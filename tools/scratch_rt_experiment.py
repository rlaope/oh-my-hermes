"""Scratch v5: the DACL a restricted process's named pipe gets, and which client opens fail. Not for merge."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "coding"))
import fanout_restricted_token as rt  # noqa: E402

CHILD = r'''
import ctypes, os, sys
from ctypes import wintypes
k = ctypes.WinDLL("kernel32", use_last_error=True)
a = ctypes.WinDLL("advapi32", use_last_error=True)
k.CreateNamedPipeW.restype = wintypes.HANDLE
k.CreateNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
k.CreateFileW.restype = wintypes.HANDLE
k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
a.GetSecurityInfo.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
a.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(wintypes.LPWSTR), ctypes.c_void_p]
INVALID = ctypes.c_void_p(-1).value
for server_extra, label in ((0, "plain"), (0x00040000, "write_dac")):
    name = r"\\.\pipe\omh-probe-%d-%s" % (os.getpid(), label)
    server = k.CreateNamedPipeW(name, 0x3 | 0x00080000 | 0x40000000 | server_extra, 0, 1, 65536, 65536, 0, None)
    print(label, "server", "ok" if server and server != INVALID else ctypes.get_last_error())
    if not server or server == INVALID:
        continue
    sd = ctypes.c_void_p()
    err = a.GetSecurityInfo(server, 6, 0x4 | 0x1, None, None, None, None, ctypes.byref(sd))
    text = wintypes.LPWSTR()
    if not err and a.ConvertSecurityDescriptorToStringSecurityDescriptorW(sd, 1, 0x4 | 0x1, ctypes.byref(text), None):
        print(label, "sddl", text.value)
    else:
        print(label, "GetSecurityInfo", err, ctypes.get_last_error())
    for access, name_access in ((0x80000000 | 0x100, "read+write_attr"), (0x40000000 | 0x80, "write+read_attr"), (0x40000000, "write"), (0x80000000, "read")):
        client = k.CreateFileW(name, access, 0, None, 3, 0x40000000, None)
        print(label, "client", name_access, "ok" if client and client != INVALID else ctypes.get_last_error())
        if client and client != INVALID:
            k.CloseHandle(client)
    k.CloseHandle(server)
'''

root = Path(tempfile.mkdtemp()).resolve()
granted = root / "granted"
granted.mkdir()
sid = rt.write_root_sid(granted)
rt.grant_write_root(granted, sid, directory=True)
for sids in ([sid, "S-1-1-0", "S-1-5-12"],):
    for skip in ("0", "1"):
        command = rt.launcher_command(sys.executable, sids, [sys.executable, "-I", "-B", "-c", CHILD])
        completed = subprocess.run(command, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL,
                                   env={**os.environ, "OMH_RT_SKIP_DACL": skip})
        print(f"=== skip_dacl={skip} exit={completed.returncode & 0xFFFFFFFF:08X}")
        print(completed.stdout.strip())
        print(completed.stderr.strip()[-400:])
unconfined = subprocess.run([sys.executable, "-I", "-B", "-c", CHILD], capture_output=True, text=True)
print("=== unconfined")
print(unconfined.stdout.strip())
