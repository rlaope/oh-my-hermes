"""Scratch: which restricted-token variant lets a child start. Not for merge."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "coding"))
import fanout_restricted_token as rt  # noqa: E402

advapi32, kernel32 = rt._windows()
advapi32.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]


def logon_sid(token):
    needed = wintypes.DWORD()
    advapi32.GetTokenInformation(token, 28, None, 0, ctypes.byref(needed))
    buffer = ctypes.create_string_buffer(needed.value)
    if not advapi32.GetTokenInformation(token, 28, buffer, needed, ctypes.byref(needed)):
        return None
    # TOKEN_GROUPS: DWORD GroupCount; (padding) SID_AND_ATTRIBUTES Groups[]
    count = ctypes.c_uint32.from_buffer(buffer).value
    offset = ctypes.sizeof(ctypes.c_void_p)
    entry = rt._SidAndAttributes.from_buffer(buffer, offset)
    text = wintypes.LPWSTR()
    advapi32.ConvertSidToStringSidW(entry.Sid, ctypes.byref(text))
    return count, text.value


def attempt(label, sids, flags, set_dacl, argv, stdio=True):
    token = wintypes.HANDLE()
    advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), 0x1 | 0x2 | 0x8 | 0x80, ctypes.byref(token))
    pointers = [rt._sid_pointer(advapi32, sid) for sid in sids]
    restricting = (rt._SidAndAttributes * len(pointers))(*(rt._SidAndAttributes(p.value, 0) for p in pointers))
    restricted = wintypes.HANDLE()
    if not advapi32.CreateRestrictedToken(token, 0x1 | 0x8, 0, None, 0, None, len(pointers), restricting, ctypes.byref(restricted)):
        print(label, "CreateRestrictedToken failed", ctypes.get_last_error())
        return
    if set_dacl:
        principals = ("SY", rt._token_user_sid(advapi32, kernel32, token), *sids)
        sddl = "D:" + "".join(f"(A;;GA;;;{p})" for p in principals)
        descriptor = ctypes.c_void_p()
        advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None)
        present, defaulted, dacl = wintypes.BOOL(), wintypes.BOOL(), ctypes.c_void_p()
        advapi32.GetSecurityDescriptorDacl(descriptor, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted))
        default = ctypes.c_void_p(dacl.value)
        if not advapi32.SetTokenInformation(restricted, 6, ctypes.byref(default), ctypes.sizeof(default)):
            print(label, "SetTokenInformation failed", ctypes.get_last_error())
    startup = rt._StartupInfo()
    startup.cb = ctypes.sizeof(startup)
    if stdio:
        startup.dwFlags = 0x100
        for field, standard in (("hStdInput", -10), ("hStdOutput", -11), ("hStdError", -12)):
            handle = kernel32.GetStdHandle(standard & 0xFFFFFFFF)
            if handle:
                kernel32.SetHandleInformation(handle, 1, 1)
            setattr(startup, field, handle)
    line = ctypes.create_unicode_buffer(subprocess.list2cmdline(argv))
    process = rt._ProcessInformation()
    if not advapi32.CreateProcessAsUserW(restricted, None, line, None, None, True, flags, None, None, ctypes.byref(startup), ctypes.byref(process)):
        print(label, "CreateProcessAsUserW failed", ctypes.get_last_error())
        return
    kernel32.WaitForSingleObject(process.hProcess, 60000)
    code = wintypes.DWORD()
    kernel32.GetExitCodeProcess(process.hProcess, ctypes.byref(code))
    print(f"{label}: exit=0x{code.value:08X}", flush=True)


root = Path(tempfile.mkdtemp()).resolve()
granted = root / "granted"
granted.mkdir()
sid = rt.write_root_sid(granted)
print("grant", rt.grant_write_root(granted, sid, directory=True))
token = wintypes.HANDLE()
advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), 0x8, ctypes.byref(token))
logon = logon_sid(token)
print("logon sid", logon)
logon_text = logon[1] if logon else None
write = [sys.executable, "-I", "-B", "-c", "import sys; open(sys.argv[1], 'w').write('x'); print('wrote')", str(granted / "f")]
outside = [sys.executable, "-I", "-B", "-c", "import sys; open(sys.argv[1], 'w').write('x')", str(root / "outside")]
cmd = ["cmd.exe", "/c", "echo cmd-ok"]
variants = [
    ("base", [sid], 0, True),
    ("no_dacl", [sid], 0, False),
    ("detached", [sid], 0x8, True),
    ("no_window", [sid], 0x08000000, True),
    ("new_console", [sid], 0x10, True),
    ("logon", [sid] + ([logon_text] if logon_text else []), 0, True),
    ("everyone", [sid, "S-1-1-0"], 0, True),
    ("restricted_sid", [sid, "S-1-5-12"], 0, True),
    ("logon_detached", [sid] + ([logon_text] if logon_text else []), 0x8, True),
]
for label, sids, flags, dacl in variants:
    for name, argv in (("cmd", cmd), ("write", write), ("outside", outside)):
        try:
            attempt(f"{label}/{name}", sids, flags, dacl, argv)
        except OSError as exc:
            print(label, name, "error", exc)
    (granted / "f").unlink(missing_ok=True)
    if (root / "outside").exists():
        print(label, "OUTSIDE WRITTEN")
        (root / "outside").unlink()
