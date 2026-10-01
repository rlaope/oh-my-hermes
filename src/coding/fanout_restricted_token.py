"""Windows write fence for fanout: a write-restricted token plus per-root DACL grants.

The boundary is the one the macOS and Linux backends implement: writes outside
the granted roots fail, reads are unrestricted. A token created with
``WRITE_RESTRICTED`` runs the restricting-SID access check for write access
only, so reads keep the user's own access while a write must also be granted to
one of the restricting SIDs. Each write root is granted to its own SID, derived
from its resolved path; no other object on the host names those SIDs, so a
write anywhere else fails the second check. ``DISABLE_MAX_PRIVILEGE`` drops
every privilege except change-notify, because an elevated token's
backup/restore privileges would otherwise bypass the DACL entirely.

This module is imported by the dispatcher (to grant roots) and also run as a
script by path (``python -I -B <this file> <sid>[,<sid>...] -- <argv...>``) to
start one command under the restricted token. As a script it imports nothing
outside the standard library, so the interpreter running it needs no ``omh``
on its path. Every Windows call is made inside a function, so importing it on
another platform is safe.
"""

from __future__ import annotations

from collections.abc import Sequence
import ctypes
import hashlib
import os
from pathlib import Path
import subprocess
import sys

_SID_DOMAIN = "omh-fanout-write-root"

_TOKEN_ASSIGN_PRIMARY = 0x0001
_TOKEN_DUPLICATE = 0x0002
_TOKEN_QUERY = 0x0008
_TOKEN_ADJUST_DEFAULT = 0x0080
_DISABLE_MAX_PRIVILEGE = 0x1
_WRITE_RESTRICTED = 0x8
_TOKEN_USER = 1
_TOKEN_DEFAULT_DACL = 6
_SDDL_REVISION_1 = 1
_STARTF_USESTDHANDLES = 0x00000100
_HANDLE_FLAG_INHERIT = 0x00000001
_CREATE_SUSPENDED = 0x00000004
_INFINITE = 0xFFFFFFFF
_DWORD_FAILURE = 0xFFFFFFFF
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_SE_FILE_OBJECT = 1
_DACL_SECURITY_INFORMATION = 0x00000004
_ACL_SIZE_INFORMATION = 2
_ACCESS_ALLOWED_ACE_TYPE = 0
_INHERITED_ACE = 0x10
_OBJECT_AND_CONTAINER_INHERIT = 0x3
_GRANT_ACCESS = 1
_TRUSTEE_IS_SID = 0
# icacls "M": read, write, execute and delete. Granted per root, never to a parent.
_MODIFY_ACCESS = 0x001301BF


def write_root_sid(path: Path) -> str:
    """Return the restricting SID that names exactly one resolved write root.

    The value is a pure function of the path (case-folded, as Windows compares
    paths), so a second grant to the same root is recognised instead of stacked.
    It is a well-formed SID no account owns: it only ever appears in a DACL
    written by `grant_write_root` and in a restricted token's restricting list,
    which cannot widen the access of any token that does not carry it.
    """
    digest = hashlib.sha256(f"{_SID_DOMAIN}\0{str(path).casefold()}".encode("utf-8")).digest()
    parts = (int.from_bytes(digest[index:index + 4], "big") for index in range(0, 16, 4))
    return "S-1-5-21-" + "-".join(str(part) for part in parts)


def launcher_command(
    interpreter: str, sids: Sequence[str], argv: Sequence[str]
) -> tuple[str, ...]:
    """The argv that runs `argv` under a token restricted to `sids`."""
    return (interpreter, "-I", "-B", str(Path(__file__).resolve()), ",".join(sids), "--", *argv)


def parse_launcher_arguments(arguments: Sequence[str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if len(arguments) < 3 or arguments[1] != "--":
        raise ValueError("usage: <sid>[,<sid>...] -- <argv...>")
    sids = tuple(sid for sid in arguments[0].split(",") if sid)
    if not sids or not all(sid.startswith("S-1-") for sid in sids):
        raise ValueError("at least one restricting SID is required")
    return sids, tuple(arguments[2:])


def _windows() -> tuple[ctypes.WinDLL, ctypes.WinDLL]:  # type: ignore[name-defined]
    if sys.platform != "win32":
        raise OSError("write-restricted tokens exist only on Windows")
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)  # type: ignore[attr-defined]
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    handle, dword, pointer = wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p
    signatures = {
        (advapi32, "OpenProcessToken"): ([handle, dword, ctypes.POINTER(handle)], wintypes.BOOL),
        (advapi32, "ConvertStringSidToSidW"): ([wintypes.LPCWSTR, ctypes.POINTER(pointer)], wintypes.BOOL),
        (advapi32, "ConvertSidToStringSidW"): ([pointer, ctypes.POINTER(wintypes.LPWSTR)], wintypes.BOOL),
        (advapi32, "CreateRestrictedToken"): (
            [handle, dword, dword, pointer, dword, pointer, dword, pointer, ctypes.POINTER(handle)],
            wintypes.BOOL,
        ),
        (advapi32, "GetTokenInformation"): ([handle, ctypes.c_int, pointer, dword, ctypes.POINTER(dword)], wintypes.BOOL),
        (advapi32, "SetTokenInformation"): ([handle, ctypes.c_int, pointer, dword], wintypes.BOOL),
        (advapi32, "ConvertStringSecurityDescriptorToSecurityDescriptorW"): (
            [wintypes.LPCWSTR, dword, ctypes.POINTER(pointer), ctypes.POINTER(dword)],
            wintypes.BOOL,
        ),
        (advapi32, "GetSecurityDescriptorDacl"): (
            [pointer, ctypes.POINTER(wintypes.BOOL), ctypes.POINTER(pointer), ctypes.POINTER(wintypes.BOOL)],
            wintypes.BOOL,
        ),
        (advapi32, "CreateProcessAsUserW"): (
            [handle, wintypes.LPCWSTR, wintypes.LPWSTR, pointer, pointer, wintypes.BOOL, dword,
             pointer, wintypes.LPCWSTR, pointer, pointer],
            wintypes.BOOL,
        ),
        (advapi32, "GetNamedSecurityInfoW"): (
            [wintypes.LPCWSTR, ctypes.c_int, dword, pointer, pointer, ctypes.POINTER(pointer), pointer,
             ctypes.POINTER(pointer)],
            dword,
        ),
        (advapi32, "SetNamedSecurityInfoW"): (
            [wintypes.LPWSTR, ctypes.c_int, dword, pointer, pointer, pointer, pointer], dword,
        ),
        (advapi32, "SetEntriesInAclW"): ([wintypes.ULONG, pointer, pointer, ctypes.POINTER(pointer)], dword),
        (advapi32, "GetAclInformation"): ([pointer, pointer, dword, ctypes.c_int], wintypes.BOOL),
        (advapi32, "GetAce"): ([pointer, dword, ctypes.POINTER(pointer)], wintypes.BOOL),
        (advapi32, "EqualSid"): ([pointer, pointer], wintypes.BOOL),
        (kernel32, "GetCurrentProcess"): ([], handle),
        (kernel32, "GetStdHandle"): ([dword], handle),
        (kernel32, "SetHandleInformation"): ([handle, dword, dword], wintypes.BOOL),
        (kernel32, "CreateJobObjectW"): ([pointer, wintypes.LPCWSTR], handle),
        (kernel32, "SetInformationJobObject"): ([handle, ctypes.c_int, pointer, dword], wintypes.BOOL),
        (kernel32, "AssignProcessToJobObject"): ([handle, handle], wintypes.BOOL),
        (kernel32, "ResumeThread"): ([handle], dword),
        (kernel32, "TerminateProcess"): ([handle, wintypes.UINT], wintypes.BOOL),
        (kernel32, "WaitForSingleObject"): ([handle, dword], dword),
        (kernel32, "GetExitCodeProcess"): ([handle, ctypes.POINTER(dword)], wintypes.BOOL),
        (kernel32, "CloseHandle"): ([handle], wintypes.BOOL),
        (kernel32, "LocalFree"): ([pointer], pointer),
    }
    for (library, name), (argtypes, restype) in signatures.items():
        function = getattr(library, name)
        function.argtypes = argtypes
        function.restype = restype
    return advapi32, kernel32


def _failed(name: str, error: int | None = None) -> OSError:
    code = ctypes.get_last_error() if error is None else error  # type: ignore[attr-defined]
    return OSError(code, f"{name} failed (Windows error {code})")


def _sid_pointer(advapi32: ctypes.WinDLL, sid: str) -> ctypes.c_void_p:  # type: ignore[name-defined]
    pointer = ctypes.c_void_p()
    if not advapi32.ConvertStringSidToSidW(sid, ctypes.byref(pointer)):
        raise _failed(f"ConvertStringSidToSidW({sid})")
    return pointer


class _AceHeader(ctypes.Structure):
    _fields_ = [("AceType", ctypes.c_ubyte), ("AceFlags", ctypes.c_ubyte), ("AceSize", ctypes.c_ushort)]


class _AccessAllowedAce(ctypes.Structure):
    _fields_ = [("Header", _AceHeader), ("Mask", ctypes.c_uint32), ("SidStart", ctypes.c_uint32)]


class _AclSizeInformation(ctypes.Structure):
    _fields_ = [("AceCount", ctypes.c_uint32), ("AclBytesInUse", ctypes.c_uint32), ("AclBytesFree", ctypes.c_uint32)]


class _Trustee(ctypes.Structure):
    _fields_ = [
        ("pMultipleTrustee", ctypes.c_void_p),
        ("MultipleTrusteeOperation", ctypes.c_int),
        ("TrusteeForm", ctypes.c_int),
        ("TrusteeType", ctypes.c_int),
        ("ptstrName", ctypes.c_void_p),
    ]


class _ExplicitAccess(ctypes.Structure):
    _fields_ = [
        ("grfAccessPermissions", ctypes.c_uint32),
        ("grfAccessMode", ctypes.c_int),
        ("grfInheritance", ctypes.c_uint32),
        ("Trustee", _Trustee),
    ]


def grant_write_root(path: Path, sid: str, *, directory: bool) -> bool:
    """Give `sid` modify access to `path`; return False when it already had it.

    A directory grant is inheritable to files and subdirectories, and setting
    it propagates to the existing tree, which is the one-time cost on a large
    owner state directory. An explicit grant already present on the root is
    recognised and left alone, so a later run does not walk the tree again.
    The grant persists after the run: the SID is carried only by tokens this
    module creates, so it adds no access for anything else.
    """
    advapi32, kernel32 = _windows()
    sid_pointer = _sid_pointer(advapi32, sid)
    descriptor = ctypes.c_void_p()
    new_dacl = ctypes.c_void_p()
    try:
        dacl = ctypes.c_void_p()
        error = advapi32.GetNamedSecurityInfoW(
            str(path), _SE_FILE_OBJECT, _DACL_SECURITY_INFORMATION, None, None,
            ctypes.byref(dacl), None, ctypes.byref(descriptor),
        )
        if error:
            raise _failed(f"GetNamedSecurityInfoW({path})", error)
        inheritance = _OBJECT_AND_CONTAINER_INHERIT if directory else 0
        if dacl.value and _has_explicit_grant(advapi32, dacl, sid_pointer, inheritance):
            return False
        entry = _ExplicitAccess(
            _MODIFY_ACCESS, _GRANT_ACCESS, inheritance,
            _Trustee(None, 0, _TRUSTEE_IS_SID, 0, sid_pointer.value),
        )
        error = advapi32.SetEntriesInAclW(1, ctypes.byref(entry), dacl, ctypes.byref(new_dacl))
        if error:
            raise _failed("SetEntriesInAclW", error)
        error = advapi32.SetNamedSecurityInfoW(
            str(path), _SE_FILE_OBJECT, _DACL_SECURITY_INFORMATION, None, None, new_dacl, None,
        )
        if error:
            raise _failed(f"SetNamedSecurityInfoW({path})", error)
        return True
    finally:
        for allocation in (new_dacl, descriptor, sid_pointer):
            if allocation.value:
                kernel32.LocalFree(allocation)


def _has_explicit_grant(
    advapi32: ctypes.WinDLL,  # type: ignore[name-defined]
    dacl: ctypes.c_void_p,
    sid_pointer: ctypes.c_void_p,
    inheritance: int,
) -> bool:
    size = _AclSizeInformation()
    if not advapi32.GetAclInformation(dacl, ctypes.byref(size), ctypes.sizeof(size), _ACL_SIZE_INFORMATION):
        raise _failed("GetAclInformation")
    for index in range(size.AceCount):
        ace = ctypes.c_void_p()
        if not advapi32.GetAce(dacl, index, ctypes.byref(ace)):
            raise _failed("GetAce")
        allowed = ctypes.cast(ace, ctypes.POINTER(_AccessAllowedAce)).contents
        if (
            allowed.Header.AceType == _ACCESS_ALLOWED_ACE_TYPE
            and not allowed.Header.AceFlags & _INHERITED_ACE
            and allowed.Header.AceFlags & _OBJECT_AND_CONTAINER_INHERIT == inheritance
            and allowed.Mask & _MODIFY_ACCESS == _MODIFY_ACCESS
            and advapi32.EqualSid(ace.value + _AccessAllowedAce.SidStart.offset, sid_pointer)
        ):
            return True
    return False


class _SidAndAttributes(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", ctypes.c_uint32)]


class _StartupInfo(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_uint32),
        ("lpReserved", ctypes.c_wchar_p),
        ("lpDesktop", ctypes.c_wchar_p),
        ("lpTitle", ctypes.c_wchar_p),
        ("dwX", ctypes.c_uint32),
        ("dwY", ctypes.c_uint32),
        ("dwXSize", ctypes.c_uint32),
        ("dwYSize", ctypes.c_uint32),
        ("dwXCountChars", ctypes.c_uint32),
        ("dwYCountChars", ctypes.c_uint32),
        ("dwFillAttribute", ctypes.c_uint32),
        ("dwFlags", ctypes.c_uint32),
        ("wShowWindow", ctypes.c_ushort),
        ("cbReserved2", ctypes.c_ushort),
        ("lpReserved2", ctypes.c_void_p),
        ("hStdInput", ctypes.c_void_p),
        ("hStdOutput", ctypes.c_void_p),
        ("hStdError", ctypes.c_void_p),
    ]


class _ProcessInformation(ctypes.Structure):
    _fields_ = [
        ("hProcess", ctypes.c_void_p),
        ("hThread", ctypes.c_void_p),
        ("dwProcessId", ctypes.c_uint32),
        ("dwThreadId", ctypes.c_uint32),
    ]


class _JobBasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class _JobExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JobBasicLimitInformation),
        ("IoInfo", ctypes.c_uint64 * 6),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def _token_user_sid(
    advapi32: ctypes.WinDLL, kernel32: ctypes.WinDLL, token: ctypes.c_void_p  # type: ignore[name-defined]
) -> str:
    from ctypes import wintypes

    needed = wintypes.DWORD()
    advapi32.GetTokenInformation(token, _TOKEN_USER, None, 0, ctypes.byref(needed))
    buffer = ctypes.create_string_buffer(needed.value)
    if not advapi32.GetTokenInformation(token, _TOKEN_USER, buffer, needed, ctypes.byref(needed)):
        raise _failed("GetTokenInformation(TokenUser)")
    user = _SidAndAttributes.from_buffer(buffer)
    text = wintypes.LPWSTR()
    if not advapi32.ConvertSidToStringSidW(user.Sid, ctypes.byref(text)):
        raise _failed("ConvertSidToStringSidW")
    try:
        return str(text.value)
    finally:
        kernel32.LocalFree(text)


def run_restricted(sids: Sequence[str], argv: Sequence[str]) -> int:
    """Run `argv` under a write-restricted token and return its exit code.

    The child starts suspended inside a kill-on-close Job Object owned by this
    process, so terminating this launcher (taskkill, a timeout) also ends every
    process the child started. Standard handles are passed through unchanged,
    and the environment and working directory are inherited.
    """
    from ctypes import wintypes

    advapi32, kernel32 = _windows()
    token = wintypes.HANDLE()
    access = _TOKEN_ASSIGN_PRIMARY | _TOKEN_DUPLICATE | _TOKEN_QUERY | _TOKEN_ADJUST_DEFAULT
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), access, ctypes.byref(token)):
        raise _failed("OpenProcessToken")
    sid_pointers = [_sid_pointer(advapi32, sid) for sid in sids]
    restricting = (_SidAndAttributes * len(sid_pointers))(
        *(_SidAndAttributes(pointer.value, 0) for pointer in sid_pointers)
    )
    restricted = wintypes.HANDLE()
    if not advapi32.CreateRestrictedToken(
        token, _DISABLE_MAX_PRIVILEGE | _WRITE_RESTRICTED, 0, None, 0, None,
        len(sid_pointers), restricting, ctypes.byref(restricted),
    ):
        raise _failed("CreateRestrictedToken")
    # Objects the child creates without an inheritable parent DACL (named
    # pipes for its own children, events) take the token's default DACL. The
    # restricting check applies to them too, so it must name the SIDs or the
    # child could not write to what it just created.
    principals = ("SY", _token_user_sid(advapi32, kernel32, token), *sids)
    sddl = "D:" + "".join(f"(A;;GA;;;{principal})" for principal in principals)
    descriptor = ctypes.c_void_p()
    if not advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        sddl, _SDDL_REVISION_1, ctypes.byref(descriptor), None
    ):
        raise _failed("ConvertStringSecurityDescriptorToSecurityDescriptorW")
    present, defaulted, dacl = wintypes.BOOL(), wintypes.BOOL(), ctypes.c_void_p()
    if not advapi32.GetSecurityDescriptorDacl(descriptor, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)):
        raise _failed("GetSecurityDescriptorDacl")
    default_dacl = ctypes.c_void_p(dacl.value)
    if os.environ.get("OMH_RT_SKIP_DACL") != "1" and not advapi32.SetTokenInformation(
        restricted, _TOKEN_DEFAULT_DACL, ctypes.byref(default_dacl), ctypes.sizeof(default_dacl)
    ):
        raise _failed("SetTokenInformation(TokenDefaultDacl)")
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise _failed("CreateJobObjectW")
    limits = _JobExtendedLimitInformation()
    limits.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel32.SetInformationJobObject(
        job, _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, ctypes.byref(limits), ctypes.sizeof(limits)
    ):
        raise _failed("SetInformationJobObject")
    startup = _StartupInfo()
    startup.cb = ctypes.sizeof(startup)
    startup.dwFlags = _STARTF_USESTDHANDLES
    invalid = ctypes.c_void_p(-1).value
    for field, standard in (("hStdInput", -10), ("hStdOutput", -11), ("hStdError", -12)):
        handle = kernel32.GetStdHandle(standard & 0xFFFFFFFF)
        if handle and handle != invalid:
            # A handle this launcher inherited is usually inheritable already;
            # setting the flag again is harmless and covers one that is not.
            kernel32.SetHandleInformation(handle, _HANDLE_FLAG_INHERIT, _HANDLE_FLAG_INHERIT)
        setattr(startup, field, handle)
    command_line = ctypes.create_unicode_buffer(subprocess.list2cmdline(list(argv)))
    process = _ProcessInformation()
    if not advapi32.CreateProcessAsUserW(
        restricted, None, command_line, None, None, True, _CREATE_SUSPENDED,
        None, None, ctypes.byref(startup), ctypes.byref(process),
    ):
        raise _failed(f"CreateProcessAsUserW({argv[0]})")
    try:
        if not kernel32.AssignProcessToJobObject(job, process.hProcess):
            error = ctypes.get_last_error()  # type: ignore[attr-defined]
            kernel32.TerminateProcess(process.hProcess, 1)
            raise _failed("AssignProcessToJobObject", error)
        if kernel32.ResumeThread(process.hThread) == _DWORD_FAILURE:
            error = ctypes.get_last_error()  # type: ignore[attr-defined]
            kernel32.TerminateProcess(process.hProcess, 1)
            raise _failed("ResumeThread", error)
        kernel32.WaitForSingleObject(process.hProcess, _INFINITE)
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(process.hProcess, ctypes.byref(code)):
            raise _failed("GetExitCodeProcess")
        return int(code.value)
    finally:
        kernel32.CloseHandle(process.hThread)
        kernel32.CloseHandle(process.hProcess)


def main(arguments: Sequence[str]) -> int:
    try:
        sids, argv = parse_launcher_arguments(arguments)
    except ValueError as exc:
        sys.stderr.write(f"omh-restricted-token: {exc}\n")
        return 2
    try:
        return run_restricted(sids, argv)
    except OSError as exc:
        sys.stderr.write(f"omh-restricted-token: {exc}\n")
        return 125


if __name__ == "__main__":
    exit_code = main(sys.argv[1:])
    sys.stdout.flush()
    sys.stderr.flush()
    # A Windows exit code is a DWORD; os._exit takes a C int, and a negative
    # int wraps back to the same DWORD.
    os._exit(exit_code - (1 << 32) if exit_code >= (1 << 31) else exit_code)
