"""Set process-local paths BEFORE third-party imports. No HOME/registry edits."""
from __future__ import annotations
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parent.parent
RUNTIME = ROOT / 'runtime'
_GUARD = False
_SECRETS: set[str] = set()
_LOCK = threading.RLock()


def inside(path, root=ROOT) -> Path:
    p = Path(path).resolve()
    if not p.is_relative_to(root.resolve()):
        raise PermissionError('BILISCOPE_OUTSIDE_ROOT: ' + str(p))
    return p


def atomic_json(path, value):
    p = inside(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    temporary = p.with_suffix(p.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(p)


def remember_secret(secret: str):
    # Very short "secrets" cannot be credentials but would rewrite ordinary
    # words in logs and request traces, so they are not tracked.
    if secret and len(secret) >= 6:
        with _LOCK:
            _SECRETS.add(secret)


def redact(value) -> str:
    result = str(value)
    with _LOCK:
        for secret in _SECRETS:
            result = result.replace(secret, '[REDACTED]')
    result = re.sub(r'(?i)(Bearer\s+)\S+', r'\1[REDACTED]', result)
    result = re.sub(r'(?i)((?:SESSDATA|bili_jct|api[_-]?key|csrf|access_token)["\s:=]+)[^\s,;&"\']+', r'\1[REDACTED]', result)
    result = re.sub(r'https?://[^\s\"\']+\?[^\s\"\']+', '[URL_QUERY_REDACTED]', result)
    return result


class RedactingFormatter(logging.Formatter):
    def format(self, record):
        return redact(super().format(record))


def write_guard(event, args):
    # CPython audit events cover Python file writes, not native/OS disk activity.
    if event == 'open':
        path, mode, flags = args
        if isinstance(path, int):
            return
        writing = bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
        if writing:
            inside(os.fsdecode(path))
    elif event in {'os.mkdir', 'os.remove', 'os.rmdir', 'os.truncate', 'os.chmod', 'os.utime'}:
        if not isinstance(args[0], int):
            inside(os.fsdecode(args[0]))
    elif event in {'os.rename', 'os.link'}:
        inside(os.fsdecode(args[0]))
        inside(os.fsdecode(args[1]))
    elif event == 'os.symlink':
        # No app feature needs symlinks. Prevent paths becoming an escape route.
        raise PermissionError('BILISCOPE_SYMLINK_DISABLED')
    elif event == 'os.chdir':
        inside(os.fsdecode(args[0]))


def configure(*, guard=True):
    global _GUARD
    # Reject pre-existing junctions/symlinks that redirect runtime data.
    inside(RUNTIME)
    locations = {
        'tmp': RUNTIME / 'tmp', 'logs': RUNTIME / 'logs',
        'cache': RUNTIME / 'cache', 'config': RUNTIME / 'config',
        'profile': RUNTIME / 'browser-profile', 'browsers': RUNTIME / 'browsers',
        'downloads': RUNTIME / 'downloads', 'models': RUNTIME / 'models',
        'exports': RUNTIME / 'exports', 'evidence': RUNTIME / 'evidence',
        'provenance': RUNTIME / 'provenance', 'state': RUNTIME / 'state',
    }
    for path in locations.values():
        inside(path).mkdir(parents=True, exist_ok=True)
    env_paths = {
        'TMP': locations['tmp'], 'TEMP': locations['tmp'], 'TMPDIR': locations['tmp'],
        'XDG_CACHE_HOME': locations['cache'], 'XDG_CONFIG_HOME': locations['config'],
        'XDG_DATA_HOME': RUNTIME / 'data', 'XDG_STATE_HOME': locations['state'],
        'XDG_RUNTIME_DIR': RUNTIME / 'run',
        'APPDATA': RUNTIME / 'appdata', 'LOCALAPPDATA': RUNTIME / 'localappdata',
        'PIP_CACHE_DIR': locations['cache'] / 'pip',
        'PLAYWRIGHT_BROWSERS_PATH': locations['browsers'],
        'HF_HOME': locations['cache'] / 'huggingface',
        'HF_HUB_CACHE': locations['cache'] / 'huggingface' / 'hub',
        'TORCH_HOME': locations['cache'] / 'torch',
        'MPLCONFIGDIR': locations['config'] / 'matplotlib',
        'NUMBA_CACHE_DIR': locations['cache'] / 'numba',
        'CUDA_CACHE_PATH': locations['cache'] / 'cuda',
        'NODE_COMPILE_CACHE': locations['cache'] / 'node',
        'NODE_REPL_HISTORY': locations['state'] / 'node-history',
        'GLOG_log_dir': locations['logs'],
    }
    for key, path in env_paths.items():
        if key != 'NODE_REPL_HISTORY':
            inside(path).mkdir(parents=True, exist_ok=True)
        os.environ[key] = str(path)
    # Ignore inherited overrides which could launch a different driver/browser.
    for key in ('PLAYWRIGHT_NODEJS_PATH', 'PLAYWRIGHT_DOWNLOAD_HOST',
                'PLAYWRIGHT_CHROMIUM_DOWNLOAD_HOST', 'NODE_OPTIONS',
                'NODE_EXTRA_CA_CERTS', 'SSLKEYLOGFILE', 'CHROME_LOG_FILE',
                'PYTHONPATH', 'PYTHONHOME', 'PIP_TARGET', 'PIP_PREFIX', 'PIP_USER',
                'PIP_LOG', 'PIP_EXTRA_INDEX_URL', 'PIP_INDEX_URL'):
        os.environ.pop(key, None)
    for key in ('DEBUG', 'PWDEBUG', 'NODE_V8_COVERAGE'):
        os.environ.pop(key, None)
    if os.name != 'nt':
        (RUNTIME / 'run').chmod(0o700)
    os.environ.update({
        'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1',
        'PIP_CONFIG_FILE': os.devnull, 'PIP_DISABLE_PIP_VERSION_CHECK': '1',
        'PIP_NO_INPUT': '1', 'PLAYWRIGHT_SKIP_BROWSER_GC': '1',
        'HF_HUB_DISABLE_TELEMETRY': '1', 'HF_HUB_DISABLE_XET': '1',
        'DO_NOT_TRACK': '1', 'GRADIO_ANALYTICS_ENABLED': 'False',
        'GLOG_logtostderr': '1',
    })
    sys.dont_write_bytecode = True
    tempfile.tempdir = str(locations['tmp'])
    os.chdir(ROOT)
    if guard and not _GUARD:
        sys.addaudithook(write_guard)
        _GUARD = True
    return locations


def setup_logging():
    logger = logging.getLogger('biliscope')
    if logger.handlers:
        return logger
    handler = RotatingFileHandler(inside(RUNTIME / 'logs' / 'app.log'),
                                  maxBytes=2_000_000, backupCount=3, encoding='utf-8')
    handler.setFormatter(RedactingFormatter('%(asctime)s %(levelname)s %(message)s'))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def path_report():
    keys = ('TMP','TEMP','TMPDIR','APPDATA','LOCALAPPDATA','XDG_CACHE_HOME',
            'XDG_CONFIG_HOME','XDG_DATA_HOME','XDG_STATE_HOME','PIP_CACHE_DIR',
            'PLAYWRIGHT_BROWSERS_PATH','HF_HOME','HF_HUB_CACHE','TORCH_HOME',
            'NUMBA_CACHE_DIR','CUDA_CACHE_PATH','MPLCONFIGDIR', 'XDG_RUNTIME_DIR',
            'NODE_COMPILE_CACHE','NODE_REPL_HISTORY','GLOG_log_dir')
    return {'project': str(ROOT), 'cwd': os.getcwd(), 'python_write_guard': _GUARD,
            'paths': {k: {'path': os.environ.get(k, ''),
                          'inside_project': Path(os.environ.get(k, '/')).resolve().is_relative_to(ROOT)}
                      for k in keys},
            'python_bytecode_disabled': sys.dont_write_bytecode,
            'boundary': 'Application data only; Windows/antivirus/driver-managed OS files are outside this policy.'}
