#!/usr/bin/env python3
"""Refresh managed XNU sources from the pin, preserving unchanged file mtimes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile


def git(tree, *args):
    return subprocess.check_output(['git', '-C', str(tree), *args])


def tree_paths(tree, revision):
    # The caller's index may contain staged user additions; it is not ownership.
    return {record.split(b'\t', 1)[1].decode()
            for record in git(tree, 'ls-tree', '-rz', revision).split(b'\0') if record}


def check_parents(boundary, target):
    relative = target.relative_to(boundary)
    current = boundary
    for part in relative.parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise RuntimeError('symlink in managed source parent: ' + str(current))
        if current.exists() and not current.is_dir():
            raise RuntimeError('non-directory managed source parent: ' + str(current))


def same_file(source, target):
    if source.is_symlink():
        return target.is_symlink() and os.readlink(source) == os.readlink(target)
    return (source.is_file() and target.is_file() and not target.is_symlink()
            and source.read_bytes() == target.read_bytes()
            and stat.S_IMODE(source.stat().st_mode) == stat.S_IMODE(target.stat().st_mode))


def write_stamp(stamp, payload):
    fd, name = tempfile.mkstemp(prefix='unixnu-patchset-', dir=stamp.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(payload, stream, sort_keys=True)
            stream.write('\n')
        os.replace(name, stamp)
    finally:
        Path(name).unlink(missing_ok=True)


def prepare(root, revision):
    root = root.resolve()
    reference = root / 'refer/xnu'
    work = root / '.cache/xnu-work'
    check_parents(root, work / '.git/unixnu-patchset.json')
    if work.is_symlink() or (work / '.git').is_symlink():
        raise RuntimeError('managed source/Git directory must not be a symlink')
    if git(reference, 'rev-parse', 'HEAD').decode().strip() != revision:
        raise RuntimeError('unexpected XNU reference revision')
    patches = [*sorted((root / 'patches/xnu').glob('*.patch')),
               *sorted((root / 'kits/NativePrelink/patches').glob('*.patch'))]
    digest = hashlib.sha256(b'unixnu-xnu-patchset-v1\0' + revision.encode())
    for patch in patches:
        name = patch.relative_to(root).as_posix().encode()
        data = patch.read_bytes()
        digest.update(len(name).to_bytes(8, 'big') + name)
        digest.update(len(data).to_bytes(8, 'big') + data)
    identity = digest.hexdigest()
    # Keep the stamp outside the source file namespace and source/object mtimes.
    stamp = work / '.git/unixnu-patchset.json'
    if stamp.is_symlink() or (stamp.exists() and not stamp.is_file()):
        raise RuntimeError('invalid patchset stamp path')
    previous = json.loads(stamp.read_text()) if stamp.exists() else {}
    old_head = git(work, 'rev-parse', 'HEAD').decode().strip()
    if previous.get('identity') == identity and old_head == revision:
        return
    # Every patch must apply to the pin before touching the live work source.
    # A legacy tree without a stamp is intentionally rebuilt this same way.
    with tempfile.TemporaryDirectory(prefix='xnu-patchset-', dir=root / '.cache') as directory:
        staged = Path(directory) / 'source'
        subprocess.run(['git', 'clone', '--quiet', '--shared', '--no-checkout',
                        str(reference), str(staged)], check=True)
        git(staged, 'checkout', '--quiet', '--detach', revision)
        for patch in patches:
            git(staged, 'apply', '--index', str(patch))
        # --index applies in the disposable staged tree only. Neither ownership
        # nor safety checks use the live index.
        managed = set(git(staged, 'ls-files', '-z').decode().split('\0')) - {''}
        old_managed = set(previous.get('paths', [])) | tree_paths(work, old_head)
        if old_head != revision:
            changed_index = subprocess.run(['git', '-C', str(work), 'diff', '--cached', '--quiet'], check=False)
            if changed_index.returncode != 0:
                raise RuntimeError('cannot change XNU pin with staged work-source changes')
        # Complete preflight before changing any source, manifest, or index.
        for name in managed | old_managed:
            relative = Path(name)
            if relative.is_absolute() or not relative.parts or '..' in relative.parts or relative.parts[0] == '.git':
                raise RuntimeError('unsafe managed source path: ' + name)
            target = work / relative
            check_parents(work, target)
            exists = target.exists() or target.is_symlink()
            if exists and not (target.is_file() or target.is_symlink()):
                raise RuntimeError('non-file at managed source path: ' + name)
            if exists and name not in old_managed:
                # Pre-stamp migration may adopt an unchanged canonical addition,
                # but never guess ownership of a different existing file. This
                # preserves legitimate legacy hook files without overwriting user
                # additions. Changed legacy additions need explicit provenance.
                if previous or not same_file(staged / name, target):
                    raise RuntimeError('unowned existing canonical source collision: ' + name)
        # Retain ownership across an interrupted synchronization. Only paths
        # preflighted above are recorded, including adopted legacy additions.
        write_stamp(stamp, {'identity': None, 'paths': sorted(managed | old_managed)})
        for name in sorted(managed | old_managed):
            source, target = staged / name, work / name
            if not source.exists() and not source.is_symlink():
                if target.is_file() or target.is_symlink():
                    target.unlink()
                continue
            mode = stat.S_IMODE(source.lstat().st_mode)
            if source.is_symlink():
                if target.is_symlink() and os.readlink(target) == os.readlink(source):
                    continue
            elif target.is_file() and not target.is_symlink() and target.read_bytes() == source.read_bytes():
                if stat.S_IMODE(target.stat().st_mode) != mode:
                    target.chmod(mode)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary_name = tempfile.mkstemp(prefix='.unixnu-patch-', dir=target.parent)
            temporary = Path(temporary_name)
            try:
                if source.is_symlink():
                    os.close(fd)
                    temporary.unlink()
                    temporary.symlink_to(os.readlink(source))
                else:
                    with os.fdopen(fd, 'wb') as stream, source.open('rb') as original:
                        shutil.copyfileobj(original, stream)
                        os.fchmod(stream.fileno(), mode)
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        # Preserve an unrelated live index when the pin is unchanged. Pin
        # transitions were preflighted to require a clean index above.
        if old_head != revision:
            git(work, 'reset', '--mixed', '--quiet', revision)
        write_stamp(stamp, {'identity': identity, 'revision': revision, 'paths': sorted(managed)})
    print('Prepared canonical XNU patchset; unchanged source mtimes and build caches preserved')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--revision', required=True)
    args = parser.parse_args()
    prepare(args.root, args.revision)
