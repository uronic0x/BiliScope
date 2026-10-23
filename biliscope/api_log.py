"""Local, bounded request traces so prompt assembly is auditable.

Prompts, evidence and model replies stay inside the project; nothing here is
sent anywhere. Image payloads are replaced by size markers so one trace does
not balloon to megabytes of base64.
"""
from __future__ import annotations
from datetime import datetime
import json
from pathlib import Path
import uuid
from .runtime import RUNTIME, inside, redact

MAX_TEXT=80000
MAX_ENTRIES=200
MAX_BYTES=6*1024*1024
KEEP_TRACES=40


def _shrink(value,depth=0):
    if depth>12:return '[DEPTH_LIMIT]'
    if isinstance(value,str):
        text=value if len(value)<=MAX_TEXT else value[:MAX_TEXT]+'…[TRUNCATED '+str(len(value))+' chars]'
        # Redact while the value is still a plain string: scrubbing the
        # serialized JSON could break quoting and make the trace unreadable.
        return redact(text)
    if isinstance(value,list):return [_shrink(x,depth+1) for x in value[:200]]
    if isinstance(value,dict):
        result={}
        for key,item in value.items():
            if key=='image_url' and isinstance(item,dict):
                url=str(item.get('url',''))
                result[key]={'omitted':'image','bytes':len(url)}
            else:
                result[str(key)]=_shrink(item,depth+1)
        return result
    return value


def summarize(data):
    """A readable copy of a request body: images omitted, text preserved.

    Redaction happens on the serialized text at write time, not here, so the
    stored value stays structured and readable.
    """
    return _shrink(data)


class RequestLog:
    """Writes one <NNN>-<purpose>.json per API call inside the run folder."""

    def __init__(self,folder):
        self.folder=inside(Path(folder)/'requests')
        self.count=0
        self.total=0

    def request(self,purpose,endpoint_url,data):
        if self.count>=MAX_ENTRIES or self.total>=MAX_BYTES:return None
        self.count+=1
        entry={'index':self.count,'purpose':str(purpose)[:40],
               'endpoint':redact(str(endpoint_url)),'request':summarize(data),
               'response':None,'error':None}
        self._write(entry)
        return entry

    def response(self,entry,result,finish_reason=None):
        if entry is None:return
        entry['response']={'finish_reason':finish_reason,
                           'content':_shrink(result.get('content')),
                           'tool_calls':_shrink(result.get('tool_calls'))}
        self._write(entry)

    def error(self,entry,code):
        if entry is None:return
        entry['error']=str(code)
        self._write(entry)

    def _write(self,entry):
        payload=json.dumps(entry,ensure_ascii=False,indent=1)
        # Values are already redacted by _shrink; scrubbing the serialized JSON
        # here would corrupt quoting, so only the endpoint is re-checked.
        if self.total+len(payload)>MAX_BYTES:return
        self.total+=len(payload)
        name=str(entry['index']).zfill(3)+'-'+''.join(
            c if c.isalnum() or c in '-_' else '_' for c in entry['purpose'])+'.json'
        self.folder.mkdir(parents=True,exist_ok=True)
        target=inside(self.folder/name)
        temporary=target.with_suffix('.json.tmp')
        temporary.write_text(payload,encoding='utf-8')
        temporary.replace(target)

    def path(self,index):
        matches=sorted(self.folder.glob(str(index).zfill(3)+'-*.json'))
        return matches[0] if matches else None

    def entries(self):
        result=[]
        for path in sorted(self.folder.glob('*.json')):
            try:
                result.append((path,json.loads(path.read_text(encoding='utf-8'))))
            except (OSError,ValueError):continue
        return result

    def preview(self,limit=3):
        """Recent requests as one readable block for the GUI."""
        blocks=[]
        for path,entry in self.entries()[-limit:]:
            request=entry.get('request') or {}
            messages=request.get('messages') or []
            lines=['# '+str(entry.get('purpose'))+'  ('+path.name+')']
            lines.append('model: '+str(request.get('model'))+'  endpoint: '+str(entry.get('endpoint')))
            for message in messages:
                role=str(message.get('role'))
                content=message.get('content')
                if isinstance(content,list):
                    content='\n'.join(str(x.get('text','[image]')) if isinstance(x,dict) else str(x) for x in content)
                lines.append('\n=== '+role+' ===\n'+str(content))
            if entry.get('error'):lines.append('\n[error] '+str(entry['error']))
            elif entry.get('response'):
                lines.append('\n=== assistant ===\n'+str(entry['response'].get('content')))
            blocks.append('\n'.join(lines))
        return '\n\n'.join(blocks) if blocks else ''


def prune(keep=KEEP_TRACES):
    """Drop the oldest run-request folders so traces cannot grow unbounded."""
    root=inside(RUNTIME/'auto')
    folders=[]
    for path in root.iterdir():
        if path.is_dir() and (path/'requests').is_dir():
            folders.append(path)
    for path in sorted(folders)[:-keep]:
        for item in sorted((path/'requests').glob('*.json'),reverse=True):
            try: item.unlink()
            except OSError: pass
        try: (path/'requests').rmdir()
        except OSError: pass


def new_session_folder(prefix='chat'):
    """Return a path for this run; the folder appears with the first request."""
    stamp=datetime.now().strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:8]
    return inside(RUNTIME/'auto'/(prefix+'-'+stamp))
