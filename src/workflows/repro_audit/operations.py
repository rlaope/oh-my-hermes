"""Local import-only command line. No model execution or network access."""
import ctypes
import errno
import hashlib
import json
import os
import stat
import sys
import uuid
from pathlib import Path
from .core import template_case, load_case, compare_case, ValidationError
from .render import render_report
from .core import MAX_FILE_BYTES
from .importer import import_harness


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                      allow_nan=False).encode('utf-8')


class _SafetyError(Exception):
    """No offending user data is included in this exception."""


def _path(value):
    # Do not collapse '..' past an unseen symlink. './case' remains supported.
    if not value or '\x00' in value or '..' in Path(value).parts:
        raise _SafetyError()
    return Path(os.path.abspath(value))


def _open_directory(path):
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except OSError as error:
        os.close(fd)
        if error.errno in (errno.ELOOP, errno.ENOTDIR):
            raise _SafetyError() from None
        raise


def _identity(fd):
    info = os.fstat(fd)
    return info.st_dev, info.st_ino


def _same_entry(parent, name, identity):
    try:
        info = os.stat(name, dir_fd=parent, follow_symlinks=False)
        return stat.S_ISDIR(info.st_mode) and (info.st_dev, info.st_ino) == identity
    except FileNotFoundError:
        return False


def _check_parent(path, fd):
    other = _open_directory(path)
    try:
        if _identity(other) != _identity(fd):
            raise _SafetyError()
    finally:
        os.close(other)


def _rename_noreplace(parent, source, target):
    """Native exclusive directory rename; never emulate with exists()+rename().

    macOS RENAME_EXCL and Linux RENAME_NOREPLACE protect even a late empty
    directory/symlink. Unsupported systems fail closed rather than overwrite.
    """
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == 'darwin':
        operation = getattr(libc, 'renameatx_np', None)
        flags = 4  # RENAME_EXCL
    elif sys.platform.startswith('linux'):
        operation = getattr(libc, 'renameat2', None)
        flags = 1  # RENAME_NOREPLACE
    else:
        operation = None
        flags = 0
    if operation is None:
        raise OSError(errno.ENOTSUP, 'exclusive publication unavailable')
    operation.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    operation.restype = ctypes.c_int
    if operation(parent, os.fsencode(source), parent, os.fsencode(target), flags) != 0:
        code = ctypes.get_errno()
        if code in (errno.EEXIST, errno.ENOTEMPTY):
            raise _SafetyError()
        raise OSError(code, 'publication failed')


def _publish(out, files, directories=()):
    """Publish prepared bytes as one new directory; pin all traversal with FDs.

    Rollback removes only files created in our private staging inode. A changed
    target/parent is never followed or recursively removed. No input is opened
    for writing. Atomic visibility is not a power-loss durability guarantee.
    """
    root = _path(out)
    if root == root.parent:
        raise _SafetyError()
    parent = _open_directory(root.parent)
    stage = '.omh-repro-audit-' + uuid.uuid4().hex
    stage_fd = None
    owned = None
    published = False
    created_files, created_dirs = [], []
    try:
        try:
            os.stat(root.name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise _SafetyError()
        os.mkdir(stage, mode=0o700, dir_fd=parent)
        info = os.stat(stage, dir_fd=parent, follow_symlinks=False)
        owned = (info.st_dev, info.st_ino)
        stage_fd = os.open(stage, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        if _identity(stage_fd) != owned:
            raise _SafetyError()
        for name in directories:
            os.mkdir(name, mode=0o700, dir_fd=stage_fd)
            created_dirs.append(name)
        for name, data in files.items():
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=stage_fd)
            created_files.append(name)
            try:
                remaining = memoryview(data)
                while remaining:
                    count = os.write(fd, remaining)
                    if count <= 0:
                        raise OSError(errno.EIO, 'short output write')
                    remaining = remaining[count:]
                os.fsync(fd)
            finally:
                os.close(fd)
        os.fsync(stage_fd)
        _check_parent(root.parent, parent)
        if not _same_entry(parent, stage, owned):
            raise _SafetyError()
        _rename_noreplace(parent, stage, root.name)
        published = True
        os.fsync(parent)
        _check_parent(root.parent, parent)
        if not _same_entry(parent, root.name, owned):
            raise _SafetyError()
    except BaseException:
        if stage_fd is not None:
            # Remove normal-summary files first if publication had succeeded.
            for name in created_files:
                try:
                    os.unlink(name, dir_fd=stage_fd)
                except FileNotFoundError:
                    pass
            for name in created_dirs:
                os.rmdir(name, dir_fd=stage_fd)
            name = root.name if published else stage
            if _same_entry(parent, name, owned):
                os.rmdir(name, dir_fd=parent)
        if stage_fd is None and owned is not None and _same_entry(parent, stage, owned):
            os.rmdir(stage, dir_fd=parent)
        raise
    finally:
        if stage_fd is not None:
            os.close(stage_fd)
        os.close(parent)


def supported_platform():
    return (sys.platform == 'darwin' or sys.platform.startswith('linux')) and all(
        hasattr(os, name) for name in ('O_DIRECTORY', 'O_NOFOLLOW', 'O_NONBLOCK'))


def run(args):
    if not supported_platform():
        print('omh paper audit: unsupported platform; safe audit filesystem requires macOS or Linux', file=sys.stderr)
        return 2
    try:
        if args.command == 'audit':
            # Lexical overlap check does not follow or open any input path.
            case_root, out_root = Path(os.path.abspath(args.case)), _path(args.out)
            if case_root == out_root or case_root in out_root.parents:
                raise _SafetyError()
        if args.command == 'import-harness':
            try:
                source = _path(args.results)
                parent = _open_directory(source.parent)
                try:
                    fd = os.open(source.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
                finally:
                    os.close(parent)
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    os.close(fd)
                    raise _SafetyError()
                with os.fdopen(fd, 'rb') as handle:
                    raw = handle.read(MAX_FILE_BYTES + 1)
                if len(raw) > MAX_FILE_BYTES:
                    raise ValidationError([{'code': 'input_limit_exceeded', 'pointer': '/results'}])
                files = import_harness(raw, args.metric)
            except OSError as error:
                if error.errno in (errno.ELOOP, errno.ENOTDIR):
                    raise _SafetyError() from None
                raise
            except ValidationError as error:
                _publish(args.out, {'validation.json': _json({'status': 'rejected', 'errors': error.errors, 'input_digest': None})})
                print('omh paper audit: input rejected; see validation.json', file=sys.stderr)
                return 2
            _publish(args.out, files, ('artifacts',))
            print('omh paper audit: Harness source claims imported; operator review pending; no model execution')
            return 0
        if args.command == 'init':
            templates = template_case('case-001')
            if args.metric == 'acc_norm':
                templates['case.json']['profile_id'] = 'hellaswag-acc-norm-audit-v0.2'
            files = {name: _json(value) for name, value in templates.items()}
            _publish(args.out, files, ('artifacts',))
        else:
            try:
                try:
                    _path(args.case)
                except _SafetyError:
                    raise ValidationError([{'code': 'unsafe_path', 'pointer': '/case'}]) from None
                bundle = load_case(args.case)
            except ValidationError as error:
                _publish(args.out, {'validation.json': _json({'status': 'rejected',
                         'errors': error.errors, 'input_digest': error.input_digest})})
                print('omh paper audit: input rejected; see validation.json', file=sys.stderr)
                return 2
            report = compare_case(bundle)
            inputs = {k: bundle[k] for k in ('case', 'reported', 'actual', 'evidence')}
            files = {'validation.json': _json({'status': 'accepted', 'errors': [], 'input_digest': report['input_digest']}),
                     'report.json': _json(report), 'inputs.canonical.json': _json(inputs),
                     'report.html': render_report(report, inputs).encode('utf-8')}
            files['artifact-index.json'] = _json({'artifacts': [
                {'path': name, 'size_bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                for name, data in sorted(files.items())]})
            _publish(args.out, files)
    except _SafetyError:
        print('omh paper audit: unsafe or existing output/input path; nothing overwritten', file=sys.stderr)
        return 2
    except OSError:
        print('omh paper audit: I/O failure; no audit completed', file=sys.stderr)
        return 3
    print('omh paper audit: unknown templates created' if args.command == 'init' else 'omh paper audit: accepted audit created; scientific verdict not assessed')
    return 0
