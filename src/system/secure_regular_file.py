"""Bounded no-follow I/O for security-sensitive local files."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import os
from pathlib import Path
import stat
from typing import Final

_BINARY: Final = getattr(os, "O_BINARY", 0)
_CLOEXEC: Final = getattr(os, "O_CLOEXEC", 0)
_DIRECTORY: Final = getattr(os, "O_DIRECTORY", 0)
_NOFOLLOW: Final = getattr(os, "O_NOFOLLOW", 0)
_REPARSE_POINT: Final = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
_DIRECTORY_FLAGS: Final = os.O_RDONLY | _BINARY | _CLOEXEC | _DIRECTORY | _NOFOLLOW


class SecureFileError(Exception):
    """Raised when a path cannot prove it names one regular file."""


def _uses_windows_fallback() -> bool:
    return os.name == "nt"


def _posix_components(path: Path) -> tuple[str, ...]:
    absolute = Path(os.path.abspath(path))
    components = absolute.parts[1:]
    if not components:
        raise SecureFileError(f"path must name a file: {path}")
    first = Path(absolute.anchor) / components[0]
    try:
        metadata = first.lstat()
    except FileNotFoundError:
        return components
    if not stat.S_ISLNK(metadata.st_mode):
        return components
    if metadata.st_uid != 0:
        raise SecureFileError(f"path contains a caller-controlled symlink: {first}")
    target = Path(os.readlink(first))
    if not target.is_absolute():
        target = first.parent / target
    canonical = Path(os.path.abspath(target))
    return (*canonical.parts[1:], *components[1:])


def _open_directory(parent: int, component: str, *, create: bool, private: bool) -> int:
    try:
        return os.open(component, _DIRECTORY_FLAGS, dir_fd=parent)
    except FileNotFoundError:
        if not create:
            raise
    try:
        os.mkdir(component, 0o700 if private else 0o777, dir_fd=parent)
    except FileExistsError:
        return os.open(component, _DIRECTORY_FLAGS, dir_fd=parent)
    return os.open(component, _DIRECTORY_FLAGS, dir_fd=parent)


@contextmanager
def _open_posix_parent(path: Path, *, create: bool, private: bool) -> Iterator[tuple[int, str]]:
    components = _posix_components(path)
    try:
        parent = os.open(os.sep, _DIRECTORY_FLAGS)
    except OSError as exc:
        raise SecureFileError(f"could not open filesystem root for: {path}") from exc
    try:
        for component in components[:-1]:
            try:
                child = _open_directory(parent, component, create=create, private=private)
            except OSError as exc:
                raise SecureFileError(f"path contains an unsafe directory: {path}") from exc
            os.close(parent)
            parent = child
        yield parent, components[-1]
    finally:
        os.close(parent)


def _verify_open_file_at(parent: int, name: str, descriptor: int, path: Path) -> None:
    opened = os.fstat(descriptor)
    if not stat.S_ISREG(opened.st_mode):
        raise SecureFileError(f"path is not a regular file: {path}")
    try:
        named = os.stat(name, dir_fd=parent, follow_symlinks=False)
    except OSError as exc:
        raise SecureFileError(f"path changed while opening: {path}") from exc
    if not stat.S_ISREG(named.st_mode):
        raise SecureFileError(f"path is not a regular file: {path}")
    if (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino):
        raise SecureFileError(f"path changed while opening: {path}")


def _reject_windows_symlinks(path: Path) -> None:
    absolute = Path(os.path.abspath(path))
    for component in reversed((absolute, *absolute.parents)):
        try:
            metadata = component.lstat()
        except FileNotFoundError:
            continue
        attributes = getattr(metadata, "st_file_attributes", 0)
        if stat.S_ISLNK(metadata.st_mode) or bool(attributes & _REPARSE_POINT):
            raise SecureFileError(f"path contains a symlink: {component}")


def _windows_ancestor_snapshot(path: Path) -> tuple[tuple[Path, int, int], ...]:
    snapshot: list[tuple[Path, int, int]] = []
    absolute = Path(os.path.abspath(path))
    for component in reversed(absolute.parents):
        try:
            metadata = component.lstat()
        except FileNotFoundError:
            continue
        attributes = getattr(metadata, "st_file_attributes", 0)
        if (
            stat.S_ISLNK(metadata.st_mode)
            or bool(attributes & _REPARSE_POINT)
            or not stat.S_ISDIR(metadata.st_mode)
        ):
            raise SecureFileError(f"path contains an unsafe directory: {component}")
        snapshot.append((component, metadata.st_dev, metadata.st_ino))
    return tuple(snapshot)


def _verify_windows_ancestors(snapshot: tuple[tuple[Path, int, int], ...]) -> None:
    for component, device, inode in snapshot:
        try:
            metadata = component.lstat()
        except OSError as exc:
            raise SecureFileError(f"path ancestor changed while opening: {component}") from exc
        attributes = getattr(metadata, "st_file_attributes", 0)
        if (
            stat.S_ISLNK(metadata.st_mode)
            or bool(attributes & _REPARSE_POINT)
            or not stat.S_ISDIR(metadata.st_mode)
            or (metadata.st_dev, metadata.st_ino) != (device, inode)
        ):
            raise SecureFileError(f"path ancestor changed while opening: {component}")


def _verify_windows_file(path: Path, descriptor: int) -> None:
    opened = os.fstat(descriptor)
    if not stat.S_ISREG(opened.st_mode):
        raise SecureFileError(f"path is not a regular file: {path}")
    try:
        named = path.lstat()
    except OSError as exc:
        raise SecureFileError(f"path changed while opening: {path}") from exc
    attributes = getattr(named, "st_file_attributes", 0)
    if (
        stat.S_ISLNK(named.st_mode)
        or bool(attributes & _REPARSE_POINT)
        or not stat.S_ISREG(named.st_mode)
    ):
        raise SecureFileError(f"path is not a regular file: {path}")
    if (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino):
        raise SecureFileError(f"path changed while opening: {path}")


def validate_no_symlinks(path: Path) -> None:
    """Reject caller-controlled symlinks in the currently existing path prefix."""
    if _uses_windows_fallback():
        _reject_windows_symlinks(path)
        return
    components = _posix_components(path)
    try:
        parent = os.open(os.sep, _DIRECTORY_FLAGS)
    except OSError as exc:
        raise SecureFileError(f"could not open filesystem root for: {path}") from exc
    try:
        for component in components[:-1]:
            try:
                child = os.open(component, _DIRECTORY_FLAGS, dir_fd=parent)
            except FileNotFoundError:
                return
            except OSError as exc:
                raise SecureFileError(f"path contains an unsafe directory: {path}") from exc
            os.close(parent)
            parent = child
        try:
            metadata = os.stat(components[-1], dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            return
        if stat.S_ISLNK(metadata.st_mode):
            raise SecureFileError(f"path contains a symlink: {path}")
    finally:
        os.close(parent)


@contextmanager
def open_regular_read(path: Path) -> Iterator[int]:
    """Open an existing regular file without following any path symlink."""
    if _uses_windows_fallback():
        _reject_windows_symlinks(path)
        ancestors = _windows_ancestor_snapshot(path)
        try:
            descriptor = os.open(path, os.O_RDONLY | _BINARY | _NOFOLLOW)
        except OSError as exc:
            raise SecureFileError(f"could not open regular file: {path}") from exc
        try:
            _verify_windows_ancestors(ancestors)
            _verify_windows_file(path, descriptor)
            yield descriptor
        finally:
            os.close(descriptor)
        return
    with _open_posix_parent(path, create=False, private=False) as (parent, name):
        try:
            # Refuse a FIFO without blocking before fstat can check its type.
            flags = os.O_RDONLY | _BINARY | _CLOEXEC | _NOFOLLOW | os.O_NONBLOCK
            descriptor = os.open(name, flags, dir_fd=parent)
        except OSError as exc:
            raise SecureFileError(f"could not open regular file: {path}") from exc
        try:
            _verify_open_file_at(parent, name, descriptor, path)
            yield descriptor
        finally:
            os.close(descriptor)


@contextmanager
def open_regular_update(path: Path, *, private: bool) -> Iterator[int]:
    """Open or create one regular file for same-descriptor read and append."""
    if _uses_windows_fallback():
        _reject_windows_symlinks(path.parent)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700 if private else 0o777)
        _reject_windows_symlinks(path)
        ancestors = _windows_ancestor_snapshot(path)
        try:
            descriptor = os.open(path, os.O_RDWR | os.O_CREAT | _BINARY | _NOFOLLOW, 0o600 if private else 0o666)
        except OSError as exc:
            raise SecureFileError(f"could not open regular file: {path}") from exc
        try:
            _verify_windows_ancestors(ancestors)
            _verify_windows_file(path, descriptor)
            yield descriptor
        finally:
            os.close(descriptor)
        return
    with _open_posix_parent(path, create=True, private=private) as (parent, name):
        flags = os.O_RDWR | os.O_CREAT | _BINARY | _CLOEXEC | _NOFOLLOW
        try:
            descriptor = os.open(name, flags, 0o600 if private else 0o666, dir_fd=parent)
        except OSError as exc:
            raise SecureFileError(f"could not open regular file: {path}") from exc
        try:
            _verify_open_file_at(parent, name, descriptor, path)
            if private:
                os.fchmod(descriptor, 0o600)
            yield descriptor
        finally:
            os.close(descriptor)


def read_bounded(descriptor: int, maximum: int) -> bytes:
    """Read from byte zero and reject content beyond ``maximum`` bytes."""
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    remaining = maximum + 1
    while remaining:
        chunk = os.read(descriptor, min(remaining, 65_536))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    value = b"".join(chunks)
    if len(value) > maximum:
        raise SecureFileError(f"regular file exceeds {maximum} bytes")
    return value


def append_bytes(descriptor: int, payload: bytes) -> None:
    """Append all bytes to an already verified descriptor and persist them."""
    os.lseek(descriptor, 0, os.SEEK_END)
    view = memoryview(payload)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise SecureFileError("regular-file append made no progress")
        view = view[written:]
    os.fsync(descriptor)
