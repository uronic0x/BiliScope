"""Installed dependency and binary inventory; no network access."""
from __future__ import annotations
import hashlib
import importlib.metadata as md
import json
from pathlib import Path
import sys
from .runtime import ROOT, RUNTIME, inside, atomic_json

SOURCES = {
    'patchright': ('Apache-2.0', 'https://github.com/Kaliiiiiiiiii-Vinyzu/patchright-python', 'https://github.com/Kaliiiiiiiiii-Vinyzu/patchright'),
    'greenlet': ('MIT AND Python-2.0', 'https://github.com/python-greenlet/greenlet'),
    'pyee': ('MIT', 'https://github.com/jfhbrook/pyee'),
    'typing-extensions': ('PSF-2.0', 'https://github.com/python/typing_extensions'),
    'numpy': ('BSD-3-Clause; see bundled notices', 'https://github.com/numpy/numpy', 'https://github.com/OpenMathLib/OpenBLAS', 'https://github.com/microsoft/STL'),
    'av': ('BSD-3-Clause; bundled FFmpeg/codecs have LGPL/GPL notices', 'https://github.com/PyAV-Org/PyAV', 'https://github.com/PyAV-Org/pyav-ffmpeg', 'https://github.com/FFmpeg/FFmpeg'),
    'sherpa-onnx': ('Apache-2.0', 'https://github.com/k2-fsa/sherpa-onnx'),
    'PySide6': ('LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only', 'https://www.qt.io/qt-for-python', 'https://code.qt.io/cgit/pyside/pyside-setup.git'),
    'PySide6-Addons': ('LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only', 'https://www.qt.io/qt-for-python', 'https://code.qt.io/cgit/pyside/pyside-setup.git'),
    'PySide6-Essentials': ('LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only', 'https://www.qt.io/qt-for-python', 'https://code.qt.io/cgit/pyside/pyside-setup.git'),
    'shiboken6': ('LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only', 'https://www.qt.io/qt-for-python', 'https://code.qt.io/cgit/pyside/pyside-setup.git'),
}


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):
            h.update(block)
    return h.hexdigest()


def inventory():
    result = []
    for name, sources in SOURCES.items():
        try:
            dist = md.distribution(name)
            binaries = []
            for item in dist.files or []:
                if Path(item).suffix.lower() in ('.exe','.dll','.pyd','.so','.dylib','.node'):
                    path = Path(dist.locate_file(item)).resolve()
                    if not path.is_relative_to(ROOT):
                        raise PermissionError('DEPENDENCY_OUTSIDE_PROJECT: '+name)
                    binaries.append({'path':str(path.relative_to(ROOT)), 'sha256':sha256(path)})
            result.append({'name':name,'version':dist.version,'license':sources[0],
                           'source':list(sources[1:]), 'binaries':binaries})
        except md.PackageNotFoundError:
            result.append({'name':name,'installed':False,'source':list(sources[1:])})
    return result


def save_inventory():
    value = {'python':sys.version, 'python_source':'https://github.com/python/cpython',
             'components':inventory(), 'browser':[]}
    root = inside(RUNTIME/'browsers')
    for p in sorted(root.rglob('*')):
        if p.is_file() and (p.suffix.lower() in ('.exe','.dll','.so','.pak') or p.name in ('chrome','headless_shell','INSTALLATION_COMPLETE')):
            value['browser'].append({'path':str(p.relative_to(ROOT)), 'sha256':sha256(p)})
    # The browser manifest pins Chromium version + revision; the embedded
    # driver pins the patched JS implementation. Retain their exact bytes.
    try:
        import patchright
        driver = Path(patchright.__file__).parent/'driver'/'package'
        for name in ('browsers.json','package.json','ThirdPartyNotices.txt'):
            p = driver/name
            if p.exists():
                inside(RUNTIME/'provenance'/('driver-'+name)).write_bytes(p.read_bytes())
        node = driver.parent/('node.exe' if sys.platform=='win32' else 'node')
        if node.exists():
            import subprocess
            out = subprocess.run([str(node),'--version'],capture_output=True,text=True,cwd=ROOT,check=True)
            value['node'] = {'version':out.stdout.strip(),'sha256':sha256(node),
                             'source':'https://github.com/nodejs/node'}
    except ImportError:
        pass
    atomic_json(RUNTIME/'provenance'/'installed-components.json',value)
    return value
