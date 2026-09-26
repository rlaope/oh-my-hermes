"""Deterministic Windows API contracts; host simulation is not native evidence."""
from __future__ import annotations

import ctypes
import errno
import hashlib
import os
import stat
import unittest
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from functools import cached_property
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Protocol, final
from unittest.mock import Mock, patch

from _local_package import load_local_package
from _typing_support import override
from test_working_tree_fingerprint import ContentOS, entry_digest, path_stat

load_local_package()
from omh.quality import working_tree_fingerprint_content as content
from omh.quality import working_tree_fingerprint_windows as windows
from _module_patch import patch_modules


class _WindowsPort(Protocol):
    @property
    def _BasicInfo(self) -> type[ctypes.Structure]: ...
    @property
    def _StandardInfo(self) -> type[ctypes.Structure]: ...
    @property
    def _IdInfo(self) -> type[ctypes.Structure]: ...
    def _close_handle(self, handle: int) -> None: ...


class _WindowsAccess(_WindowsPort, Protocol):
    def layouts(self: _WindowsPort) -> tuple[type[ctypes.Structure], type[ctypes.Structure], type[ctypes.Structure]]:
        return self._IdInfo, self._BasicInfo, self._StandardInfo

    def close(self: _WindowsPort, handle: int) -> None:
        self._close_handle(handle)


_windows_port: _WindowsPort = windows


# Independent fixed-width ABI views: the real module allocates the buffers,
# these views fill them, and windows.stat must decode every field correctly.
@final
class _BasicInfo(ctypes.Structure):
    # ctypes replaces these defaults with the real _fields_ descriptors.
    CreationTime: int = 0
    LastAccessTime: int = 0
    LastWriteTime: int = 0
    ChangeTime: int = 0
    FileAttributes: int = 0
    _fields_ = [
        ("CreationTime", ctypes.c_int64), ("LastAccessTime", ctypes.c_int64),
        ("LastWriteTime", ctypes.c_int64), ("ChangeTime", ctypes.c_int64),
        ("FileAttributes", ctypes.c_uint32),
    ]


@final
class _StandardInfo(ctypes.Structure):
    AllocationSize: int = 0
    EndOfFile: int = 0
    NumberOfLinks: int = 0
    DeletePending: int = 0
    Directory: int = 0
    _fields_ = [
        ("AllocationSize", ctypes.c_int64), ("EndOfFile", ctypes.c_int64),
        ("NumberOfLinks", ctypes.c_uint32), ("DeletePending", ctypes.c_ubyte),
        ("Directory", ctypes.c_ubyte),
    ]


@final
class _IdInfo(ctypes.Structure):
    VolumeSerialNumber: int = 0
    FileId: ctypes.Array[ctypes.c_ubyte] = (ctypes.c_ubyte * 16)()
    _fields_ = [("VolumeSerialNumber", ctypes.c_uint64), ("FileId", ctypes.c_ubyte * 16)]


@dataclass
class _HandleApi:
    information: Callable[[int, int, object, int], int]

    @cached_property
    def CreateFileW(self) -> Mock:
        return Mock(return_value=123)

    @cached_property
    def CloseHandle(self) -> Mock:
        return Mock(return_value=1)

    @cached_property
    def GetFileType(self) -> Mock:
        return Mock(return_value=1)

    @cached_property
    def GetFileInformationByHandleEx(self) -> Mock:
        return Mock(side_effect=self.information)


class _CRT:
    @cached_property
    def open_osfhandle(self) -> Mock:
        return Mock(return_value=42)

    @cached_property
    def setmode(self) -> Mock:
        return Mock()

    @cached_property
    def get_osfhandle(self) -> Mock:
        return Mock(return_value=123)


@final
@dataclass
class _HandleOS:
    O_RDONLY: int = os.O_RDONLY
    O_NOINHERIT: int = 0x80
    O_BINARY: int = 0x8000
    fsdecode = staticmethod(os.fsdecode)

    @cached_property
    def close(self) -> Mock:
        return Mock()


@dataclass
class _ReadRecorder:
    sizes: list[int] = field(default_factory=list)
    operation: Callable[[int, int], bytes] = os.read

    def __call__(self, fd: int, size: int) -> bytes:
        self.sizes.append(size)
        return self.operation(fd, size)


class WindowsHandleApiTests(unittest.TestCase):
    @override
    def setUp(self) -> None:
        for name in ("api", "identity", "pending", "attributes", "directory", "queries"):
            self.addCleanup(self.__dict__.pop, name, None)
        _ = self.api, self.identity, self.pending, self.attributes, self.directory, self.queries
        binding = patch.object(windows, "_api", return_value=self.api)
        _ = binding.start()
        self.addCleanup(binding.stop)

    @cached_property
    def api(self) -> _HandleApi:
        return _HandleApi(self.information)

    @cached_property
    def identity(self) -> tuple[int, int]:
        return (9, (1 << 120) + 7)

    @cached_property
    def pending(self) -> bool:
        return False

    @cached_property
    def attributes(self) -> int:
        return 0x80

    @cached_property
    def directory(self) -> bool:
        return False

    @cached_property
    def queries(self) -> list[int]:
        return []

    def information(self, handle: int, kind: int, pointer: object, size: int) -> int:
        pointer_arg = ctypes.c_void_p.from_param(pointer)
        self.assertEqual(handle, 123)
        self.queries.append(kind)
        if kind == 18:
            self.assertEqual(size, ctypes.sizeof(_IdInfo))
            identity = ctypes.cast(pointer_arg, ctypes.POINTER(_IdInfo)).contents
            identity.VolumeSerialNumber = self.identity[0]
            identity.FileId[:] = self.identity[1].to_bytes(16, "little")
        elif kind == 0:
            self.assertEqual(size, ctypes.sizeof(_BasicInfo))
            basic = ctypes.cast(pointer_arg, ctypes.POINTER(_BasicInfo)).contents
            basic.CreationTime, basic.LastAccessTime = 10, 20
            basic.LastWriteTime, basic.ChangeTime = 30, 40
            basic.FileAttributes = self.attributes
        else:
            self.assertEqual(kind, 1)
            self.assertEqual(size, ctypes.sizeof(_StandardInfo))
            standard = ctypes.cast(pointer_arg, ctypes.POINTER(_StandardInfo)).contents
            standard.EndOfFile, standard.NumberOfLinks = 17, 1
            standard.DeletePending, standard.Directory = self.pending, self.directory
        return 1

    def test_native_struct_layout_and_full_width_identity_times(self) -> None:
        identity, basic, standard = _WindowsAccess.layouts(_windows_port)
        self.assertEqual(ctypes.sizeof(identity), 24)
        self.assertEqual(ctypes.sizeof(basic), 40)
        self.assertEqual(ctypes.sizeof(standard), 24)
        result = windows.stat(b"C:\\repo\\file.exe")
        self.assertEqual(self.queries, [18, 0, 1])
        self.assertEqual(result, windows.Metadata(9, (1 << 120) + 7, 17, 3000, 4000, 1000, 0x80, 1))
        self.assertEqual(result.st_mode, stat.S_IFREG | 0o666)
        self.api.CreateFileW.assert_called_once_with("C:\\repo\\file.exe", 0x80, 7, None, 3, 0x02200000, None)
        self.api.CloseHandle.assert_called_once_with(123)

    def test_zero_identity_and_pending_deletion_never_become_wildcards(self) -> None:
        for volume, inode, pending in ((0, 7, False), (9, 0, False), (9, 7, True)):
            with self.subTest(volume=volume, inode=inode, pending=pending):
                self.identity, self.pending = (volume, inode), pending
                with self.assertRaises(OSError):
                    _ = windows.stat(b"file")
        self.assertEqual(self.api.CloseHandle.call_count, 3)

    def test_disk_type_and_directory_disagreement_refuse(self) -> None:
        self.api.GetFileType.return_value = 3
        with self.assertRaises(OSError):
            _ = windows.stat(b"pipe")
        self.api.GetFileInformationByHandleEx.assert_not_called()
        self.api.GetFileType.return_value = 1
        self.directory = True
        with self.assertRaises(OSError):
            _ = windows.stat(b"changed-type")
        self.assertEqual(self.api.CloseHandle.call_count, 2)

    def test_reparse_and_readonly_attributes_are_preserved(self) -> None:
        self.attributes = 0x400
        self.assertFalse(stat.S_ISREG(windows.stat(b"reparse").st_mode))
        self.attributes = 1
        self.assertEqual(windows.stat(b"readonly").st_mode, stat.S_IFREG | 0o444)

    def test_query_and_open_failures_are_visible_and_handles_close(self) -> None:
        error = OSError(errno.EACCES, "native query refused")
        with patch.object(ctypes, "get_last_error", return_value=5, create=True), patch.object(
            ctypes, "WinError", return_value=error, create=True,
        ):
            for kind in (18, 0, 1):
                with self.subTest(kind=kind):
                    def query(handle: int, observed_kind: int, pointer: object, size: int) -> int:
                        return 0 if observed_kind == kind else self.information(handle, observed_kind, pointer, size)
                    self.api.GetFileInformationByHandleEx.side_effect = query
                    with self.assertRaises(OSError):
                        _ = windows.stat(b"file")
            self.assertEqual(self.api.CloseHandle.call_count, 3)
            self.api.CreateFileW.return_value = ctypes.c_void_p(-1).value
            with self.assertRaises(OSError):
                _ = windows.stat(b"file")
            self.assertEqual(self.api.CloseHandle.call_count, 3)
            self.api.CloseHandle.return_value = 0
            with self.assertRaises(OSError):
                _WindowsAccess.close(_windows_port, 123)

    def test_data_handle_ownership_binary_mode_and_writer_exclusion(self) -> None:
        crt = _CRT()
        platform_os = _HandleOS()
        with patch_modules({"msvcrt": crt}), patch.object(windows, "os", platform_os):
            self.assertEqual(windows.open(b"file"), 42)
            self.api.CreateFileW.assert_called_once_with("file", 0x80000000, 1, None, 3, 0x02200000, None)
            crt.open_osfhandle.assert_called_once_with(123, os.O_RDONLY | 0x80)
            crt.setmode.assert_called_once_with(42, 0x8000)
            self.api.CloseHandle.assert_not_called()  # transferred to CRT owner
            self.assertEqual(windows.fstat(42).st_ino, (1 << 120) + 7)
            crt.get_osfhandle.assert_called_once_with(42)
            crt.setmode.side_effect = OSError(errno.EACCES, "binary mode refused")
            with self.assertRaises(OSError):
                _ = windows.open(b"file")
            platform_os.close.assert_called_once_with(42)
            self.api.CloseHandle.assert_not_called()
            crt.open_osfhandle.side_effect = OSError(errno.EMFILE, "fd allocation failed")
            with self.assertRaises(OSError):
                _ = windows.open(b"file")
            self.api.CloseHandle.assert_called_once_with(123)


class WindowsObservationBoundaryTests(unittest.TestCase):
    @override
    def setUp(self) -> None:
        for name in ("root", "path", "payload", "raw_path", "platform_os", "stat_mock", "fstat_mock", "reader"):
            self.addCleanup(self.__dict__.pop, name, None)
        _ = self.root, self.path, self.payload
        _ = self.path.write_bytes(self.payload)
        _ = self.raw_path
        for target, name, value in (
            (content, "os", self.platform_os),
            (windows, "open", self.open_file),
            (windows, "stat", self.stat_mock),
            (windows, "fstat", self.fstat_mock),
        ):
            binding = patch.object(target, name, value)
            _ = binding.start()
            self.addCleanup(binding.stop)

    @cached_property
    def root(self) -> Path:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return Path(temporary.name)

    @cached_property
    def path(self) -> Path:
        return self.root / "file.exe"

    @cached_property
    def payload(self) -> bytes:
        return b"raw\r\nbytes\x1aafter\x00\xff"

    @cached_property
    def raw_path(self) -> bytes:
        return os.fsencode(self.path)

    @cached_property
    def platform_os(self) -> ContentOS:
        return ContentOS(name="nt", read=self.reader)

    @cached_property
    def reader(self) -> _ReadRecorder:
        return _ReadRecorder()

    @staticmethod
    def open_file(path: bytes) -> int:
        return os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))

    @cached_property
    def stat_mock(self) -> Mock:
        return Mock(side_effect=self.descriptor_stat)

    @cached_property
    def fstat_mock(self) -> Mock:
        return Mock(side_effect=self.descriptor_fstat)

    def descriptor_fstat(self, fd: int) -> windows.Metadata:
        return self.convert(os.fstat(fd))

    def descriptor_stat(self, path: bytes) -> windows.Metadata:
        # Match the facade's fstat family, not CPython Windows path-stat
        # timestamps/IDs. Reopen the name on every probe to retain race checks.
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
        try:
            return self.convert(os.fstat(descriptor))
        finally:
            os.close(descriptor)

    @staticmethod
    def convert(value: os.stat_result) -> windows.Metadata:
        attributes = 0x400 if stat.S_ISLNK(value.st_mode) else 0x80
        return windows.Metadata(value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns,
                                value.st_ctime_ns, 1000, attributes, value.st_nlink)

    def test_stable_stream_matches_raw_blob_with_bounded_reads(self) -> None:
        self.payload *= 200000
        _ = self.path.write_bytes(self.payload)
        result = content.overlay(self.root, [b"file.exe"], {})
        digest = hashlib.sha1(b"blob " + str(len(self.payload)).encode() + b"\0" + self.payload).hexdigest().encode()
        self.assertEqual(result, [(b"file.exe", b"100644", digest)])
        self.assertGreater(len(self.reader.sizes), 2)
        self.assertTrue(all(size <= 1024 * 1024 for size in self.reader.sizes))

    def test_distinct_opened_identity_refuses_before_read(self) -> None:
        before = path_stat(self.raw_path)
        replacement = self.root / "replacement"
        _ = replacement.write_bytes(self.payload)
        os.replace(replacement, self.path)
        with self.assertRaises(content.ContentRace):
            _ = entry_digest(self.raw_path, before)
        self.assertEqual(self.reader.sizes, [])

    def test_pre_read_named_replacement_refuses_even_when_fd_identity_matches(self) -> None:
        before = path_stat(self.raw_path)
        assert isinstance(before, windows.Metadata)
        self.stat_mock.side_effect = None
        self.stat_mock.return_value = replace(before, st_ino=before.st_ino + 1)
        with self.assertRaises(content.ContentRace):
            _ = entry_digest(self.raw_path, before)
        self.assertEqual(self.reader.sizes, [])

    def test_pre_read_reparse_replacement_refuses_without_reading_target(self) -> None:
        before = path_stat(self.raw_path)
        assert isinstance(before, windows.Metadata)
        self.fstat_mock.side_effect = None
        self.fstat_mock.return_value = replace(before, attributes=0x400)
        with self.assertRaises(content.ContentRace):
            _ = entry_digest(self.raw_path, before)
        self.assertEqual(self.reader.sizes, [])

    def test_every_native_race_field_is_checked_across_read(self) -> None:
        before = path_stat(self.raw_path)
        assert isinstance(before, windows.Metadata)
        for field_name, changed in (
            ("st_dev", replace(before, st_dev=before.st_dev + 1)),
            ("st_ino", replace(before, st_ino=before.st_ino + 1)),
            ("st_size", replace(before, st_size=before.st_size + 1)),
            ("st_mtime_ns", replace(before, st_mtime_ns=before.st_mtime_ns + 1)),
            ("st_ctime_ns", replace(before, st_ctime_ns=before.st_ctime_ns + 1)),
            ("creation_ns", replace(before, creation_ns=before.creation_ns + 1)),
            ("attributes", replace(before, attributes=before.attributes + 1)),
            ("links", replace(before, links=before.links + 1)),
        ):
            with self.subTest(field=field_name):
                self.fstat_mock.side_effect = [before, changed]
                with self.assertRaises(content.ContentRace):
                    _ = entry_digest(self.raw_path, before)

    def test_same_length_byte_change_during_read_fails_closed(self) -> None:
        changed = False

        def read(fd: int, size: int) -> bytes:
            nonlocal changed
            chunk = os.read(fd, size)
            if not changed:
                changed = True
                _ = self.path.write_bytes(self.payload[:-1] + b"x")
                # Deterministic metadata transition; no filesystem clock luck.
                value = self.path.stat()
                os.utime(self.path, ns=(value.st_atime_ns, value.st_mtime_ns + 1000000000))
            return chunk

        self.reader.operation = read
        with self.assertRaises(content.ContentRace):
            _ = content.overlay(self.root, [b"file.exe"], {})

    def test_post_read_named_replacement_fails_closed(self) -> None:
        before = path_stat(self.raw_path)
        assert isinstance(before, windows.Metadata)
        self.stat_mock.side_effect = [before, before, replace(before, st_ino=before.st_ino + 1)]
        with self.assertRaises(content.ContentRace):
            _ = content.overlay(self.root, [b"file.exe"], {})


if __name__ == "__main__":
    _ = unittest.main()
