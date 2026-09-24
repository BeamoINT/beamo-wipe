#!/usr/bin/env python3
"""Build portable launchers without a shell, device discovery, or reboot."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
GO_VERSION = "go1.26.8"
LAUNCHERS = ("Start Beamo Wipe.exe", "Start Beamo Wipe Linux")


def _unique_manifest_fields(pairs):
    fields = {}
    for key, value in pairs:
        if key in fields:
            raise RuntimeError("duplicate JSON field in desktop launcher manifest")
        fields[key] = value
    return fields


def _require_output_directory(output: Path, *, create: bool = False) -> int | None:
    """Walk every output component without following a linked parent."""
    if os.name != "posix":
        absolute = output.absolute()
        for component in (*reversed(absolute.parents), absolute):
            try:
                metadata = component.lstat()
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    component.mkdir()
                except FileExistsError:
                    pass
                metadata = component.lstat()
            if not stat.S_ISDIR(metadata.st_mode) or (
                getattr(metadata, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            ):
                raise RuntimeError("unsafe desktop output directory")
        return None
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        directory_fd = os.open("/", flags)
        try:
            for component in output.absolute().parts[1:]:
                if create:
                    try:
                        os.mkdir(component, dir_fd=directory_fd)
                    except FileExistsError:
                        pass
                next_fd = os.open(component, flags, dir_fd=directory_fd)
                os.close(directory_fd)
                directory_fd = next_fd
            if os.fstat(directory_fd).st_uid != os.getuid():
                raise RuntimeError("unsafe desktop output directory")
            return directory_fd
        except Exception:
            os.close(directory_fd)
            raise
    except OSError as exc:
        raise RuntimeError("unsafe desktop output directory") from exc


def desktop_source_digest(root: Path) -> str:
    """Bind cached launcher bytes to every local Go and embedded-web input."""
    desktop = root / "desktop"
    source_files = [
        desktop / "go.mod",
        *desktop.glob("*.go"),
        *desktop.joinpath("web").rglob("*"),
    ]
    go_sum = desktop / "go.sum"
    if go_sum.exists() or go_sum.is_symlink():
        source_files.append(go_sum)
    for path in source_files:
        if path.is_symlink():
            raise RuntimeError("desktop source input is a symlink")
    paths = sorted(
        (path for path in source_files if not path.is_dir()),
        key=lambda path: path.relative_to(root).as_posix(),
    )
    if not (desktop / "go.mod").is_file() or not any(
        path.suffix == ".go" for path in paths
    ):
        raise RuntimeError("desktop source inputs are missing")
    digest = hashlib.sha256()
    for path in paths:
        if path.is_symlink() or not path.is_file():
            raise RuntimeError("desktop source input is not a regular file")
        relative = path.relative_to(root).as_posix().encode("utf-8")
        data = path.read_bytes()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def _read_output_file(
    output: Path, output_fd: int | None, name: str, limit: int
) -> bytes:
    """Read one regular cached artifact without following a link or FIFO."""
    if output_fd is None:
        path = output / name
        if not path.is_file() or path.is_symlink() or path.stat().st_size > limit:
            raise OSError("unsafe desktop output file")
        return path.read_bytes()
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=output_fd)
    with os.fdopen(fd, "rb") as stream:
        metadata = os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
            raise OSError("unsafe desktop output file")
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise OSError("desktop output file exceeded size limit")
    return data


def verify_desktop_bundle(
    root: Path, output: Path, source: str, version: str, dirty: bool
) -> None:
    """Reject a cached launcher pair built from another source state."""
    output_fd = _require_output_directory(output)
    try:
        try:
            manifest = json.loads(
                _read_output_file(output, output_fd, "desktop-build.json", 16 * 1024),
                object_pairs_hook=_unique_manifest_fields,
            )
        except (OSError, ValueError, RecursionError) as exc:
            raise RuntimeError(
                "desktop launcher manifest is missing or invalid; rebuild launchers"
            ) from exc
        if not isinstance(manifest, dict) or manifest.get("source_commit") != source:
            raise RuntimeError(
                "desktop launchers are from a different source commit; rebuild them"
            )
        if manifest.get("source_sha256") != desktop_source_digest(root):
            raise RuntimeError(
                "desktop launchers are from different desktop source inputs; rebuild them"
            )
        if (
            manifest.get("version") != version
            or manifest.get("source_dirty") is not dirty
        ):
            raise RuntimeError(
                "desktop launcher version or source status changed; rebuild them"
            )
        if (
            manifest.get("go") != GO_VERSION
            or not isinstance(manifest.get("files"), dict)
            or set(manifest["files"]) != set(LAUNCHERS)
        ):
            raise RuntimeError(
                "desktop launcher manifest does not match the required build; rebuild launchers"
            )
        for name in LAUNCHERS:
            try:
                digest = hashlib.sha256(
                    _read_output_file(output, output_fd, name, 64 * 1024 * 1024)
                ).hexdigest()
            except OSError as exc:
                raise RuntimeError(
                    "desktop launcher checksum mismatch; rebuild launchers"
                ) from exc
            if digest != manifest["files"][name]:
                raise RuntimeError(
                    "desktop launcher checksum mismatch; rebuild launchers"
                )
    finally:
        if output_fd is not None:
            os.close(output_fd)


def _publish_launcher(
    output: Path, output_fd: int | None, source: Path, name: str
) -> None:
    """Replace one launcher in the originally opened output directory."""
    if source.is_symlink() or not source.is_file():
        raise RuntimeError("desktop compiler did not write a regular launcher")
    if output_fd is None:
        temporary_path = output / f".launcher-{secrets.token_hex(16)}"
        owned = None
        try:
            with temporary_path.open("xb") as dest:
                owned = os.fstat(dest.fileno())
                with source.open("rb") as src:
                    shutil.copyfileobj(src, dest)
            os.replace(temporary_path, output / name)
        except Exception:
            try:
                current = temporary_path.lstat()
            except FileNotFoundError:
                pass
            else:
                if (
                    owned is not None
                    and stat.S_ISREG(current.st_mode)
                    and (
                        current.st_dev,
                        current.st_ino,
                    )
                    == (owned.st_dev, owned.st_ino)
                ):
                    temporary_path.unlink()
            raise
        return
    temporary = f".launcher-{secrets.token_hex(16)}"
    fd = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
        dir_fd=output_fd,
    )
    owned = os.fstat(fd)
    try:
        with os.fdopen(fd, "wb") as dest, source.open("rb") as src:
            shutil.copyfileobj(src, dest)
            os.fchmod(dest.fileno(), 0o755)
        os.replace(temporary, name, src_dir_fd=output_fd, dst_dir_fd=output_fd)
    except Exception:
        try:
            current = os.stat(temporary, dir_fd=output_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            if stat.S_ISREG(current.st_mode) and (current.st_dev, current.st_ino) == (
                owned.st_dev,
                owned.st_ino,
            ):
                os.unlink(temporary, dir_fd=output_fd)
        raise


def build(output=None):
    go = os.environ.get("BEAMO_GO_BIN", "go")
    env = os.environ.copy()
    env.update(CGO_ENABLED="0", GOTOOLCHAIN="local")
    version_line = subprocess.check_output([go, "version"], text=True, env=env).split()
    if len(version_line) < 3 or version_line[2] != GO_VERSION:
        raise RuntimeError(
            "Launcher builds require Go 1.26.8 (see scripts/ci-desktop.sh)."
        )
    sys.path.insert(0, str(ROOT / "src"))
    from beamo_wipe import __version__

    source = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    dirty = bool(
        subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=ROOT, text=True
        ).strip()
    )
    output = Path(output) if output is not None else ROOT / "dist" / "desktop"
    output_fd = _require_output_directory(output, create=True)
    lock = output / ".build.lock"
    try:
        if output_fd is None:
            lock_fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        else:
            lock_fd = os.open(
                ".build.lock",
                os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                0o600,
                dir_fd=output_fd,
            )
    except FileExistsError as exc:
        if output_fd is not None:
            os.close(output_fd)
        raise RuntimeError(
            "Another desktop build owns this output. Wait for it to finish; see docs/development.md for interrupted builds."
        ) from exc
    except Exception:
        if output_fd is not None:
            os.close(output_fd)
        raise

    def owns_lock_inode() -> bool:
        owned = os.fstat(lock_fd)
        try:
            if output_fd is None:
                current = lock.lstat()
            else:
                current = os.stat(
                    ".build.lock", dir_fd=output_fd, follow_symlinks=False
                )
        except OSError:
            return False
        return stat.S_ISREG(current.st_mode) and (current.st_dev, current.st_ino) == (
            owned.st_dev,
            owned.st_ino,
        )

    def owns_lock() -> bool:
        if not owns_lock_inode():
            return False
        try:
            current_output_fd = _require_output_directory(output)
        except (OSError, RuntimeError):
            return False
        if output_fd is None or current_output_fd is None:
            return True
        try:
            current = os.fstat(current_output_fd)
            original = os.fstat(output_fd)
            return (current.st_dev, current.st_ino) == (
                original.st_dev,
                original.st_ino,
            )
        finally:
            os.close(current_output_fd)

    try:
        manifest = output / "desktop-build.json"
        # A failed rebuild must not leave an earlier success receipt beside partial outputs.
        if output_fd is None:
            manifest.unlink(missing_ok=True)
        else:
            try:
                os.unlink(manifest.name, dir_fd=output_fd)
            except FileNotFoundError:
                pass
        source_digest = desktop_source_digest(ROOT)
        flags = f"-s -w -X main.version={__version__} -X main.sourceCommit={source} -X main.sourceDirty={str(dirty).lower()}"
        files = {}
        with tempfile.TemporaryDirectory(prefix="beamo-desktop-build-") as staged_dir:
            staged = Path(staged_dir)
            for host, name in (
                ("linux", "Start Beamo Wipe Linux"),
                ("windows", "Start Beamo Wipe.exe"),
            ):
                if not owns_lock():
                    raise RuntimeError(
                        "desktop build lock changed during launcher build"
                    )
                target = staged / name
                subprocess.check_call(
                    [
                        go,
                        "build",
                        "-trimpath",
                        "-buildvcs=false",
                        "-ldflags",
                        flags + (" -H=windowsgui" if host == "windows" else ""),
                        "-o",
                        str(target),
                        ".",
                    ],
                    cwd=ROOT / "desktop",
                    env={**env, "GOOS": host, "GOARCH": "amd64"},
                )
                if not owns_lock():
                    raise RuntimeError(
                        "desktop build lock changed during launcher build"
                    )
                if target.is_symlink() or not target.is_file():
                    raise RuntimeError(
                        "desktop compiler did not write a regular launcher"
                    )
                files[name] = hashlib.sha256(target.read_bytes()).hexdigest()
            if desktop_source_digest(ROOT) != source_digest:
                raise RuntimeError(
                    "desktop source inputs changed during launcher build"
                )
            if not owns_lock():
                raise RuntimeError(
                    "desktop build lock changed before manifest publication"
                )
            for name in LAUNCHERS:
                _publish_launcher(output, output_fd, staged / name, name)
            for name in LAUNCHERS:
                try:
                    published_sha = hashlib.sha256(
                        _read_output_file(output, output_fd, name, 64 * 1024 * 1024)
                    ).hexdigest()
                except OSError as exc:
                    raise RuntimeError(
                        "desktop launcher bytes changed during publication"
                    ) from exc
                if published_sha != files[name]:
                    raise RuntimeError(
                        "desktop launcher bytes changed during publication"
                    )
        if desktop_source_digest(ROOT) != source_digest:
            raise RuntimeError("desktop source inputs changed during launcher build")
        if not owns_lock():
            raise RuntimeError("desktop build lock changed before manifest publication")
        manifest_bytes = (
            json.dumps(
                {
                    "version": __version__,
                    "source_commit": source,
                    "source_sha256": source_digest,
                    "source_dirty": dirty,
                    "go": GO_VERSION,
                    "files": files,
                },
                sort_keys=True,
                indent=2,
            )
            + "\n"
        )
        manifest_owned = None
        try:
            if output_fd is None:
                with manifest.open("x", encoding="utf-8") as stream:
                    stream.write(manifest_bytes)
            else:
                manifest_fd = os.open(
                    manifest.name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o644,
                    dir_fd=output_fd,
                )
                manifest_owned = os.fstat(manifest_fd)
                with os.fdopen(manifest_fd, "w", encoding="utf-8") as stream:
                    stream.write(manifest_bytes)
        except FileExistsError as exc:
            raise RuntimeError(
                "desktop manifest path appeared during launcher build"
            ) from exc
        if not owns_lock():
            if output_fd is not None and manifest_owned is not None:
                try:
                    current = os.stat(
                        manifest.name, dir_fd=output_fd, follow_symlinks=False
                    )
                except FileNotFoundError:
                    pass
                else:
                    if (current.st_dev, current.st_ino) == (
                        manifest_owned.st_dev,
                        manifest_owned.st_ino,
                    ):
                        os.unlink(manifest.name, dir_fd=output_fd)
            raise RuntimeError("desktop output changed before completion")
        print(
            "Built Windows and Linux desktop launchers. Runtime and firmware tests remain separate gates."
        )
    finally:
        try:
            if owns_lock_inode():
                if output_fd is None:
                    lock.unlink()
                else:
                    os.unlink(".build.lock", dir_fd=output_fd)
        finally:
            os.close(lock_fd)
            if output_fd is not None:
                os.close(output_fd)


if __name__ == "__main__":
    try:
        build()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
