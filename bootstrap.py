"""One-time setup; all subprocess environments inherit project-local paths."""
import sys
from pathlib import Path
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
from biliscope.runtime import ROOT, RUNTIME, configure, inside, atomic_json
configure(guard=False)
import argparse
import json
import os
import subprocess
import venv
from datetime import datetime,timezone


def run(argv, log):
    # No shell command interpretation; capture child logs inside this project.
    log.write(('\n$ '+' '.join(argv)+'\n').encode('utf-8'))
    log.flush()
    subprocess.run(argv,cwd=ROOT,env=os.environ.copy(),stdout=log,stderr=subprocess.STDOUT,check=True)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--no-browser',action='store_true',help='developer setup only')
    args=p.parse_args()
    if not (3,12) <= sys.version_info[:2] <= (3,14):
        raise RuntimeError('Use 64-bit CPython 3.12, 3.13 or 3.14 / 请使用 64 位 CPython 3.12–3.14')
    if sys.maxsize <= 2**32:
        raise RuntimeError('64-bit Python is required / 需要 64 位 Python')
    prefix=inside(ROOT/'.venv')
    python=prefix/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    with inside(RUNTIME/'logs'/'setup.log').open('ab') as log:
        print('Preparing isolated environment / 正在准备隔离环境…',flush=True)
        if not python.exists():
            venv.EnvBuilder(with_pip=True,symlinks=False).create(prefix)
        else:
            # Never install into a redirected/symlinked global interpreter.
            inside(python)
        cmd=[str(python),'-I','-B']
        run(cmd+['-m','pip','install','--disable-pip-version-check','--no-input',
                 '--only-binary=:all:','--no-compile','--require-hashes',
                 '--index-url','https://pypi.org/simple','--report',
                 str(RUNTIME/'provenance'/('pip-install-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'.json')),'-r',str(ROOT/'requirements.lock')],log)
        if not args.no_browser:
            print('Installing Chromium locally / 正在项目内安装 Chromium…',flush=True)
            from biliscope.browser_install import install
            install()
        run(cmd+[str(ROOT/'tools'/'inventory.py')],log)
    print('Ready. Run launch.bat / 安装完成，运行 launch.bat。',flush=True)


if __name__=='__main__':
    try:
        main()
    except Exception as e:
        print('Setup failed / 安装失败:',type(e).__name__)
        print('Details / 详情:',RUNTIME/'logs'/'setup.log')
        raise SystemExit(1)
