"""Optional Windows user-scoped DPAPI. Never save the API key as plaintext."""
import ctypes
from ctypes import wintypes
import os
from .runtime import RUNTIME, inside

class Blob(ctypes.Structure):
    _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_ubyte))]


def _crypt(data: bytes, decrypt=False):
    if os.name != 'nt':
        raise RuntimeError('DPAPI_WINDOWS_ONLY')
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    result = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    fn = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                   ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        kernel.LocalFree(result.pbData)


def save_key(key: str, remember: bool):
    p = inside(RUNTIME/'config'/'api-key.dpapi')
    if not remember:
        p.unlink(missing_ok=True)
    else:
        encrypted = _crypt(key.encode('utf-8'))
        temp = p.with_suffix('.tmp')
        temp.write_bytes(encrypted)
        temp.replace(p)


def load_key():
    p = inside(RUNTIME/'config'/'api-key.dpapi')
    if os.name == 'nt' and p.exists():
        return _crypt(p.read_bytes(), decrypt=True).decode('utf-8')
    return os.environ.get('BILISCOPE_API_KEY','')
