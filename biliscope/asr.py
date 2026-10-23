"""CPU-only, local Whisper ONNX transcription. No CUDA or vendor SDK."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import urllib.request
from .domain import AppError
from .runtime import ROOT, RUNTIME, inside, atomic_json


def ensure_model(progress=lambda *_:None,stop=None):
    lock=json.loads((ROOT/'docs'/'model-lock.json').read_text(encoding='utf-8'))
    folder=inside(RUNTIME/'models'/'whisper-base')
    folder.mkdir(parents=True,exist_ok=True)
    records=[]
    from .llm import NoRedirect
    # HF file storage legitimately redirects across its CDN domains. Only the
    # model downloader follows redirects; it sends no API key or Bilibili cookie.
    opener=urllib.request.build_opener()
    for item in lock['files']:
        target=inside(folder/item['name'])
        expected=item['sha256']
        valid=target.exists() and _hash(target)==expected
        if not valid:
            progress('model_download',item['name'])
            url=lock['base_url']+'/'+item['name']
            temp=target.with_suffix('.partial')
            digest=hashlib.sha256();count=0
            try:
                with opener.open(url,timeout=60) as response,temp.open('wb') as out:
                    # Do not trust redirected HTTP or a surprising content size.
                    if not response.url.startswith('https://'): raise AppError('MODEL_DOWNLOAD')
                    while block:=response.read(1024*512):
                        if stop and stop.is_set(): raise AppError('CANCELLED')
                        count+=len(block)
                        if count>item['size']: raise AppError('MODEL_HASH')
                        digest.update(block);out.write(block)
                if digest.hexdigest()!=expected or count!=item['size']:
                    raise AppError('MODEL_HASH')
                temp.replace(target)
            except AppError: raise
            except Exception: raise AppError('MODEL_DOWNLOAD') from None
            finally: temp.unlink(missing_ok=True)
        records.append({'name':item['name'],'sha256':expected,'source':lock['base_url']+'/'+item['name']})
    atomic_json(RUNTIME/'provenance'/'asr-model.json',{'revision':lock['revision'],'files':records,'origin':'https://github.com/openai/whisper','license':'MIT'})
    return folder


def _hash(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
    return h.hexdigest()


def transcribe(audio:Path,end_s,progress=lambda *_:None,stop=None):
    try:
        import av
        import numpy as np
        import sherpa_onnx
    except ImportError:
        raise AppError('ASR_SETUP') from None
    model=ensure_model(progress,stop)
    recognizer=sherpa_onnx.OfflineRecognizer.from_whisper(
        encoder=str(model/'base-encoder.int8.onnx'),
        decoder=str(model/'base-decoder.int8.onnx'),
        tokens=str(model/'base-tokens.txt'),language='',task='transcribe',
        num_threads=2,provider='cpu',debug=False)
    result=[];pending=np.zeros(0,dtype=np.float32);offset=0
    max_samples=int(end_s*16000);received=0;chunk_samples=28*16000

    def decode(samples,start):
        if stop and stop.is_set(): raise AppError('CANCELLED')
        if not len(samples) or float(np.sqrt(np.mean(samples*samples)))<0.003:
            return
        stream=recognizer.create_stream()
        stream.accept_waveform(16000,samples)
        recognizer.decode_stream(stream)
        text=stream.result.text.strip()
        if text:
            result.append({'from':round(start/16000,2),
                'to':round((start+len(samples))/16000,2),'content':text})
        progress('asr_chunk',str(round((start+len(samples))/16000)))

    with av.open(str(inside(audio))) as container:
        resampler=av.audio.resampler.AudioResampler(format='flt',layout='mono',rate=16000)
        for frame in container.decode(audio=0):
            if stop and stop.is_set(): raise AppError('CANCELLED')
            for converted in resampler.resample(frame):
                samples=converted.to_ndarray().reshape(-1).astype(np.float32,copy=False)
                samples=samples[:max(0,max_samples-received)]
                received+=len(samples)
                pending=np.concatenate((pending,samples))
                while len(pending)>=chunk_samples:
                    decode(pending[:chunk_samples],offset)
                    pending=pending[chunk_samples:];offset+=chunk_samples
            if received>=max_samples: break
        if received<max_samples:
            for converted in resampler.resample(None):
                samples=converted.to_ndarray().reshape(-1).astype(np.float32,copy=False)
                samples=samples[:max(0,max_samples-received)]
                received+=len(samples);pending=np.concatenate((pending,samples))
        decode(pending,offset)
    return result
