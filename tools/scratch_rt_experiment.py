"""Scratch v6: Low integrity instead of a write-restricted token. Not for merge."""
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
advapi32.DuplicateTokenEx.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.POINTER(wintypes.HANDLE)]
advapi32.DuplicateTokenEx.restype = wintypes.BOOL


class Label(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", ctypes.c_uint32)]


def low_run(argv, env=None):
    token = wintypes.HANDLE()
    assert advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), 0x1 | 0x2 | 0x8 | 0x80, ctypes.byref(token))
    low = wintypes.HANDLE()
    assert advapi32.DuplicateTokenEx(token, 0x02000000, None, 2, 1, ctypes.byref(low)), ctypes.get_last_error()
    sid = rt._sid_pointer(advapi32, "S-1-16-4096")
    label = Label(sid.value, 0x20)  # SE_GROUP_INTEGRITY
    assert advapi32.SetTokenInformation(low, 25, ctypes.byref(label), ctypes.sizeof(label) + 12), ctypes.get_last_error()
    startup = rt._StartupInfo()
    startup.cb = ctypes.sizeof(startup)
    startup.dwFlags = 0x100
    for field, standard in (("hStdInput", -10), ("hStdOutput", -11), ("hStdError", -12)):
        handle = kernel32.GetStdHandle(standard & 0xFFFFFFFF)
        if handle:
            kernel32.SetHandleInformation(handle, 1, 1)
        setattr(startup, field, handle)
    line = ctypes.create_unicode_buffer(subprocess.list2cmdline(argv))
    process = rt._ProcessInformation()
    if not advapi32.CreateProcessAsUserW(low, None, line, None, None, True, 0, None, None, ctypes.byref(startup), ctypes.byref(process)):
        return f"CreateProcessAsUserW {ctypes.get_last_error()}"
    kernel32.WaitForSingleObject(process.hProcess, 120000)
    code = wintypes.DWORD()
    kernel32.GetExitCodeProcess(process.hProcess, ctypes.byref(code))
    return f"exit=0x{code.value:08X}"


if len(sys.argv) > 1 and sys.argv[1] == "--low":
    print(low_run(sys.argv[2:]), flush=True)
    sys.exit(0)

root = Path(tempfile.mkdtemp()).resolve()
unit_a = root / "unit-a"
unit_b = root / "unit-b"
for directory in (unit_a, unit_b):
    directory.mkdir()
    print("label", directory.name, subprocess.run(["icacls", str(directory), "/setintegritylevel", "(OI)(CI)low"], capture_output=True, text=True).returncode)
probe = (
    "import sys, uuid, os\n"
    "for directory in sys.argv[1:]:\n"
    "    path = os.path.join(directory, 'omh-probe-' + uuid.uuid4().hex)\n"
    "    try:\n"
    "        open(path, 'w').write('x')\n"
    "    except OSError as error:\n"
    "        print('refused', directory, error.errno)\n"
    "    else:\n"
    "        print('WRITABLE', directory)\n"
    "        os.remove(path)\n"
)
locations = [unit_a, unit_b, root, Path(os.environ["USERPROFILE"]) / "AppData" / "LocalLow", Path(os.environ["LOCALAPPDATA"]) / "Temp", Path(os.environ["USERPROFILE"])]
env = {**os.environ, "TEMP": str(unit_a), "TMP": str(unit_a)}
cases = {
    "python-locations": [sys.executable, "-I", "-B", "-c", probe, *map(str, locations)],
    "node-pipe-child": ["node", "-e", "const r=require('child_process').spawnSync(process.execPath,['-e','console.log(1)'],{encoding:'utf8'}); console.log('child', r.status, JSON.stringify(r.stdout), r.error && r.error.message)"],
    "git-version": ["git", "--version"],
    "node-write-unit": ["node", "-e", "require('fs').writeFileSync(process.argv[1], 'x'); console.log('node-ok')", str(unit_a / "node")],
}
for label, argv in cases.items():
    completed = subprocess.run([sys.executable, __file__, "--low", *argv], capture_output=True, text=True, env=env, cwd=unit_a, timeout=180)
    print(f"--- low {label}: {completed.stdout.strip()} | {completed.stderr.strip()[-300:]}", flush=True)
