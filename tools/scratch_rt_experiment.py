"""Scratch v4: why node child_process fails under the restricted token. Not for merge."""
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "coding"))
import fanout_restricted_token as rt  # noqa: E402

root = Path(tempfile.mkdtemp()).resolve()
granted = root / "granted"
granted.mkdir()
sid = rt.write_root_sid(granted)
rt.grant_write_root(granted, sid, directory=True)
sids = [sid, "S-1-1-0", "S-1-5-12"]

node_cases = {
    "ignore": "const r=require('child_process').spawnSync(process.execPath,['-e','0'],{stdio:'ignore'}); console.log(r.status, r.error && r.error.message)",
    "inherit": "const r=require('child_process').spawnSync(process.execPath,['-e','0'],{stdio:'inherit'}); console.log(r.status, r.error && r.error.message)",
    "pipe": "const r=require('child_process').spawnSync(process.execPath,['-e','console.log(1)'],{stdio:'pipe',encoding:'utf8'}); console.log(r.status, JSON.stringify(r.stdout), r.error && r.error.message)",
    "cmd_pipe": "const r=require('child_process').spawnSync('cmd.exe',['/c','echo hi'],{encoding:'utf8'}); console.log(r.status, JSON.stringify(r.stdout), r.error && r.error.message)",
    "net_server": "const s=require('net').createServer(); s.listen('\\\\\\\\.\\\\pipe\\\\omh-probe-'+process.pid, ()=>{console.log('listening'); s.close();}); s.on('error', e=>console.log('err', e.code))",
    "async_spawn": "const c=require('child_process').spawn(process.execPath,['-e','console.log(7)']); c.on('error',e=>console.log('err',e.code, e.syscall)); c.stdout.on('data',d=>console.log('out',String(d).trim())); c.on('exit',x=>console.log('exit',x))",
    "fs_tmp": "const os=require('os'); console.log(os.tmpdir()); require('fs').writeFileSync(require('path').join(os.tmpdir(),'n'), 'x'); console.log('tmp-ok')",
}
for skip in ("0", "1"):
  for label, code in node_cases.items():
    command = rt.launcher_command(sys.executable, sids, ["node", "-e", code])
    completed = subprocess.run(command, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL,
                               env={**__import__("os").environ, "TEMP": str(granted), "TMP": str(granted), "OMH_RT_SKIP_DACL": skip})
    print(f"--- skip_dacl={skip} node {label}: exit={completed.returncode & 0xFFFFFFFF:08X} out={completed.stdout.strip()!r} err={completed.stderr.strip()[-300:]!r}", flush=True)
