"""Official, unbranded Chromium snapshots; fixed source revision and SHA-256."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path,PurePosixPath
import shutil
import stat
import sys
import urllib.request
import zipfile
from .domain import AppError
from .runtime import ROOT,RUNTIME,inside,atomic_json


def descriptor():
    platform='Win_x64' if sys.platform=='win32' else 'Linux_x64' if sys.platform.startswith('linux') else None
    if not platform: raise AppError('BROWSER_PLATFORM')
    value=json.loads((ROOT/'docs/browser-lock.json').read_text(encoding='utf-8'))[platform]
    return value


def executable():
    d=descriptor()
    p=inside(RUNTIME/'browsers'/('chromium-'+d['snapshot'])/d['executable'])
    if not p.is_file(): raise AppError('SETUP_REQUIRED')
    return p


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def safe_extract(archive,destination):
    destination=inside(destination)
    with zipfile.ZipFile(archive) as z:
        for item in z.infolist():
            name=PurePosixPath(item.filename.replace('\\','/'))
            if name.is_absolute() or '..' in name.parts or any(':' in p for p in name.parts):
                raise AppError('BROWSER_ARCHIVE')
            mode=item.external_attr>>16
            if stat.S_ISLNK(mode):raise AppError('BROWSER_ARCHIVE')
            target=inside(destination.joinpath(*name.parts))
            if not target.is_relative_to(destination):raise AppError('BROWSER_ARCHIVE')
            if item.is_dir():target.mkdir(parents=True,exist_ok=True)
            else:
                target.parent.mkdir(parents=True,exist_ok=True)
                with z.open(item) as source,target.open('wb') as out:shutil.copyfileobj(source,out)
                if os.name!='nt' and mode:target.chmod(mode&0o777)


def install():
    d=descriptor();folder=inside(RUNTIME/'browsers'/('chromium-'+d['snapshot']))
    state=folder/'installed.json';exe=folder/d['executable']
    if state.exists() and exe.is_file():
        current=json.loads(state.read_text())
        if current.get('archive_sha256')==d['sha256'] and current.get('executable_sha256')==digest(exe):return exe
    archive=inside(RUNTIME/'cache'/d['archive'])
    if not archive.exists() or digest(archive)!=d['sha256']:
        temp=archive.with_suffix('.partial')
        h=hashlib.sha256();size=0
        opener=urllib.request.build_opener()
        try:
            with opener.open(d['url'],timeout=60) as response,temp.open('wb') as out:
                if not response.url.startswith('https://'):raise AppError('BROWSER_HASH')
                while block:=response.read(1024*1024):
                    size+=len(block)
                    if size>d['size']:raise AppError('BROWSER_HASH')
                    out.write(block);h.update(block)
            if size!=d['size'] or h.hexdigest()!=d['sha256']:raise AppError('BROWSER_HASH')
            temp.replace(archive)
        finally:temp.unlink(missing_ok=True)
    folder.mkdir(parents=True,exist_ok=True)
    safe_extract(archive,folder)
    if not exe.is_file():raise AppError('BROWSER_ARCHIVE')
    if os.name!='nt':exe.chmod(0o755)
    record={'source':d['source'],'source_revisions':d['revisions'],'download_url':d['url'],
            'archive_sha256':d['sha256'],'executable_sha256':digest(exe),'snapshot':d['snapshot']}
    atomic_json(state,record)
    atomic_json(RUNTIME/'provenance'/'chromium.json',record)
    return exe
