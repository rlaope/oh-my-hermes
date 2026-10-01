"""Scratch v2: Everyone as a restricting SID -- what starts, what can be written. Not for merge."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

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


root = Path(tempfile.mkdtemp()).resolve()
granted = root / "granted"
granted.mkdir()
sid = rt.write_root_sid(granted)
print("grant", rt.grant_write_root(granted, sid, directory=True), flush=True)

candidates = [
    Path(os.environ.get("PUBLIC", r"C:\Users\Public")),
    Path(os.environ.get("ProgramData", r"C:\ProgramData")),
    Path(r"C:\Windows\Temp"),
    Path(r"C:\Windows\Tasks"),
    Path(r"C:\Windows\tracing"),
    Path(r"C:\Windows\System32\spool\drivers\color"),
    Path(r"C:\Windows\System32\Tasks"),
    Path("C:\\"),
    Path("D:\\"),
    Path(os.environ.get("LOCALAPPDATA", "")),
    Path(os.environ.get("APPDATA", "")),
    Path(os.environ.get("USERPROFILE", "")),
    Path(os.environ.get("LOCALAPPDATA", "")) / "Temp",
    Path(os.environ.get("USERPROFILE", "")) / "AppData" / "LocalLow",
    root,
]
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


def run(label, sids, argv):
    command = rt.launcher_command(sys.executable, sids, argv)
    completed = subprocess.run(command, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
    print(f"--- {label}: exit={completed.returncode & 0xFFFFFFFF:08X}")
    print(completed.stdout.strip())
    print(completed.stderr.strip()[-500:])


token = wintypes.HANDLE()
advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), 0x8, ctypes.byref(token))
logon = logon_sid(token)[1]
print("logon", logon)
for extra in (["S-1-1-0", logon], ["S-1-1-0", logon, "S-1-5-12"], ["S-1-1-0", "S-1-5-12"], ["S-1-1-0", logon, "S-1-5-32-545"]):
    sids = [sid, *extra]
    run(f"cmd {extra}", sids, ["cmd.exe", "/c", "echo cmd-ok"])
    run(f"git-abs {extra}", sids, [r"C:\\Program Files\\Git\\cmd\\git.exe", "--version"])
    run(f"python {extra}", sids, [sys.executable, "-I", "-B", "-c", "print('py-ok')"])
    run(f"git {extra}", sids, ["git", "--version"])
    run(f"node {extra}", sids, ["node", "-e", "require('fs').writeFileSync(process.argv[1], 'x'); console.log('node-ok')", str(granted / "node")])
    run(f"node-child {extra}", sids, ["node", "-e", "const r=require('child_process').spawnSync(process.execPath,['-e','console.log(1)'],{encoding:'utf8'}); console.log('child', r.status, r.stdout, r.error && r.error.message)"])
    run(f"py-child-pipes {extra}", sids, [sys.executable, "-I", "-B", "-c", "import subprocess, sys; r = subprocess.run([sys.executable, '-c', 'print(42)'], capture_output=True, text=True); print('child', r.returncode, r.stdout)"])
    run(f"locations {extra}", sids, [sys.executable, "-I", "-B", "-c", probe, *(str(path) for path in candidates)])
baseline = subprocess.run([sys.executable, "-I", "-B", "-c", probe, *(str(path) for path in candidates)], capture_output=True, text=True)
print("--- baseline unconfined")
print(baseline.stdout.strip())
