#!/usr/bin/env python3
"""Build portable launchers without a shell, device discovery, or reboot."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
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


def _read_regular_source(path: Path) -> bytes:
    """Read one compiler input from a regular inode still named by its path."""
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode):
            raise RuntimeError("desktop source input changed or unsafe")
        flags = (
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        )
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode) or (before.st_dev, before.st_ino) != (
                opened.st_dev,
                opened.st_ino,
            ):
                raise RuntimeError("desktop source input changed or unsafe")
            data = stream.read()
            after = os.fstat(stream.fileno())
        named = path.lstat()
    except OSError as exc:
        raise RuntimeError("desktop source input changed or unsafe") from exc

    def identity(info):
        return (
            info.st_dev,
            info.st_ino,
            info.st_size,
            info.st_mtime_ns,
            info.st_ctime_ns,
        )

    if (
        not stat.S_ISREG(named.st_mode)
        or not (
            identity(before) == identity(opened) == identity(after) == identity(named)
        )
        or len(data) != opened.st_size
    ):
        raise RuntimeError("desktop source input changed or unsafe")
    return data


def desktop_source_digest(root: Path) -> str:
    """Bind cached launcher bytes to the Go inputs and their build recipe."""
    desktop = root / "desktop"
    if desktop.is_symlink() or not desktop.is_dir():
        raise RuntimeError("desktop source directory is missing or linked")
    # Go can compile assembly and link .syso objects alongside .go files. It
    # may also select files from a vendor tree, so an extension allowlist would
    # let a cached launcher verify against changed compiler inputs.
    source_files = list(desktop.rglob("*"))
    regular_files = []
    for path in source_files:
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise RuntimeError("desktop source input is a symlink")
        if stat.S_ISREG(mode):
            regular_files.append(path)
        elif not stat.S_ISDIR(mode):
            raise RuntimeError("desktop source input is not a regular file")
    paths = sorted(
        regular_files,
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
        data = _read_regular_source(path)
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    recipe = Path(__file__)
    if not stat.S_ISREG(recipe.lstat().st_mode):
        raise RuntimeError("desktop build recipe is not a regular file")
    recipe_data = _read_regular_source(recipe)
    recipe_name = b"scripts/build_desktop.py"
    digest.update(len(recipe_name).to_bytes(4, "big"))
    digest.update(recipe_name)
    digest.update(len(recipe_data).to_bytes(8, "big"))
    digest.update(recipe_data)
    return digest.hexdigest()


def _snapshot_desktop_source(root: Path, staged_root: Path, expected: str) -> Path:
    """Give Go a private source copy whose digest matches the receipt."""
    source = root / "desktop"
    destination = staged_root / "desktop"
    destination.mkdir(parents=True)
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        staged = destination / relative
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            staged.mkdir()
        elif stat.S_ISREG(mode):
            staged.parent.mkdir(parents=True, exist_ok=True)
            with staged.open("xb") as output:
                output.write(_read_regular_source(path))
        else:
            raise RuntimeError("desktop source input changed or unsafe")
    if desktop_source_digest(staged_root) != expected:
        raise RuntimeError("desktop source inputs changed during staging")
    return destination


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


def _require_generated_prior_manifest(output: Path, output_fd: int | None) -> None:
    """Preserve unfamiliar content at the receipt path during a rebuild."""
    name = "desktop-build.json"
    try:
        if output_fd is None:
            metadata = (output / name).lstat()
        else:
            metadata = os.stat(name, dir_fd=output_fd, follow_symlinks=False)
    except FileNotFoundError:
        # Without a receipt, even a correctly named launcher is unidentified.
        # A failed earlier build may have left partial output; preserve it for
        # deliberate inspection instead of replacing it on the next retry.
        for launcher in LAUNCHERS:
            try:
                if output_fd is None:
                    (output / launcher).lstat()
                else:
                    os.stat(launcher, dir_fd=output_fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            raise RuntimeError(
                "unrecognized desktop launcher without a manifest; preserve existing output"
            )
        return
    if not stat.S_ISREG(metadata.st_mode):
        raise RuntimeError("unrecognized desktop manifest; preserve existing output")
    try:
        manifest = json.loads(
            _read_output_file(output, output_fd, name, 16 * 1024),
            object_pairs_hook=_unique_manifest_fields,
        )
    except (OSError, ValueError, RuntimeError, RecursionError) as exc:
        raise RuntimeError(
            "unrecognized desktop manifest; preserve existing output"
        ) from exc
    if (
        not isinstance(manifest, dict)
        or set(manifest)
        != {"version", "source_commit", "source_sha256", "source_dirty", "go", "files"}
        or not isinstance(manifest["version"], str)
        or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", manifest["version"])
        or not isinstance(manifest["source_commit"], str)
        or not re.fullmatch(r"[0-9a-f]{40}", manifest["source_commit"])
        or not isinstance(manifest["source_sha256"], str)
        or not re.fullmatch(r"[0-9a-f]{64}", manifest["source_sha256"])
        or type(manifest["source_dirty"]) is not bool
        or not isinstance(manifest["go"], str)
        or not isinstance(manifest["files"], dict)
        or set(manifest["files"]) != set(LAUNCHERS)
        or any(
            not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
            for value in manifest["files"].values()
        )
    ):
        raise RuntimeError("unrecognized desktop manifest; preserve existing output")
    # A well-shaped JSON receipt alone does not establish ownership of the
    # launcher paths. If either file was replaced (or the earlier bundle was
    # incomplete), preserve the contents instead of overwriting them.
    for launcher in LAUNCHERS:
        try:
            existing = _read_output_file(output, output_fd, launcher, 64 * 1024 * 1024)
        except OSError as exc:
            raise RuntimeError(
                "unrecognized desktop manifest; preserve existing output"
            ) from exc
        if hashlib.sha256(existing).hexdigest() != manifest["files"][launcher]:
            raise RuntimeError(
                "unrecognized desktop manifest; preserve existing output"
            )


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
    # Let the selected Go binary locate its own standard library and tools.
    env.pop("GOROOT", None)
    # These Go settings can replace source files, select a separate workspace,
    # or emit binaries that require newer x86 CPUs. None is covered by the
    # desktop source digest, so pin them for both portable launchers.
    env.update(
        CGO_ENABLED="0",
        GOTOOLCHAIN="local",
        GOFLAGS="",
        GOWORK="off",
        GOAMD64="v1",
        GOEXPERIMENT="",
        GOENV="off",
        GO111MODULE="on",
    )
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
    output_identity = None
    if output_fd is None:
        # Windows has no dir_fd support for the publication calls below.
        # Keep the checked directory's file ID to detect a moved directory
        # with a hard-linked lock before any path-based publication.
        metadata = output.stat(follow_symlinks=False)
        if not stat.S_ISDIR(metadata.st_mode) or not metadata.st_ino:
            raise RuntimeError("unsafe desktop output directory identity")
        output_identity = (metadata.st_dev, metadata.st_ino)
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
        if output_fd is None:
            try:
                current = output.stat(follow_symlinks=False)
            except OSError:
                return False
            return (
                stat.S_ISDIR(current.st_mode)
                and (
                    current.st_dev,
                    current.st_ino,
                )
                == output_identity
            )
        if current_output_fd is None:
            return False
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
        if not owns_lock():
            raise RuntimeError("desktop build lock changed before publication")
        _require_generated_prior_manifest(output, output_fd)
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
            source_copy = _snapshot_desktop_source(
                ROOT, staged / "source", source_digest
            )
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
                    cwd=source_copy,
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
                if not owns_lock():
                    raise RuntimeError(
                        "desktop build lock changed during launcher publication"
                    )
                _publish_launcher(output, output_fd, staged / name, name)
                if not owns_lock():
                    raise RuntimeError(
                        "desktop build lock changed during launcher publication"
                    )
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
            if owns_lock_inode() and (output_fd is not None or owns_lock()):
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
