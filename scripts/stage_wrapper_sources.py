#!/usr/bin/env python3
"""Copy only tracked, regular wrapper bytes into the live-build tree."""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
import secrets
import shutil
import stat
import subprocess
import sys


def _open_output_directory(output: Path) -> int:
    """Walk a source or stage directory without following linked components."""
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for component in output.absolute().parts[1:]:
            next_fd = os.open(
                component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd
            )
            os.close(fd)
            fd = next_fd
        return fd
    except Exception:
        os.close(fd)
        raise


def _require_current_directory(path: Path, original_fd: int) -> None:
    try:
        current_fd = _open_output_directory(path)
    except OSError as exc:
        raise RuntimeError("staging directory changed during publication") from exc
    try:
        original = os.fstat(original_fd)
        current = os.fstat(current_fd)
        if (current.st_dev, current.st_ino) != (original.st_dev, original.st_ino):
            raise RuntimeError("staging directory changed during publication")
    finally:
        os.close(current_fd)


def _prepare_directory(path: Path) -> int:
    """Create a staging directory through no-follow directory descriptors."""
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for component in path.absolute().parts[1:]:
            try:
                os.mkdir(component, dir_fd=fd)
            except FileExistsError:
                pass
            next_fd = os.open(
                component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd
            )
            os.close(fd)
            fd = next_fd
        return fd
    except Exception:
        os.close(fd)
        raise


def _clear_contents(
    directory_fd: int,
    approved_files: set[tuple[str, ...]],
    prefix: tuple[str, ...] = (),
) -> None:
    """Empty only entries beneath the opened staging directory."""
    for name in os.listdir(directory_fd):
        relative = (*prefix, name)
        metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if metadata.st_uid != os.getuid():
            raise RuntimeError(f"unknown live staging content: {'/'.join(relative)}")
        if relative in approved_files and stat.S_ISREG(metadata.st_mode):
            os.unlink(name, dir_fd=directory_fd)
        elif stat.S_ISDIR(metadata.st_mode) and any(
            path[: len(relative)] == relative for path in approved_files
        ):
            child_fd = os.open(
                name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=directory_fd,
            )
            try:
                _clear_contents(child_fd, approved_files, relative)
            finally:
                os.close(child_fd)
            os.rmdir(name, dir_fd=directory_fd)
        else:
            raise RuntimeError(f"unknown live staging content: {'/'.join(relative)}")


def _validate_generated_contents(
    directory_fd: int,
    approved_files: set[tuple[str, ...]],
    prefix: tuple[str, ...] = (),
) -> None:
    """Refuse unfamiliar entries before resetting an ignored generated tree."""
    approved_directories = {
        path[:length] for path in approved_files for length in range(1, len(path))
    }
    for name in os.listdir(directory_fd):
        relative = (*prefix, name)
        metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if metadata.st_uid != os.getuid():
            raise RuntimeError(f"unknown live staging content: {'/'.join(relative)}")
        if relative in approved_files and stat.S_ISREG(metadata.st_mode):
            continue
        if relative in approved_directories and stat.S_ISDIR(metadata.st_mode):
            child_fd = os.open(
                name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=directory_fd,
            )
            try:
                _validate_generated_contents(child_fd, approved_files, relative)
            finally:
                os.close(child_fd)
            continue
        raise RuntimeError(f"unknown live staging content: {'/'.join(relative)}")


def _approved_wrapper_stage_files(live: Path) -> set[tuple[str, ...]]:
    root = live.parent.parent
    try:
        names = subprocess.check_output(
            ["git", "ls-files", "-z", "--", "src/beamo_wipe"], cwd=root
        ).split(b"\0")
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(
            "cannot identify existing wrapper stage; preserve it"
        ) from exc
    approved = set()
    for encoded in names:
        if not encoded:
            continue
        parts = PurePosixPath(os.fsdecode(encoded)).parts
        if len(parts) < 3 or parts[:2] != ("src", "beamo_wipe") or ".." in parts:
            raise RuntimeError("invalid tracked wrapper source path")
        if "__pycache__" not in parts and PurePosixPath(parts[-1]).suffix not in {
            ".pyc",
            ".pyo",
        }:
            approved.add(parts[2:])
    return approved


def prepare_live_stage(live: Path) -> None:
    """Reset generated includes without traversing a linked parent."""
    clear = {
        "config/includes.chroot/usr/lib/python3/dist-packages/beamo_wipe": None,
        "config/includes.chroot/usr/share/beamo-wipe": {
            ("build-identity.json",),
            ("helper", "index.html"),
            ("helper", "fr.html"),
            ("helper", "de.html"),
            ("sounds", "finished.wav"),
            ("sounds", "attention.wav"),
        },
        "config/includes.chroot/usr/share/doc/beamo-wipe": {
            ("NOTICE",),
            ("LICENSE",),
            ("THIRD_PARTY.md",),
            ("SOURCE.txt",),
        },
    }
    ensure = (
        "config/includes.chroot/usr/share/beamo-wipe/helper",
        "config/includes.chroot/usr/share/beamo-wipe/sounds",
        "config/includes.binary",
        "config/includes.chroot/usr/local/bin",
    )
    # `lb config` rewrites these ignored files inside the build container. An
    # existing path might also contain untracked user work, so refuse it rather
    # than silently deleting it or copying it into the new ISO.
    generated_config = (
        "config/binary",
        "config/bootstrap",
        "config/chroot",
        "config/common",
        "config/source",
        "config/package-lists/live.list.chroot",
    )
    for relative in generated_config:
        path = live / relative
        try:
            parent_fd = _open_output_directory(path.parent)
        except FileNotFoundError:
            continue
        try:
            try:
                os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            raise RuntimeError(
                f"existing live-build config requires deliberate cleanup: {relative}"
            )
        finally:
            os.close(parent_fd)
    # Validate every tree before removing a known generated file, so an
    # unfamiliar ignored file cannot be lost by partial preparation.
    clear_fds = []
    try:
        for relative, approved in clear.items():
            directory_fd = _prepare_directory(live / relative)
            try:
                if approved is None:
                    approved = _approved_wrapper_stage_files(live)
            except Exception:
                os.close(directory_fd)
                raise
            clear_fds.append((directory_fd, approved))
            _validate_generated_contents(directory_fd, approved)
        for directory_fd, approved in clear_fds:
            _clear_contents(directory_fd, approved)
    finally:
        for directory_fd, _ in clear_fds:
            os.close(directory_fd)
    for relative in ensure:
        os.close(_prepare_directory(live / relative))
    binary_fd = _open_output_directory(live / "config/includes.binary")
    try:
        generated = {
            "START-HERE.html",
            "build-identity.json",
            "README.txt",
            "NOTICE",
            "LICENSE",
            "SOURCE.txt",
            "Start Beamo Wipe.exe",
            "Start Beamo Wipe Linux",
            "desktop-build.json",
            "GO-LICENSE.txt",
            "GO-PATENTS.txt",
        }
        for name in os.listdir(binary_fd):
            metadata = os.stat(name, dir_fd=binary_fd, follow_symlinks=False)
            if name not in generated or not stat.S_ISREG(metadata.st_mode):
                raise RuntimeError(f"unsafe binary include: {name}")
    finally:
        os.close(binary_fd)


def read_regular_file(
    path: Path, *, limit: int = 64 * 1024 * 1024
) -> tuple[bytes, int]:
    """Read a regular input through its no-follow parent descriptor."""
    parent_fd = _open_output_directory(path.parent)
    try:
        fd = os.open(
            path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd
        )
        with os.fdopen(fd, "rb") as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                raise RuntimeError(f"unsafe staged input: {path.name}")
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise RuntimeError(f"staged input exceeds size limit: {path.name}")
        return data, stat.S_IMODE(metadata.st_mode)
    finally:
        os.close(parent_fd)


def read_regular_bytes(path: Path, *, limit: int = 64 * 1024 * 1024) -> bytes:
    return read_regular_file(path, limit=limit)[0]


def install_bytes(destination: Path, data: bytes, *, executable: bool = False) -> None:
    """Replace a generated include without following a linked parent or leaf."""
    parent_fd = _open_output_directory(destination.parent)
    temporary = f".beamo-stage-{secrets.token_hex(16)}"
    fd = None
    owned = None
    try:
        fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=parent_fd,
        )
        owned = os.fstat(fd)
        with os.fdopen(fd, "wb") as stream:
            fd = None
            stream.write(data)
            os.fchmod(stream.fileno(), 0o755 if executable else 0o644)
        os.replace(
            temporary, destination.name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd
        )
        published_fd = os.open(
            destination.name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=parent_fd,
        )
        with os.fdopen(published_fd, "rb") as published:
            if (
                not stat.S_ISREG(os.fstat(published.fileno()).st_mode)
                or published.read(len(data) + 1) != data
            ):
                raise RuntimeError("staged include bytes changed during publication")
        _require_current_directory(destination.parent, parent_fd)
    except Exception:
        if fd is not None:
            os.close(fd)
        try:
            current = os.stat(temporary, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            if owned is not None and (current.st_dev, current.st_ino) == (
                owned.st_dev,
                owned.st_ino,
            ):
                os.unlink(temporary, dir_fd=parent_fd)
        raise
    finally:
        os.close(parent_fd)


def install_file(source: Path, destination: Path) -> None:
    data, mode = read_regular_file(source)
    install_bytes(destination, data, executable=bool(mode & 0o111))


def require_executable(path: Path) -> None:
    """Set executable mode only on the opened regular live entrypoint."""
    parent_fd = _open_output_directory(path.parent)
    try:
        fd = os.open(
            path.name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=parent_fd,
        )
        with os.fdopen(fd, "rb") as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode) or not metadata.st_mode & 0o111:
                raise RuntimeError("live entrypoint is missing or not executable")
            os.fchmod(stream.fileno(), stat.S_IMODE(metadata.st_mode) | 0o111)
        _require_current_directory(path.parent, parent_fd)
    finally:
        os.close(parent_fd)


def require_approved_hook(live: Path) -> None:
    """Reject unexpected hooks in both live-build hook directories."""
    hook_dir = live / "config/hooks/normal"
    approved = "0500-build-nwipe.hook.chroot"
    directory_fd = _open_output_directory(hook_dir)
    try:
        # live-build executes several hook suffixes here, including .binary
        # and any .chroot. The source-controlled nwipe hook is the only
        # approved entry in this directory.
        hooks = os.listdir(directory_fd)
        if hooks != [approved]:
            raise RuntimeError("unapproved live-build hook")
        metadata = os.stat(approved, dir_fd=directory_fd, follow_symlinks=False)
        if not stat.S_ISREG(metadata.st_mode):
            raise RuntimeError("unapproved live-build hook")
    finally:
        os.close(directory_fd)
    require_executable(hook_dir / approved)

    # Git ignores config/hooks/live because lb config generates links to the
    # installed Debian live-build hooks there. live-build also executes any
    # regular .hook.chroot left in that directory, so a clean git status is
    # not sufficient to approve its contents.
    generated_dir = live / "config/hooks/live"
    try:
        generated_fd = _open_output_directory(generated_dir)
    except FileNotFoundError:
        return  # Fresh checkouts have no generated hooks yet.
    try:
        generated_names = frozenset(
            {
                "0010-disable-kexec-tools.hook.chroot",
                "0050-disable-sysvinit-tmpfs.hook.chroot",
            }
        )
        for name in os.listdir(generated_fd):
            if name not in generated_names:
                raise RuntimeError("unapproved live-build hook")
            metadata = os.stat(name, dir_fd=generated_fd, follow_symlinks=False)
            if not stat.S_ISLNK(metadata.st_mode):
                raise RuntimeError("unapproved live-build hook")
            target = os.readlink(name, dir_fd=generated_fd)
            if target not in (
                f"/usr/share/live/build/hooks/{name}",
                f"/usr/share/live/build/hooks/live/{name}",
            ):
                raise RuntimeError("unapproved live-build hook")
    finally:
        os.close(generated_fd)


def _stage_file(output_fd: int, parts: tuple[str, ...], source) -> None:
    directory_fd = os.dup(output_fd)
    try:
        for component in parts[2:-1]:
            try:
                os.mkdir(component, dir_fd=directory_fd)
            except FileExistsError:
                pass
            next_fd = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=directory_fd,
            )
            os.close(directory_fd)
            directory_fd = next_fd
        staged_fd = os.open(
            parts[-1],
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o666,
            dir_fd=directory_fd,
        )
        with os.fdopen(staged_fd, "wb") as staged:
            shutil.copyfileobj(source, staged)
    finally:
        os.close(directory_fd)


def stage(root: Path, output: Path) -> None:
    names = subprocess.check_output(
        ["git", "ls-files", "-z", "--", "src/beamo_wipe"], cwd=root
    ).split(b"\0")
    entries = [name for name in names if name]
    if not entries:
        raise RuntimeError("no tracked wrapper source files")
    output_fd = _open_output_directory(output)
    try:
        for encoded in entries:
            relative = PurePosixPath(os.fsdecode(encoded))
            parts = relative.parts
            if len(parts) < 3 or parts[:2] != ("src", "beamo_wipe") or ".." in parts:
                raise RuntimeError("invalid tracked wrapper source path")
            if relative.suffix in {".pyc", ".pyo"} or "__pycache__" in parts:
                continue
            directory_fd = _open_output_directory(root)
            try:
                for component in parts[:-1]:
                    next_fd = os.open(
                        component,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                        dir_fd=directory_fd,
                    )
                    os.close(directory_fd)
                    directory_fd = next_fd
                source_fd = os.open(
                    parts[-1],
                    os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                    dir_fd=directory_fd,
                )
                with os.fdopen(source_fd, "rb") as source:
                    if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                        raise RuntimeError(
                            "tracked wrapper source is not a regular file"
                        )
                    _stage_file(output_fd, parts, source)
            except OSError as exc:
                raise RuntimeError(
                    f"tracked wrapper source or destination is unsafe: {relative}"
                ) from exc
            finally:
                os.close(directory_fd)
    finally:
        os.close(output_fd)


def main() -> int:
    try:
        if len(sys.argv) != 3:
            raise RuntimeError("expected source and output paths")
        if sys.argv[1] == "--prepare":
            prepare_live_stage(Path(sys.argv[2]))
        else:
            stage(Path(sys.argv[1]), Path(sys.argv[2]))
    except (IndexError, OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"wrapper staging failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
