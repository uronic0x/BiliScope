"""Session-scoped Bilibili access via Patchright; no independent cookie export."""
from __future__ import annotations
import asyncio
import json
import logging
from pathlib import Path
import time
from urllib.parse import urlencode, urlparse
from .domain import AppError, Evidence, Mention, canonical_url, parse_video, wbi_query, comment_payload
from .runtime import ROOT, RUNTIME, inside, atomic_json, remember_secret

log=logging.getLogger('biliscope')


def media_url(value):
    p=urlparse(value)
    host=p.hostname or ''
    if p.scheme!='https' or p.username or p.password:
        raise AppError('MEDIA_URL')
    if not any(host==suffix or host.endswith('.'+suffix) for suffix in
               ('bilivideo.com','bilivideo.cn','bilibili.com','hdslb.com','biliimg.com','bilivideo.net')):
        raise AppError('MEDIA_URL')
    # First-party CDN (mcdn.bilivideo.cn) serves on high ports; third-party
    # PCDN hosts remain blocked by the suffix list above.
    if p.port not in (None,443) and not 1024<=p.port<=65535:
        raise AppError('MEDIA_URL')
    return value


def stream_candidates(item):
    urls=[]
    for key in ('baseUrl','base_url','backupUrl','backup_url'):
        value=item.get(key)
        if isinstance(value,str): urls.append(value)
        elif isinstance(value,list): urls.extend(x for x in value if isinstance(x,str))
    return urls


def pick_stream(choices):
    # Lowest bandwidth first; accept the first URL that passes media_url.
    for item in sorted(choices,key=lambda x:x.get('bandwidth',10**10)):
        for url in stream_candidates(item):
            try: return media_url(url)
            except AppError: continue
    raise AppError('MEDIA_URL')


class Browser:
    def __init__(self):
        self.driver=None
        self.context=None
        self.page=None
        self._keys=None
        self._last_read=0.0
        self._last_post=0.0
        self._last_fingerprint=None
        self._video_files={}
        self.stop=None

    async def start(self,headless=False):
        if self.context:
            if not self.page or self.page.is_closed():
                self.page=await self.context.new_page()
            return
        try:
            from patchright.async_api import async_playwright
        except ImportError:
            raise AppError('SETUP_REQUIRED') from None
        self.driver=await async_playwright().start()
        args=[
          '--disable-background-networking','--disable-component-update',
          '--disable-sync','--disable-breakpad','--disable-crash-reporter',
          '--disable-domain-reliability','--disable-logging','--no-first-run',
          '--disable-dev-shm-usage','--disk-cache-size=134217728','--media-cache-size=67108864',
          '--no-default-browser-check','--noerrdialogs',
          '--disk-cache-dir='+str(inside(RUNTIME/'cache'/'chromium')),
          '--crash-dumps-dir='+str(inside(RUNTIME/'logs'/'chromium-crashes')),
          '--log-file='+str(inside(RUNTIME/'logs'/'chromium.log')),
          '--disable-features=MediaRouter,OptimizationHints,AutofillServerCommunication,NetworkTimeServiceQuerying',
        ]
        try:
            from .browser_install import executable
            self.context=await self.driver.chromium.launch_persistent_context(
                executable_path=str(executable()),
                user_data_dir=str(inside(RUNTIME/'browser-profile')),
                headless=headless,chromium_sandbox=True,
                viewport={'width':1280,'height':850},args=args,
                downloads_path=str(inside(RUNTIME/'downloads')),
                traces_dir=str(inside(RUNTIME/'logs'/'traces')),
                accept_downloads=False,service_workers='block',
                env=dict(__import__('os').environ))
            self.context.set_default_timeout(20000)
            self.context.set_default_navigation_timeout(45000)
            # The site needs its first-party analytics/session endpoints to work.
            # Block well-known third-party analytics; never call this total silence.
            await self.context.route('**/*',self._route)
            self.page=self.context.pages[0] if self.context.pages else await self.context.new_page()
        except Exception:
            await self.close()
            raise AppError('BROWSER_START') from None

    async def _route(self,route):
        host=urlparse(route.request.url).hostname or ''
        denied=('google-analytics.com','googletagmanager.com','doubleclick.net','sentry.io')
        if any(host==d or host.endswith('.'+d) for d in denied):
            await route.abort()
        else:
            await route.continue_()

    async def close(self):
        if self.context:
            try:
                await asyncio.wait_for(self.context.close(),12)
            except Exception:
                log.warning('Browser close did not complete cleanly')
        self.context=None;self.page=None
        if self.driver:
            try: await self.driver.stop()
            except Exception: pass
        self.driver=None
        self.cleanup_media()

    def cleanup_media(self):
        for path in self._video_files.values():
            try: path.unlink(missing_ok=True)
            except OSError: log.warning('Deferred media cleanup; file still open')
        self._video_files.clear()

    async def login(self):
        await self.start()
        await self.page.goto('https://www.bilibili.com/',wait_until='domcontentloaded')
        return 'LOGIN_BROWSER'

    async def _response_json(self,response,*,require_success=True):
        try:
            if response.status!=200:
                raise AppError('BILI_HTTP',str(response.status))
            obj=await response.json()
            if require_success and obj.get('code')!=0:
                code=obj.get('code')
                raise AppError('LOGIN_REQUIRED' if code in (-101,-111) else 'BILI_API',str(code))
            return obj
        finally:
            await response.dispose()

    async def api(self,path,params=None,*,signed=False,raw=False):
        await self.start()
        wait=0.35-(time.monotonic()-self._last_read)
        if wait>0: await asyncio.sleep(wait)
        self._last_read=time.monotonic()
        params=params or {}
        if signed:
            if not self._keys:
                nav=await self.api('/x/web-interface/nav',raw=True)
                wbi=nav.get('data',{}).get('wbi_img',{})
                try:
                    self._keys=tuple(Path(urlparse(wbi[k]).path).stem for k in ('img_url','sub_url'))
                except KeyError:
                    raise AppError('WBI_KEYS') from None
            query=wbi_query(params,*self._keys,time.time())
        else:
            query=urlencode(params)
        try:
            response=await self.context.request.get('https://api.bilibili.com'+path+('?' +query if query else ''),
                headers={'Referer':'https://www.bilibili.com/'},timeout=30000,max_redirects=0)
        except Exception:
            raise AppError('BILI_NETWORK') from None
        try:
            obj=await self._response_json(response,require_success=not raw)
        except AppError:
            if signed: self._keys=None
            raise
        except Exception:
            raise AppError('BILI_RESPONSE') from None
        return obj if raw else obj.get('data')

    async def resolve(self,value):
        try:
            return parse_video(value)
        except AppError:
            u=urlparse(value.strip())
            if u.scheme!='https' or u.hostname!='b23.tv' or u.username or u.password or u.port not in (None,443):
                raise
            await self.start()
            # Follow the platform short link, then accept only a BV video target.
            await self.page.goto(value.strip(),wait_until='domcontentloaded')
            return parse_video(self.page.url)

    async def load(self,value,max_minutes):
        bvid,part=await self.resolve(value)
        data=await self.api('/x/web-interface/view',{'bvid':bvid})
        pages=data.get('pages') or []
        if part>len(pages):
            raise AppError('PART_RANGE')
        segment=pages[part-1]
        duration=float(segment.get('duration') or data['duration'])
        if duration<=0:
            raise AppError('VIDEO_DURATION')
        ev=Evidence(bvid,part,int(data['aid']),int(segment['cid']),data['title'],
            data.get('owner',{}).get('name',''),duration,min(duration,max_minutes*60),data.get('desc',''))
        await self.page.goto(ev.url,wait_until='domcontentloaded')
        if ev.scope_end<ev.duration:
            ev.notes.append('PARTIAL_ANALYSIS: first '+str(ev.scope_end)+' seconds only')
        try:
            await self.subtitle(ev)
        except AppError as e:
            # Differentiate unavailable/auth/risk from a successful empty list.
            ev.notes.append('SUBTITLE_UNAVAILABLE: '+e.code+' '+e.detail)
        return ev

    async def subtitle(self,ev):
        data=await self.api('/x/player/wbi/v2',{'aid':ev.aid,'cid':ev.cid},signed=True)
        tracks=(data or {}).get('subtitle',{}).get('subtitles',[])
        if not tracks:
            ev.notes.append('NO_SUBTITLE_TRACKS_RETURNED')
            return
        tracks=sorted(tracks,key=lambda x:(not str(x.get('lan','')).startswith('zh'),str(x.get('lan','')).startswith('ai-')))
        track=tracks[0]
        url=track['subtitle_url']
        if url.startswith('//'): url='https:'+url
        media_url(url)
        response=await self.context.request.get(url,timeout=30000,max_redirects=0)
        try:
            if response.status!=200: raise AppError('SUBTITLE_HTTP',str(response.status))
            body=await response.body()
            if len(body)>8*1024*1024: raise AppError('SUBTITLE_LIMIT')
            obj=json.loads(body)
        finally:
            await response.dispose()
        ev.transcript=[{'from':float(x['from']),'to':min(float(x['to']),ev.scope_end),'content':str(x['content'])}
                       for x in obj.get('body',[]) if float(x.get('from',ev.scope_end))<ev.scope_end]
        ev.transcript_source='bilibili-subtitle:'+str(track.get('lan','unknown'))
        if not ev.transcript:
            ev.notes.append('EMPTY_SUBTITLE_BODY')

    async def comments(self,ev):
        # Legacy sorted read endpoint avoids making page selectors a hard dependency.
        data=await self.api('/x/v2/reply',{'oid':ev.aid,'type':1,'sort':2,'pn':1,'ps':20})
        result=[]
        for item in (data or {}).get('replies') or []:
            member=item.get('member',{})
            rpid=str(item.get('rpid_str') or item['rpid'])
            root=str(item.get('root_str') or item.get('root') or '0')
            result.append({'rpid':rpid,
              'root':rpid if root=='0' else root,
              'uid':str(member.get('mid','')),'name':member.get('uname',''),
              'message':item.get('content',{}).get('message',''),'likes':item.get('like',0)})
        ev.comments=result
        return result

    async def discover(self,mode,keyword=''):
        if mode=='recommendations':
            # Signed feed endpoint; the legacy unsigned endpoint now returns -400.
            data=await self.api('/x/web-interface/wbi/index/top/feed/rcmd',{'ps':20,'fresh_type':3},signed=True)
            items=(data or {}).get('item') or []
        elif mode=='search' and keyword.strip():
            data=await self.api('/x/web-interface/wbi/search/type',
                {'search_type':'video','keyword':keyword.strip(),'order':'pubdate','page':1,'page_size':20},signed=True)
            items=(data or {}).get('result') or []
        else:raise AppError('AUTO_PLAN')
        result=[]
        for item in items:
            # IDs from the selected source are validated. Ignore arbitrary
            # links, ad destinations and commands returned in page text.
            bvid=item.get('bvid')
            if isinstance(bvid,str):
                try:url=canonical_url(parse_video(bvid)[0])
                except AppError:continue
                if url not in result:result.append(url)
        return result

    async def lookup_user(self,uid):
        if not str(uid).isdigit() or int(uid)<=0 or len(str(uid))>20:
            raise AppError('MENTION_INVALID')
        data=await self.api('/x/web-interface/card',{'mid':str(uid)})
        card=(data or {}).get('card',{})
        if str(card.get('mid'))!=str(uid) or not card.get('name'):
            raise AppError('MENTION_INVALID')
        return Mention(str(uid),card['name'])

    async def frame(self,ev,seconds):
        try:
            return await self._browser_frame(ev,seconds)
        except AppError:
            # Unbranded Chromium may lack the site's chosen proprietary codec.
            # Decode the same video stream with open-source FFmpeg via PyAV.
            return await self._native_frame(ev,seconds)

    async def _browser_frame(self,ev,seconds):
        await self.start()
        # The user may have navigated elsewhere in the visible browser.
        try: current=parse_video(self.page.url)
        except AppError: current=None
        if current!=(ev.bvid,ev.part):
            await self.page.goto(ev.url,wait_until='domcontentloaded')
        video=self.page.locator('video').first
        try:
            await video.wait_for(state='visible',timeout=30000)
            result=await video.evaluate('''async (v, t) => {
              if (v.readyState < 1) await new Promise((resolve,reject)=>{
                let done=false; const fail=setTimeout(()=>{if(!done){done=true;reject(Error('metadata timeout'))}},15000);
                v.addEventListener('loadedmetadata',()=>{if(!done){done=true;clearTimeout(fail);resolve()}},{once:true});
              });
              const target=Math.min(t, Math.max(0,v.duration-0.2));
              v.muted=true;
              if(Math.abs(v.currentTime-target)>0.15 || v.readyState<2) {
                await new Promise((resolve,reject)=>{
                  let done=false;
                  const timer=setTimeout(()=>{if(!done){done=true;reject(Error('seek timeout'))}},20000);
                  const finish=()=>{if(!done && Math.abs(v.currentTime-target)<1 && v.readyState>=2){done=true;clearTimeout(timer);resolve()}};
                  v.addEventListener('seeked',finish,{once:true});
                  v.addEventListener('loadeddata',finish,{once:true});
                  v.currentTime=target; finish();
                });
              }
              v.pause();
              await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
              if(!v.videoWidth || !v.videoHeight || v.readyState<2) throw Error('no decoded frame');
              // Canvas copies decoded pixels only, excluding UI overlays, comments and profile info.
              const c=document.createElement('canvas');
              const ratio=Math.min(1,1024/v.videoWidth,768/v.videoHeight);
              c.width=Math.round(v.videoWidth*ratio);c.height=Math.round(v.videoHeight*ratio);
              c.getContext('2d').drawImage(v,0,0,c.width,c.height);
              let image=null;
              try { image=c.toDataURL('image/png'); } catch(e) {}
              return {actual_s:v.currentTime,width:c.width,height:c.height,image};
            }''',seconds)
            if abs(float(result['actual_s'])-seconds)>1.5:
                raise AppError('FRAME_MISMATCH')
            folder=inside(RUNTIME/'evidence'/f'{ev.bvid}-p{ev.part}')
            folder.mkdir(parents=True,exist_ok=True)
            target=folder/f'frame-{int(seconds*1000):010d}.png'
            if result.get('image'):
                import base64
                raw=base64.b64decode(result['image'].split(',',1)[1],validate=True)
                if len(raw)>2*1024*1024: raise AppError('IMAGE_LIMIT')
                target.write_bytes(raw)
            else:
                # Cross-origin tainted canvas: screenshot the video element itself.
                await video.screenshot(path=str(target),type='png',timeout=15000)
                if target.stat().st_size>2*1024*1024:
                    target.unlink();raise AppError('IMAGE_LIMIT')
            return {'requested_s':seconds,'actual_s':round(float(result['actual_s']),3),
                    'path':str(target.relative_to(ROOT)),'source':'decoded-browser-video'}
        except AppError:
            raise
        except Exception:
            raise AppError('FRAME_FAILED') from None

    async def _native_frame(self,ev,seconds):
        key=(ev.bvid,ev.cid)
        if key not in self._video_files or not self._video_files[key].exists():
            data=await self.api('/x/player/wbi/playurl',{'bvid':ev.bvid,'cid':ev.cid,'fnval':16,'qn':32,'fourk':0},signed=True)
            choices=(data or {}).get('dash',{}).get('video') or []
            if not choices: raise AppError('FRAME_FAILED')
            url=pick_stream(choices)
            target=inside(RUNTIME/'downloads'/f'{ev.bvid}-{ev.cid}-video.m4s')
            import urllib.request
            from .llm import NoRedirect
            opener=urllib.request.build_opener(NoRedirect())
            ua=await self.page.evaluate('navigator.userAgent')
            req=urllib.request.Request(url,headers={'User-Agent':ua,'Referer':ev.url})
            await asyncio.to_thread(self._download_audio,opener,req,target,getattr(self,'max_download_mb',256))
            self._video_files[key]=target
        return await asyncio.to_thread(self._decode_frame,self._video_files[key],ev,seconds)

    @staticmethod
    def _decode_frame(path,ev,seconds):
        import av
        try:
            with av.open(str(path)) as container:
                stream=container.streams.video[0]
                container.seek(int(seconds/float(stream.time_base)),stream=stream,backward=True)
                decoded=None
                for frame in container.decode(stream):
                    if frame.time is not None and float(frame.time)>=seconds-0.05:
                        decoded=frame;break
                if decoded is None or abs(float(decoded.time)-seconds)>1.5:
                    raise AppError('FRAME_MISMATCH')
                ratio=min(1,1024/decoded.width,768/decoded.height)
                image=decoded.reformat(width=max(1,int(decoded.width*ratio)),height=max(1,int(decoded.height*ratio)),format='rgb24')
                codec=av.CodecContext.create('png','w')
                codec.width=image.width;codec.height=image.height;codec.pix_fmt='rgb24'
                raw=b''.join(bytes(p) for p in codec.encode(image))+b''.join(bytes(p) for p in codec.encode(None))
                if len(raw)>2*1024*1024:raise AppError('IMAGE_LIMIT')
                folder=inside(RUNTIME/'evidence'/f'{ev.bvid}-p{ev.part}')
                folder.mkdir(parents=True,exist_ok=True)
                target=folder/f'frame-{int(seconds*1000):010d}.png';target.write_bytes(raw)
                return {'requested_s':seconds,'actual_s':round(float(decoded.time),3),
                   'path':str(target.relative_to(ROOT)),'source':'decoded-video-stream-pyav'}
        except AppError:raise
        except Exception:raise AppError('FRAME_FAILED') from None

    async def audio(self,ev,max_mb):
        data=await self.api('/x/player/wbi/playurl',{'bvid':ev.bvid,'cid':ev.cid,'fnval':16,'qn':32,'fourk':0},signed=True)
        choices=(data or {}).get('dash',{}).get('audio') or []
        if not choices:
            raise AppError('AUDIO_UNAVAILABLE')
        url=pick_stream(choices)
        target=inside(RUNTIME/'downloads'/f'{ev.bvid}-{ev.cid}.m4a')
        # APIRequestContext buffers responses. Use a bounded streaming HTTPS read,
        # with only the current browser UA; CDN audio does not need login cookies.
        agent=await self.page.evaluate('navigator.userAgent')
        import urllib.request
        from .llm import NoRedirect
        opener=urllib.request.build_opener(NoRedirect())
        req=urllib.request.Request(url,headers={'User-Agent':agent,'Referer':ev.url})
        return await asyncio.to_thread(self._download_audio,opener,req,target,max_mb)

    def _download_audio(self,opener,req,target,max_mb):
        temp=target.with_suffix('.partial')
        try:
            with opener.open(req,timeout=40) as response,temp.open('wb') as out:
                limit=int(max_mb)*1024*1024
                if int(response.headers.get('Content-Length','0'))>limit:
                    raise AppError('DOWNLOAD_LIMIT')
                size=0
                while block:=response.read(1024*512):
                    if self.stop and self.stop.is_set():raise AppError('CANCELLED')
                    size+=len(block)
                    if size>limit: raise AppError('DOWNLOAD_LIMIT')
                    out.write(block)
            temp.replace(target)
            return target
        except AppError:
            raise
        except Exception:
            raise AppError('AUDIO_DOWNLOAD') from None
        finally:
            temp.unlink(missing_ok=True)

    async def publish(self,ev,text,mentions,root=0,parent=0,*,authorize=None):
        if authorize:authorize()
        nav=await self.api('/x/web-interface/nav')
        if not nav or not nav.get('isLogin'):
            raise AppError('LOGIN_REQUIRED')
        # Revalidate the UID bindings immediately before posting.
        for m in mentions:
            current=await self.lookup_user(m.uid)
            if current.name!=m.name:
                raise AppError('MENTION_CHANGED')
        cookies=await self.context.cookies('https://www.bilibili.com/')
        csrf=next((x['value'] for x in cookies if x['name']=='bili_jct'),'')
        for x in cookies:
            if x['name'] in ('SESSDATA','bili_jct'): remember_secret(x['value'])
        form=comment_payload(ev.aid,text,mentions,csrf,root,parent)
        # Never retry a write: a timeout can mean the server already accepted it.
        fingerprint=json.dumps({k:v for k,v in form.items() if k!='csrf'},sort_keys=True)
        if fingerprint==self._last_fingerprint or time.monotonic()-self._last_post<15:
            raise AppError('COMMENT_DUPLICATE')
        if authorize:authorize()
        self._last_fingerprint=fingerprint;self._last_post=time.monotonic()
        try:
            response=await self.context.request.post('https://api.bilibili.com/x/v2/reply/add',
              form=form,headers={'Referer':ev.url,'Origin':'https://www.bilibili.com'},
              timeout=30000,max_redirects=0)
            obj=await self._response_json(response)
        except AppError:
            raise
        except Exception:
            raise AppError('POST_UNKNOWN') from None
        data=obj.get('data') or {}
        reply=data.get('reply') or {}
        rpid=reply.get('rpid_str') or data.get('rpid_str') or reply.get('rpid') or data.get('rpid')
        if not rpid:
            raise AppError('POST_UNKNOWN')
        members=reply.get('content',{}).get('members') or []
        confirmed={str(x.get('mid')) for x in members}
        return {'rpid':str(rpid),'url':ev.url+'&comment_on=1&comment_root_id='+str(root or rpid),
                'mentions_confirmed':all(m.uid in confirmed for m in mentions),
                'status':'submitted_not_visibility_verified'}
