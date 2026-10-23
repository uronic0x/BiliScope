"""Bounded or always-on, app-local automation. Model output never grants publication rights."""
from __future__ import annotations
import asyncio
from dataclasses import asdict,dataclass,fields,replace
from datetime import datetime,timedelta
import hashlib
import json
from pathlib import Path
import re
import threading
import time
import uuid
from .domain import AppError,canonical_url,parse_video
from .runtime import RUNTIME,inside,atomic_json,redact
from .security import evidence_findings,findings,safe_auto_comment
from .api_log import RequestLog

# Errors that must end the session: a wrong destination, lost identity, broken
# state, or a comment whose delivery is unknown. Everything else is a per-video
# failure so one bad video cannot stop a long-running session.
FATAL_CODES={'CANCELLED','AUTO_EXPIRED','AUTO_TARGET','AUTO_STATE','AUTO_MENTION_UNVERIFIED',
             'LOGIN_REQUIRED','API_KEY','SETUP_REQUIRED','POST_UNKNOWN','MENTION_CHANGED','MENTION_INVALID'}
RECOVERABLE_PREFIXES=('API_','BILI_','FRAME_','MEDIA_','ASR_','SUBTITLE_','COMMENT_')
RECOVERABLE_CODES={'NO_VIDEO_EVIDENCE','VIDEO_DURATION','PART_RANGE','WBI_KEYS','IMAGE_LIMIT',
                   'COMMENT_DUPLICATE','VIDEO_URL'}


def recoverable(code):
    """True when the next video can still be processed after this failure."""
    if code in FATAL_CODES:return False
    return code in RECOVERABLE_CODES or str(code).startswith(RECOVERABLE_PREFIXES)


def seconds_until_midnight(now):
    tomorrow=(now+timedelta(days=1)).replace(hour=0,minute=0,second=0,microsecond=0)
    return max(60.0,tomorrow.timestamp()-now.timestamp())


@dataclass
class AutoPlan:
    source_mode: str='recommendations'
    queue_text: str=''
    keyword: str=''
    start_time: str=''
    interval_minutes: int=15
    duration_minutes: int=60
    run_until_stopped: bool=False
    max_videos: int=6
    publish_comments: bool=False
    max_posts: int=3
    daily_post_limit: int=10
    daily_analysis_limit: int=40
    quality_gate: bool=False
    quality_threshold: int=6
    max_analyze_failures: int=2
    analysis_backoff_minutes: int=30
    mention_owner: bool=True
    mention_requires_quality: bool=False
    mention_only: bool=False
    owner_uid: str=''
    owner_every_minutes: int=30
    owner_daily_limit: int=3
    question: str=''
    comment_instruction: str=''

    def queue(self):
        result=[]
        for line in self.queue_text.splitlines():
            if not line.strip():continue
            bvid,part=parse_video(line.strip())
            url=canonical_url(bvid,part)
            if url not in result:result.append(url)
        return result

    def validate(self):
        if self.source_mode not in ('queue','search','recommendations'):raise AppError('AUTO_PLAN')
        if self.source_mode=='queue' and not self.queue():raise AppError('AUTO_QUEUE')
        if self.source_mode=='search' and not self.keyword.strip():raise AppError('AUTO_KEYWORD')
        if len(self.queue_text)>30000 or len(self.keyword)>200 or len(self.question)>4000 or len(self.comment_instruction)>4000:
            raise AppError('AUTO_PLAN')
        if self.start_time and not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]',self.start_time):
            raise AppError('AUTO_TIME')
        for key,low,high in [('interval_minutes',1,1440),('duration_minutes',1,1440),('max_videos',1,100),
                             ('max_posts',1,100),('daily_post_limit',1,100),('owner_every_minutes',1,1440),
                             ('daily_analysis_limit',1,1000),('quality_threshold',1,10),
                             ('max_analyze_failures',1,10),('analysis_backoff_minutes',1,1440),
                             ('owner_daily_limit',1,100)]:
            value=getattr(self,key)
            if type(value) is not int or not low<=value<=high:raise AppError('AUTO_PLAN',key)
        for key in ('publish_comments','mention_owner','run_until_stopped','quality_gate','mention_requires_quality','mention_only'):
            if type(getattr(self,key)) is not bool:raise AppError('AUTO_PLAN',key)
        # A quality-gated mention without quality checks would silently never
        # mention anyone; refuse the plan instead of degrading quietly.
        if self.mention_requires_quality and not self.mention_owner:raise AppError('AUTO_PLAN','mention_requires_quality')
        if self.mention_only and not (self.mention_owner and self.publish_comments):
            raise AppError('AUTO_PLAN','mention_only')
        if self.publish_comments and self.mention_owner and not re.fullmatch(r'[1-9][0-9]{0,19}',self.owner_uid):
            raise AppError('AUTO_OWNER')
        return self

    def save(self):
        self.validate();atomic_json(RUNTIME/'config'/'auto-plan.json',asdict(self))

    @classmethod
    def load(cls):
        p=inside(RUNTIME/'config'/'auto-plan.json')
        if not p.exists():return cls()
        obj=json.loads(p.read_text(encoding='utf-8'))
        # No enabled flag exists in persisted configuration. Restart is OFF.
        return cls(**{f.name:obj[f.name] for f in fields(cls) if f.name in obj})


def start_delay(start_time,now):
    if not start_time:return 0.0
    hour,minute=map(int,start_time.split(':'))
    if (hour,minute)==(now.hour,now.minute):return 0.0
    target=now.replace(hour=hour,minute=minute,second=0,microsecond=0)
    if target<now:target+=timedelta(days=1)
    return max(0.0,target.timestamp()-now.timestamp())


class AutoStore:
    def __init__(self,path=None):
        self.path=inside(path or RUNTIME/'state'/'auto-ledger.json')
        self.value={'version':1,'seen':{},'attempts':[],'owner_mentions':{},
                    'owner_days':{},'analyses':{},'failures':{}}
        if self.path.exists():
            try:
                if self.path.stat().st_size>16*1024*1024:raise ValueError()
                value=json.loads(self.path.read_text(encoding='utf-8'))
                if value.get('version')!=1 or not isinstance(value.get('seen'),dict) or not isinstance(value.get('attempts'),list):raise ValueError()
                if not all(isinstance(x,dict) and all(k in x for k in ('video','day','status')) for x in value['attempts']):raise ValueError()
                if not isinstance(value.get('owner_mentions',{}),dict):raise ValueError()
                for key in ('owner_days','analyses','failures'):
                    if not isinstance(value.get(key,{}),dict):raise ValueError()
                    value.setdefault(key,{})
                self.value=value
            except (ValueError,TypeError,KeyError):raise AppError('AUTO_STATE') from None

    def save(self):atomic_json(self.path,self.value)
    def seen(self,key):return key in self.value['seen']
    def mark_seen(self,key,stamp):
        self.value['seen'][key]=stamp
        if len(self.value['seen'])>10000:
            oldest=next(iter(self.value['seen']));del self.value['seen'][oldest]
        self.save()

    def failing(self,key,stamp):
        """True while this video is inside its failure backoff window."""
        item=self.value['failures'].get(key)
        return bool(item) and float(item.get('until',0))>stamp

    def mark_failed(self,key,stamp,backoff):
        item=self.value['failures'].get(key) or {'count':0,'until':0}
        item['count']=int(item.get('count',0))+1
        # Repeated failures back off exponentially; a single transient error
        # only hides the video for one interval-sized window.
        factor=min(8,2**max(0,item['count']-1))
        item['until']=stamp+backoff*factor
        item['last']=stamp
        self.value['failures'][key]=item
        if len(self.value['failures'])>2000:
            for name in [k for k,v in self.value['failures'].items() if float(v.get('until',0))<=stamp][:500]:
                del self.value['failures'][name]
        self.save()
        return item['until']

    def forget_failure(self,key):
        if self.value['failures'].pop(key,None) is not None:self.save()

    def analyses_today(self,day):
        return int(self.value['analyses'].get(day,0))

    def analysis_budget(self,day,limit):
        return self.analyses_today(day)<limit

    def count_analysis(self,day):
        self.value['analyses'][day]=self.analyses_today(day)+1
        if len(self.value['analyses'])>400:
            for name in sorted(self.value['analyses'])[:-400]:del self.value['analyses'][name]
        self.save()

    def budget(self,video,day,limit):
        # A previous unknown outcome is still an attempt, across app restarts.
        if any(x['video']==video for x in self.value['attempts']):return 'already_attempted'
        if sum(x['day']==day for x in self.value['attempts'])>=limit:return 'daily_limit'
        return ''

    def owner_due(self,uid,stamp,interval,day=None,daily_limit=None):
        previous=self.value['owner_mentions'].get(uid)
        if previous is not None and stamp-float(previous)<interval:return False
        if day is not None and daily_limit is not None:
            if int((self.value['owner_days'].get(uid) or {}).get(day,0))>=daily_limit:return False
        return True

    def reserve(self,video,day,text,owner_uid,stamp=None):
        item={'id':uuid.uuid4().hex,'video':video,'day':day,'status':'reserved_unknown',
              'sha256':hashlib.sha256((text+'\0'+owner_uid).encode()).hexdigest()}
        if owner_uid:
            now=datetime.now().timestamp() if stamp is None else stamp
            self.value['owner_mentions'][owner_uid]=now
            days=self.value['owner_days'].setdefault(owner_uid,{})
            days[day]=int(days.get(day,0))+1
        self.value['attempts'].append(item);self.save();return item

    def finish(self,item,result):
        item.update(status='submitted',rpid=str(result['rpid']),mentions_confirmed=bool(result['mentions_confirmed']))
        self.save()


class AutoRunner:
    def __init__(self,service,*,store=None,clock=time.monotonic,wall=datetime.now,waiter=None):
        self.service=service;self.stop=service.stop;self.clock=clock;self.wall=wall
        self.store=store or AutoStore();self.waiter=waiter
        self.deadline=float('inf');self.wall_deadline=float('inf');self.posts=0
        self.report=None;self.folder=None;self.trace=None

    def active(self):
        return not self.stop.is_set() and self.clock()<self.deadline and self.wall().timestamp()<self.wall_deadline
    def require_active(self):
        if not self.active():raise AppError('CANCELLED' if self.stop.is_set() else 'AUTO_EXPIRED')

    async def wait(self,seconds):
        if self.waiter:
            await self.waiter(seconds);return
        end=self.clock()+seconds
        while not self.stop.is_set() and self.clock()<end and self.wall().timestamp()<self.wall_deadline:
            await asyncio.sleep(min(0.25,max(0,end-self.clock())))

    def pause(self,plan):
        """Interval sleep, clipped to the session deadline when one exists."""
        seconds=plan.interval_minutes*60
        if self.deadline!=float('inf'):seconds=min(seconds,max(0,self.deadline-self.clock()))
        return seconds

    def emit(self,record):
        self.report['cycles'].append(record);self.flush()
        self.service.notify(('auto_update',record.copy()))

    def flush(self):
        atomic_json(self.folder/'report.json',self.report)
        atomic_json(RUNTIME/'state'/'auto-session.json',{
            'run_id':self.report['run_id'],'status':self.report['status'],
            'mode':self.report.get('mode','timeboxed'),
            'processed':len(self.report['cycles']),'posts':self.posts,
            'report':str(self.folder.relative_to(RUNTIME)).replace('\\','/')+'/report.json'})

    async def quality_score(self,ev,settings,key,record,trace=None):
        """Fail-closed content score: an unusable answer never passes the gate."""
        from .llm import Client
        try:
            value=await asyncio.to_thread(Client(settings,key,trace).score,ev)
        except AppError as error:
            record['score']=None;record['score_error']=error.code
            return None
        record['score']=value
        return value

    async def publish_mention_only(self,plan,ev,owner,score,day,record):
        """Post just `@owner` with no generated commentary."""
        if owner is None:
            record.update(status='mention_blocked',reason='owner_unavailable');self.emit(record)
            return
        reason=self.store.budget(str(ev.aid),day,plan.daily_post_limit)
        if not plan.publish_comments:
            record.update(status='mention_blocked',reason='publication_disabled');self.emit(record)
            return
        if self.posts>=plan.max_posts or reason:
            record.update(status='post_limit',reason=reason or 'session_limit');self.emit(record)
            return
        due=self.store.owner_due(owner.uid,self.wall().timestamp(),
            plan.owner_every_minutes*60,day,plan.owner_daily_limit)
        if due and plan.mention_requires_quality and (
                score is None or score<plan.quality_threshold):
            due=False;record['mention_skipped']='below_threshold'
        if not due:
            # Nothing to send: skipping still counts as a processed video.
            record['status']='mention_skipped'
            record.setdefault('mention_skipped','cooldown')
            self.emit(record)
            return
        self.require_active()
        attempt=self.store.reserve(str(ev.aid),day,'',owner.uid,self.wall().timestamp())
        result=await self.service.browser.publish(ev,'',[owner],authorize=self.require_active)
        self.store.finish(attempt,result)
        self.posts+=1
        record.update(status='submitted',published=True,rpid=result['rpid'],owner_mentioned=True,
                      owner_uid=owner.uid,owner_name=owner.name,
                      mentions_confirmed=result['mentions_confirmed'],
                      comment_url=result.get('url'),mention_only=True)
        self.emit(record)
        if not result['mentions_confirmed']:
            raise AppError('AUTO_MENTION_UNVERIFIED')

    async def run(self,plan,settings,key):
        # Freeze the trusted local UI configuration; subsequent edits only apply
        # to the next session, never to an in-flight publication destination.
        plan=replace(plan);settings=replace(settings);plan.validate();settings.validate()
        from .llm import Client
        Client(settings,key).validate_key()
        run_id=self.wall().strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:8]
        self.folder=inside(RUNTIME/'auto'/run_id);self.folder.mkdir(parents=True,exist_ok=True)
        self.report={'run_id':run_id,'status':'waiting','mode':'always' if plan.run_until_stopped else 'timeboxed',
                     'plan':asdict(plan),'model':settings.model,'cycles':[],
                     'prompt_sha256':hashlib.sha256(settings.system_prompt.encode()).hexdigest()}
        self.trace=RequestLog(self.folder)
        self.report['requests']=0
        self.flush()
        delay=start_delay(plan.start_time,self.wall())
        if plan.run_until_stopped:
            # No wall-clock deadline: only the stop switch, the daily analysis
            # budget and the per-session video cap (if any) bound this session.
            self.deadline=float('inf');self.wall_deadline=float('inf')
        else:
            self.deadline=self.clock()+delay+plan.duration_minutes*60
            self.wall_deadline=self.wall().timestamp()+delay+plan.duration_minutes*60
        if delay:
            self.service.progress('auto_waiting',plan.start_time);await self.wait(delay)
        if self.stop.is_set():
            self.report['status']='stopped';self.flush();return self.report
        if not self.active():
            self.report['status']='expired';self.flush();return self.report
        self.report['status']='running';self.flush()
        owner=None;record=None
        self.service.operation_guard=self.require_active
        try:
            if plan.publish_comments:
                nav=await self.service.browser.api('/x/web-interface/nav')
                if not nav or not nav.get('isLogin'):raise AppError('LOGIN_REQUIRED')
                if plan.mention_owner:
                    owner=await self.service.browser.lookup_user(plan.owner_uid)
                    self.service.progress('auto_owner_verified',owner.name+' (UID '+owner.uid+')')
            count=0
            while self.active() and (plan.run_until_stopped or count<plan.max_videos):
                day=self.wall().date().isoformat()
                if not self.store.analysis_budget(day,plan.daily_analysis_limit):
                    if not plan.run_until_stopped:
                        self.report['status']='analysis_limit';break
                    # Always-on sessions park until the local date changes, so
                    # the daily budget cannot be bypassed by waiting a minute.
                    self.service.progress('auto_analysis_limit')
                    await self.wait(min(seconds_until_midnight(self.wall()),3600))
                    continue
                self.service.progress('auto_selecting')
                urls=plan.queue() if plan.source_mode=='queue' else await self.service.browser.discover(plan.source_mode,plan.keyword)
                selected=None
                for url in urls:
                    try:
                        bvid,part=parse_video(url);video_key=bvid+':'+str(part)
                    except AppError:continue
                    if self.store.seen(video_key) or self.store.failing(video_key,self.wall().timestamp()):continue
                    selected=(canonical_url(bvid,part),video_key);break
                if selected is None:
                    if plan.source_mode=='queue':
                        self.report['status']='queue_exhausted';break
                    self.service.progress('auto_no_candidates')
                    await self.wait(self.pause(plan))
                    continue
                self.require_active()
                url,video_key=selected
                record={'video':video_key,'url':url,'status':'analyzing','published':False}
                try:
                    ev=await self.service.analyze(url,plan.question or (
                        '总结视频主要内容并标注时间点。' if settings.answer_language=='cn' else 'Summarize the video with timestamped evidence.'),settings,key,self.trace)
                except AppError as error:
                    if not recoverable(error.code):raise
                    # The video stays unseen, so it can be retried after backoff;
                    # the session keeps running for other candidates.
                    retry_after=self.store.mark_failed(video_key,self.wall().timestamp(),
                        plan.analysis_backoff_minutes*60)
                    failures=int(self.store.value['failures'][video_key]['count'])
                    if failures>=plan.max_analyze_failures:
                        # Give up on a persistently broken video (deleted, region
                        # locked, always unreadable) instead of retrying forever.
                        self.store.mark_seen(video_key,self.wall().isoformat())
                        self.store.forget_failure(video_key)
                        record.update(status='analysis_abandoned',error=error.code,attempts=failures)
                    else:
                        record.update(status='analysis_failed',error=error.code,
                                      attempts=failures,retry_after=retry_after)
                    self.emit(record)
                    await self.wait(self.pause(plan))
                    continue
                # Only a resolved video counts as processed; failures above are
                # recorded separately and never consume the video/analysis quota.
                self.store.mark_seen(video_key,self.wall().isoformat())
                self.store.forget_failure(video_key)
                self.store.count_analysis(self.wall().date().isoformat())
                count+=1
                if ev.bvid+':'+str(ev.part)!=video_key:
                    raise AppError('AUTO_TARGET')
                self.service.notify(('auto_video',ev))
                self.require_active()
                score=None
                if plan.quality_gate or (plan.mention_owner and plan.mention_requires_quality):
                    score=await self.quality_score(ev,settings,key,record,self.trace)
                flags=sorted(set(evidence_findings(ev,include_comments=settings.include_comments)+ev.security_findings+findings(ev.answer)))
                record['security_findings']=flags
                if plan.mention_only:
                    # Mention-only mode: no comment text is generated at all, so
                    # the model never gets a chance to produce awkward prose.
                    await self.publish_mention_only(plan,ev,owner,score,day,record)
                elif plan.quality_gate and (score is None or score<plan.quality_threshold):
                    # Low-quality videos are watched and logged, but never
                    # commented on and never used to disturb the owner.
                    record['status']='below_threshold';self.emit(record)
                elif settings.injection_guard and flags:
                    record['status']='injection_blocked';self.emit(record)
                else:
                    raw=await asyncio.to_thread(Client(settings,key,self.trace).draft,ev,plan.comment_instruction or (
                        '写一条具体、简洁的观察，不添加 @ 或链接。' if settings.answer_language=='cn' else 'Write a specific concise observation, without @ mentions or links.'))
                    self.require_active()
                    record['draft']=redact(raw)
                    atomic_json(self.folder/(str(count).zfill(3)+'-draft.json'),record)
                    try:
                        text=safe_auto_comment(raw,strict=settings.injection_guard)
                    except AppError as error:
                        record.update(status='output_blocked',reason=error.detail);self.emit(record)
                    else:
                        reason=self.store.budget(str(ev.aid),self.wall().date().isoformat(),plan.daily_post_limit)
                        if not plan.publish_comments:
                            record['status']='draft_only';self.emit(record)
                        elif self.posts>=plan.max_posts or reason:
                            record.update(status='post_limit',reason=reason or 'session_limit');self.emit(record)
                        else:
                            self.require_active()
                            due=owner is not None and self.store.owner_due(owner.uid,self.wall().timestamp(),
                                plan.owner_every_minutes*60,day,plan.owner_daily_limit)
                            if due and plan.mention_requires_quality and (
                                    score is None or score<plan.quality_threshold):
                                due=False;record['mention_skipped']='below_threshold'
                            mentions=[owner] if due else []
                            attempt=self.store.reserve(str(ev.aid),self.wall().date().isoformat(),text,owner.uid if due else '',self.wall().timestamp())
                            # Browser calls this again immediately before POST,
                            # after awaited login and UID verification.
                            result=await self.service.browser.publish(ev,text,mentions,authorize=self.require_active)
                            self.store.finish(attempt,result)
                            self.posts+=1
                            record.update(status='submitted',published=True,rpid=result['rpid'],owner_mentioned=due,
                                          owner_uid=owner.uid if due else '',owner_name=owner.name if due else '',
                                          mentions_confirmed=result['mentions_confirmed'],
                                          comment_url=result.get('url'))
                            self.emit(record)
                            if due and not result['mentions_confirmed']:
                                raise AppError('AUTO_MENTION_UNVERIFIED')
                if (plan.run_until_stopped or count<plan.max_videos) and self.active():
                    self.service.progress('auto_interval')
                    await self.wait(self.pause(plan))
            if self.report['status']=='running':
                self.report['status']='stopped' if self.stop.is_set() else 'expired' if not self.active() else 'video_limit'
        except AppError as error:
            self.report['status']='stopped' if error.code=='CANCELLED' else 'expired' if error.code=='AUTO_EXPIRED' else 'error'
            self.report['error']=error.code
            if record is not None and not any(x is record for x in self.report['cycles']):
                record.update(status='stopped' if error.code=='CANCELLED' else 'expired' if error.code=='AUTO_EXPIRED' else 'error',error=error.code)
                self.emit(record)
            if error.code not in ('CANCELLED','AUTO_EXPIRED'):raise
        except BaseException:
            self.report['status']='error';raise
        finally:
            self.service.operation_guard=None
            self.report['posts']=self.posts
            if self.trace:self.report['requests']=self.trace.count
            self.flush()
        return self.report
