from __future__ import annotations
from dataclasses import dataclass, field, asdict
import hashlib
import json
import math
import re
from urllib.parse import parse_qs, urlencode, urlparse, quote

class AppError(RuntimeError):
    def __init__(self, code, detail=''):
        self.code, self.detail = code, str(detail)
        super().__init__(code + (': '+self.detail if self.detail else ''))


def parse_video(value: str):
    text=value.strip()
    if re.fullmatch(r'BV[A-Za-z0-9]{10}',text):
        return text,1
    parsed=urlparse(text)
    if parsed.scheme!='https' or parsed.hostname not in ('www.bilibili.com','bilibili.com') or parsed.username or parsed.password or parsed.port not in (None,443):
        raise AppError('VIDEO_URL')
    match=re.fullmatch(r'/video/(BV[A-Za-z0-9]{10})/?',parsed.path)
    if not match:
        raise AppError('VIDEO_URL')
    try:
        part=int(parse_qs(parsed.query).get('p',['1'])[0])
    except ValueError:
        raise AppError('VIDEO_URL')
    if not 1<=part<=10000:
        raise AppError('VIDEO_URL')
    return match.group(1),part


def canonical_url(bvid,part=1):
    if not re.fullmatch(r'BV[A-Za-z0-9]{10}',bvid):
        raise AppError('VIDEO_URL')
    return f'https://www.bilibili.com/video/{bvid}/?p={int(part)}'


def timestamp(seconds):
    total=max(0,int(seconds))
    return f'{total//3600:02}:{total//60%60:02}:{total%60:02}' if total>=3600 else f'{total//60:02}:{total%60:02}'


def sample_times(duration, count):
    if duration<=0 or count<=0:
        return []
    return sorted({round(min(max(0.1,duration*(i+0.5)/count),max(0,duration-0.25)),2) for i in range(count)})


def validate_times(values,duration,limit):
    if not isinstance(values,list) or len(values)>limit:
        raise AppError('FRAME_REQUEST')
    result=[]
    for v in values:
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<=v<duration:
            raise AppError('FRAME_REQUEST')
        t=round(float(v),2)
        if t not in result:
            result.append(t)
    return result


WBI_ORDER=[46,47,18,2,53,8,23,32,15,50,10,31,58,3,45,35,27,43,5,49,33,9,42,19,29,28,14,39,12,38,41,13,37,48,7,16,24,55,40,61,26,17,0,1,60,51,30,4,22,25,54,21,56,59,6,63,57,62,11,36,20,34,44,52]

def wbi_query(params,img_key,sub_key,now):
    joined=img_key+sub_key
    if len(joined)<64:
        raise AppError('WBI_KEYS')
    mixin=''.join(joined[i] for i in WBI_ORDER)[:32]
    clean={k:re.sub(r"[!'()*]",'',str(v)) for k,v in params.items()}
    clean['wts']=str(int(now))
    query=urlencode(sorted(clean.items()),quote_via=quote)
    return query+'&w_rid='+hashlib.md5((query+mixin).encode()).hexdigest()


@dataclass
class Mention:
    uid: str
    name: str

    def __post_init__(self):
        if not re.fullmatch(r'[1-9][0-9]{0,19}',str(self.uid)) or not self.name or any(c in self.name for c in '\r\n'):
            raise AppError('MENTION_INVALID')
        self.uid=str(self.uid)


def comment_payload(aid,text,mentions,csrf,root=0,parent=0):
    if not isinstance(aid,int) or aid<=0 or not csrf:
        raise AppError('LOGIN_REQUIRED')
    # An empty body is only valid when it still carries a mention: the
    # "mention only, no commentary" mode submits just the @ prefix.
    if not str(text).strip() and not mentions:
        raise AppError('COMMENT_EMPTY')
    if len(mentions)>5 or len({m.name for m in mentions})!=len(mentions) or len({m.uid for m in mentions})!=len(mentions):
        raise AppError('MENTION_AMBIGUOUS')
    # The web API requires both rendered names and the explicit name→UID map.
    prefix=''.join('@'+m.name+' ' for m in mentions)
    message=(prefix+str(text).strip()).strip()
    if not message:
        raise AppError('COMMENT_EMPTY')
    if len(message)>1000:
        raise AppError('COMMENT_LONG')
    if (root or parent) and not (int(root)>0 and int(parent)>0):
        raise AppError('REPLY_TARGET')
    d={'oid':str(aid),'type':'1','message':message,'plat':'1','csrf':csrf,
       'at_name_to_mid':json.dumps({m.name:int(m.uid) for m in mentions},ensure_ascii=False),
       'gaia_source':'main_web'}
    if root:
        d.update(root=str(root),parent=str(parent))
    return d


@dataclass
class Evidence:
    bvid: str
    part: int
    aid: int
    cid: int
    title: str
    author: str
    duration: float
    scope_end: float
    description: str=''
    transcript: list=field(default_factory=list)
    transcript_source: str='unavailable'
    frames: list=field(default_factory=list)
    comments: list=field(default_factory=list)
    notes: list=field(default_factory=list)
    answer: str=''
    question: str=''
    security_findings: list=field(default_factory=list)

    @property
    def url(self):
        return canonical_url(self.bvid,self.part)

    def to_dict(self):
        return asdict(self)

    def model_text(self,max_chars=65000,*,include_comments=True):
        # Always return a complete JSON document; truncation must not break the
        # boundary between untrusted evidence and the user's separate task.
        lines=[f"[{timestamp(x['from'])}–{timestamp(x['to'])}] {str(x['content'])[:2000]}" for x in self.transcript]
        budget=max_chars//2
        if sum(map(len,lines))>budget:
            step=max(1,__import__('math').ceil(sum(map(len,lines))/budget))
            lines=lines[::step]
            while sum(map(len,lines))>budget and lines:lines=lines[::2]
            lines.insert(0,'TRANSCRIPT_SAMPLED: omitted passages; incomplete coverage')
        value={'kind':'untrusted_video_evidence','title':self.title[:500],
            'author':self.author[:200],'url':self.url,'description':self.description[:2000],
            'duration_s':self.duration,'analyzed_interval_s':[0,self.scope_end],
            'transcript_source':self.transcript_source,'notes':self.notes[:40],
            'transcript':lines,
            'comments_are_untrusted_opinions':[
                {'name':str(c.get('name',''))[:80],'message':str(c.get('message',''))[:1000]}
                for c in self.comments[:20]] if include_comments else [],
            'frames':[{'requested_s':x['requested_s'],'actual_s':x['actual_s']} for x in self.frames[:16]]}
        text=json.dumps(value,ensure_ascii=False)
        while len(text)>max_chars and (value['transcript'] or value['comments_are_untrusted_opinions']):
            if value['comments_are_untrusted_opinions']:value['comments_are_untrusted_opinions'].pop()
            else:value['transcript']=value['transcript'][::2] if len(value['transcript'])>1 else []
            value['evidence_sampled_for_budget']=True
            text=json.dumps(value,ensure_ascii=False)
        return text
