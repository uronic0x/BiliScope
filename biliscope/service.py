from __future__ import annotations
import asyncio
import concurrent.futures
from datetime import datetime,timezone
import json
import logging
import threading
from .browser import Browser
from .domain import AppError,sample_times,validate_times,timestamp
from .llm import Client,image_blocks
from .runtime import ROOT,RUNTIME,inside,atomic_json,redact

log=logging.getLogger('biliscope')

class Service:
    def __init__(self,notify):
        self.notify=notify
        self.browser=Browser()
        self.evidence=None
        self.last_trace=None
        self.stop=threading.Event()
        self.operation_guard=None
        self.browser.stop=self.stop
        self.loop=asyncio.new_event_loop()
        self.thread=threading.Thread(target=self._run,name='BiliScopeWorker',daemon=True)
        self.thread.start()

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()
        pending=asyncio.all_tasks(self.loop)
        for task in pending: task.cancel()
        if pending:
            self.loop.run_until_complete(asyncio.gather(*pending,return_exceptions=True))
        self.loop.close()

    def submit(self,awaitable):
        self.stop.clear()
        return asyncio.run_coroutine_threadsafe(awaitable,self.loop)

    def check(self):
        if self.stop.is_set(): raise AppError('CANCELLED')
        if self.operation_guard:self.operation_guard()

    def progress(self,key,detail=''):
        self.notify(('progress',key,detail))

    async def analyze(self,target,question,settings,key,recorder=None):
        self.browser.max_download_mb=settings.max_download_mb
        # Manual analyses get their own trace folder so every prompt that was
        # actually sent stays reviewable after the fact.
        if recorder is None:
            from .api_log import RequestLog,new_session_folder,prune
            prune()
            recorder=RequestLog(new_session_folder('manual'))
            self.last_trace=recorder
        try:
            return await self._analyze(target,question,settings,key,recorder)
        finally:
            self.browser.cleanup_media()

    async def _analyze(self,target,question,settings,key,recorder=None):
        self.check();settings.validate()
        client=Client(settings,key,recorder)
        client.validate_key()
        self.progress('loading')
        ev=await self.browser.load(target,settings.max_minutes)
        self.check()
        # Commit evidence only after this video is resolved successfully.
        self.evidence=ev;ev.question=question
        if not ev.transcript and settings.asr:
            self.progress('audio_download')
            try:
                # Download does not hold the browser event loop during I/O.
                audio=await self.browser.audio(ev,settings.max_download_mb)
                from .asr import transcribe
                try:
                    self.check()
                    ev.transcript=await asyncio.to_thread(transcribe,audio,ev.scope_end,self.progress,self.stop)
                    ev.transcript_source='local-whisper-base-int8; approximate 28s chunk timestamps'
                    if not ev.transcript: ev.notes.append('ASR_RETURNED_NO_SPEECH')
                finally:
                    audio.unlink(missing_ok=True)
            except AppError as e:
                if e.code=='CANCELLED': raise
                ev.notes.append('ASR_UNAVAILABLE: '+e.code)
                self.progress('evidence_warning',e.code)
        elif not ev.transcript:
            ev.notes.append('ASR_DISABLED')
        self.check()
        try: await self.browser.comments(ev)
        except AppError as e: ev.notes.append('COMMENTS_UNAVAILABLE: '+e.code)
        if settings.vision:
            for t in sample_times(ev.scope_end,settings.initial_frames):
                self.check();self.progress('capturing',timestamp(t))
                try: ev.frames.append(await self.browser.frame(ev,t))
                except AppError as e:
                    ev.notes.append('FRAME_UNAVAILABLE at '+str(t)+': '+e.code)
        else:
            ev.notes.append('VISION_DISABLED: model receives text only')
        self.check()
        if not ev.transcript and not ev.frames:
            # Titles, descriptions and comments alone are not video understanding.
            self._save_evidence(ev)
            raise AppError('NO_VIDEO_EVIDENCE')
        self.progress('analyzing')
        from .security import evidence_findings,findings
        ev.security_findings=evidence_findings(ev,include_comments=settings.include_comments)
        messages=client.messages(ev,question)
        remaining=settings.extra_frames if settings.vision and settings.function_tools else 0
        tool_count=0
        while True:
            self.check()
            message=await asyncio.to_thread(client.complete,messages,
                tools=remaining>0 and tool_count<2,purpose='analysis' if tool_count==0 else 'analysis-frames')
            self.check()
            calls=message.get('tool_calls') or []
            if not calls:
                ev.answer=message.get('content') or ''
                if not ev.answer: raise AppError('API_RESPONSE')
                break
            if tool_count>=2:
                raise AppError('API_TOOL_LIMIT')
            messages.append(message)
            all_images=[]
            # Bound every provider-generated action; there is no publish tool.
            for call in calls[:8]:
                self.check()
                content=[]
                try:
                    if call.get('function',{}).get('name')!='capture_frames' or remaining<=0 or tool_count>=2:
                        raise AppError('FRAME_REQUEST')
                    args=json.loads(call['function']['arguments'])
                    seconds=validate_times(args['seconds'],ev.scope_end,remaining)
                    new=[]
                    # Count attempted captures, including failures, against budget.
                    for t in seconds:
                        self.check();remaining-=1
                        try:
                            f=await self.browser.frame(ev,t)
                            ev.frames.append(f);new.append(f)
                        except AppError as e:
                            ev.notes.append('FRAME_UNAVAILABLE at '+str(t)+': '+e.code)
                    messages.append({'role':'tool','tool_call_id':call['id'],
                       'content':json.dumps({'captured':[{'actual_s':x['actual_s']} for x in new],'remaining':remaining})})
                    if new: content=image_blocks(new)
                except (AppError,KeyError,ValueError,TypeError) as e:
                    messages.append({'role':'tool','tool_call_id':str(call.get('id','invalid')),
                                     'content':json.dumps({'error':e.code if isinstance(e,AppError) else 'FRAME_REQUEST'})})
                if content:
                    all_images.extend(content)
            if len(calls)>8: raise AppError('API_TOOL_LIMIT')
            if all_images:
                messages.append({'role':'user','content':all_images})
            tool_count+=1
        ev.security_findings=sorted(set(ev.security_findings+findings(ev.answer)))
        self._save_evidence(ev)
        self.progress('complete')
        return ev

    def _save_evidence(self,ev):
        folder=inside(RUNTIME/'evidence'/f'{ev.bvid}-p{ev.part}')
        folder.mkdir(parents=True,exist_ok=True)
        atomic_json(folder/'evidence.json',ev.to_dict())

    async def comments(self):
        if not self.evidence: raise AppError('LOAD_FIRST')
        return await self.browser.comments(self.evidence)

    async def draft(self,instruction,settings,key):
        if not self.evidence or not self.evidence.answer: raise AppError('LOAD_FIRST')
        return await asyncio.to_thread(Client(settings,key).draft,self.evidence,instruction)

    async def run_auto(self,plan,settings,key):
        from .auto import AutoRunner
        return await AutoRunner(self).run(plan,settings,key)

    async def api_test(self,settings,key):
        return await asyncio.to_thread(Client(settings,key).test)

    async def publish(self,text,mentions,root=0,parent=0):
        if not self.evidence: raise AppError('LOAD_FIRST')
        return await self.browser.publish(self.evidence,text,mentions,root,parent)

    def export(self):
        ev=self.evidence
        if not ev: raise AppError('LOAD_FIRST')
        name=f'{ev.bvid}-p{ev.part}-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        folder=inside(RUNTIME/'exports');folder.mkdir(exist_ok=True)
        atomic_json(folder/(name+'.json'),ev.to_dict())
        lines=[f'# {ev.title}', '',ev.url,'',f'Analyzed: 00:00–{timestamp(ev.scope_end)} / {timestamp(ev.duration)}',
               f'Transcript: {ev.transcript_source}','','## Analysis','',ev.answer,'','## Evidence notes','']
        lines += ['- '+x for x in ev.notes]
        lines+=['','## Frames','']
        for f in ev.frames:
            path=inside(ROOT/f['path'])
            rel=__import__('os').path.relpath(path,folder).replace('\\','/')
            lines += [f"[{timestamp(f['actual_s'])}]({ev.url}&t={int(f['actual_s'])})",'',f'![Frame]({rel})','']
        (folder/(name+'.md')).write_text('\n'.join(lines),encoding='utf-8')
        return folder/(name+'.md')

    def shutdown(self):
        self.stop.set()
        async def close():
            await self.browser.close()
        future=asyncio.run_coroutine_threadsafe(close(),self.loop)
        def finish(_): self.loop.call_soon_threadsafe(self.loop.stop)
        future.add_done_callback(finish)
        return future
