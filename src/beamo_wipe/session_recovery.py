# SPDX-License-Identifier: GPL-3.0-or-later
"""Same-boot evidence journal. Never stores authority to start or resume nwipe."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
import time
from dataclasses import asdict
from pathlib import Path

from beamo_wipe import __version__, NWIPE_PINNED_VERSION, NWIPE_PINNED_COMMIT
from beamo_wipe.models import Disk, DiskKind, DiscoveryResult, MethodId
from beamo_wipe.safety import SafetyError

NAME = "session-recovery.json"
LIMIT = 256 * 1024
NOTICE = (
    "Recovered after an interface restart. No erase was restarted or resumed. "
    "Temporary evidence is lost on shutdown or power loss."
)


RECOVERY_UNSAFE_RECOVERY_FILE = "Unsafe recovery file"
RECOVERY_INVALID_RECOVERY_FILENAME = "Invalid recovery filename"
RECOVERY_RECOVERY_FILE_TOO_LARGE = "Recovery file too large"
RECOVERY_UNSAFE_RECOVERY_DIRECTORY = "Unsafe recovery directory"
RECOVERY_DIRECTORY_NOT_VOLATILE = "Recovery directory is not on the volatile filesystem"
RECOVERY_RECOVERY_IDENTITY_UNAVAILABLE = "Recovery identity unavailable"
RECOVERY_RECOVERY_IS_UNAVAILABLE = "Recovery is unavailable"
RECOVERY_RECOVERY_RECORD_TOO_LARGE = "Recovery record too large"
RECOVERY_PREVIOUS_ERASE_IS_NOT_CONFIRMED_STOPPED = "Previous erase is not confirmed stopped"
RECOVERY_THIS_SESSION_CANNOT_START_ANOTHER_ERASE = "This session cannot start another erase"
RECOVERY_FOREIGN_EVIDENCE_DIRECTORY = "Foreign evidence directory"
RECOVERY_INCOMPLETE_TERMINAL_EVIDENCE = "Incomplete terminal evidence"
RECOVERY_TERMINAL_EVIDENCE_CHANGED = "Terminal evidence changed"
RECOVERY_CONTRADICTORY_TERMINAL_EVIDENCE = "Contradictory terminal evidence"
RECOVERY_STALE_TERMINAL_EVIDENCE = "Stale terminal evidence"
RECOVERY_TERMINAL_RESULT_CANNOT_BE_PROVED = "Terminal result cannot be proved"


def _bytes(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate field")
        result[key] = value
    return result


def _disk(raw):
    if not isinstance(raw, dict) or set(raw) != set(Disk.__dataclass_fields__):
        raise ValueError("Invalid disk fields")
    for key, value in raw.items():
        if key in {"is_boot", "read_only", "hotplug"}:
            if type(value) is not bool:
                raise ValueError("Invalid disk flag")
        elif key == "size_bytes":
            if type(value) is not int or not 0 < value < 2**64:
                raise ValueError("Invalid disk size")
        elif key == "mountpoints":
            if value != []:
                raise ValueError("Unexpected mount metadata")
        elif key == "raw_model" and value is None:
            continue
        elif key == "contents":
            from beamo_wipe.models import CONTENTS_VALUES

            if value not in CONTENTS_VALUES:
                raise ValueError("Invalid disk contents")
            continue
        elif (
            not isinstance(value, str)
            or len(value) > 256
            or any(ord(c) < 32 or ord(c) == 127 for c in value)
        ):
            raise ValueError("Invalid disk text")
    from beamo_wipe.support_export import ROOT_PATH_RE

    if not ROOT_PATH_RE.fullmatch(raw["path"]) or raw["name"] != Path(raw["path"]).name:
        raise ValueError("Invalid disk path")
    return Disk(**{**raw, "kind": DiskKind(raw["kind"]), "mountpoints": ()})


class SessionStore:
    """One UI owner; a separate, inherited runner lock remains authoritative.

    Exact source hash is the compatibility policy. v0/unknown schemas have no
    safe migration and are rejected, never upgraded from percentages or logs.
    """

    def __init__(self, directory=None, *, boot=None, build=None):
        self._production_directory = directory is None
        self.directory = (
            Path(directory) if directory is not None else Path("/tmp/beamo-wipe")
        )
        self.fd = self.owner = self.quiescent = -1
        self.record: dict | None = None
        self.previous = False
        self.invalid = False
        self.boot = boot
        self.build = build

    def _file(self, name, flags=os.O_RDONLY):
        fd = os.open(name, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=self.fd)
        try:
            st = os.fstat(fd)
            if (
                not stat.S_ISREG(st.st_mode)
                or st.st_uid != os.getuid()
                or stat.S_IMODE(st.st_mode) != 0o600
                or st.st_nlink != 1
            ):
                raise SafetyError(RECOVERY_UNSAFE_RECOVERY_FILE)
        except BaseException:
            os.close(fd)
            raise
        return fd

    def read(self, name):
        if Path(name).name != name or name in {".", ".."}:
            raise SafetyError(RECOVERY_INVALID_RECOVERY_FILENAME)
        fd = self._file(name)
        try:
            opened = os.fstat(fd)
            chunks = []
            remaining = LIMIT + 1
            while remaining:
                chunk = os.read(fd, min(65536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            if not remaining:
                raise SafetyError(RECOVERY_RECOVERY_FILE_TOO_LARGE)
            after = os.fstat(fd)
            if (
                opened.st_dev,
                opened.st_ino,
                opened.st_size,
                opened.st_mode,
                opened.st_nlink,
                opened.st_mtime_ns,
                opened.st_ctime_ns,
            ) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mode,
                after.st_nlink,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ) or (
                stat.S_IMODE(after.st_mode) != 0o600
                or after.st_nlink != 1
                or sum(map(len, chunks)) != opened.st_size
            ):
                raise SafetyError(RECOVERY_UNSAFE_RECOVERY_FILE)
            return b"".join(chunks)
        finally:
            os.close(fd)

    def open(self):
        try:
            return self._open_owned()
        except BaseException:
            # Opening may fail after acquiring the interface flock (invalid
            # boot/build identity, unsafe directory, or an I/O error). Do not
            # strand ownership and block a corrected retry in this process.
            try:
                self.close()
            except BaseException:
                pass  # Preserve the original refusal; close retired each fd.
            raise

    def _open_owned(self):
        try:
            self.directory.mkdir(mode=0o700)
        except FileExistsError:
            pass
        self.fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        st = os.fstat(self.fd)
        if st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) != 0o700:
            raise SafetyError(RECOVERY_UNSAFE_RECOVERY_DIRECTORY)
        if self._production_directory and st.st_dev != os.stat("/tmp").st_dev:
            raise SafetyError(RECOVERY_DIRECTORY_NOT_VOLATILE)
        self.owner = self._file("interface.lock", os.O_RDWR | os.O_CREAT)
        fcntl.flock(self.owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if self.boot is None:
            self.boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        if self.build is None:
            from beamo_wipe.diagnostic_report import runtime_source_sha256

            self.build = runtime_source_sha256()
        if (
            not isinstance(self.boot, str)
            or not re.fullmatch(
                r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}", self.boot
            )
            or not isinstance(self.build, str)
            or not re.fullmatch(r"[0-9a-f]{64}", self.build)
        ):
            raise SafetyError(RECOVERY_RECOVERY_IDENTITY_UNAVAILABLE)
        try:
            raw = self.read(NAME)
        except FileNotFoundError:
            # Missing journal alongside older run artifacts has no safe migration.
            if any(
                name == "wipe.lock"
                or name.startswith(("result-", "nwipe", ".recovery-"))
                for name in os.listdir(self.fd)
            ):
                self.previous = self.invalid = True
                return self
            self.save({"phase": "preflight", "context": None, "terminal": None})
            return self
        except (OSError, SafetyError):
            self.previous = self.invalid = True
            return self
        self.previous = True
        try:
            envelope = json.loads(raw, object_pairs_hook=_object)
            if (
                set(envelope) != {"payload", "sha256"}
                or hashlib.sha256(_bytes(envelope["payload"])).hexdigest()
                != envelope["sha256"]
            ):
                raise ValueError("Corrupt recovery record")
            record = envelope["payload"]
            self.validate(record)
            self.record = record
        except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
            self.invalid = True
        return self

    def validate(self, record):
        if (
            set(record)
            != {
                "schema",
                "boot",
                "build",
                "session",
                "created",
                "phase",
                "context",
                "terminal",
            }
            or type(record["schema"]) is not int
            or record["schema"] != 1
            or record["boot"] != self.boot
            or record["build"] != self.build
            or not re.fullmatch(r"[0-9a-f]{32}", record["session"])
        ):
            raise ValueError("Foreign or unsupported recovery record")
        if (
            type(record["created"]) not in {int, float}
            or not 0 <= record["created"] <= time.monotonic()
        ):
            raise ValueError("Stale recovery clock")
        phase, context, terminal = (
            record["phase"],
            record["context"],
            record["terminal"],
        )
        if phase == "preflight":
            if context is not None or terminal is not None:
                raise ValueError("Contradictory preflight")
            return
        if (
            phase not in {"armed", "terminal"}
            or not isinstance(context, dict)
            or set(context)
            != {
                "disks",
                "target",
                "boot",
                "method",
                "logfile",
                "target_rdev",
                "boot_rdev",
            }
        ):
            raise ValueError("Invalid recovery context")
        if (
            not isinstance(context["disks"], list)
            or not 2 <= len(context["disks"]) <= 256
        ):
            raise ValueError("Invalid baseline")
        disks = [_disk(item) for item in context["disks"]]
        paths = [d.path for d in disks]
        if (
            len(set(paths)) != len(paths)
            or context["target"] not in paths
            or context["boot"] not in paths
            or context["target"] == context["boot"]
            or [d.path for d in disks if d.is_boot] != [context["boot"]]
        ):
            raise ValueError("Contradictory disk identities")
        MethodId(context["method"])
        if Path(context["logfile"]).parent != self.directory or not re.fullmatch(
            r"[A-Za-z0-9_.-]+", Path(context["logfile"]).name
        ):
            raise ValueError("Invalid log path")
        for key in ("target_rdev", "boot_rdev"):
            if type(context[key]) is not int or context[key] < 0:
                raise ValueError("Invalid kernel identity")
        if phase == "armed":
            if terminal is not None:
                raise ValueError("Contradictory running record")
        elif (
            not isinstance(terminal, dict)
            or set(terminal) != {"name", "sha256"}
            or not re.fullmatch(r"result-[A-Za-z0-9_-]+-[0-9]+\.json", terminal["name"])
            or not re.fullmatch(r"[0-9a-f]{64}", terminal["sha256"])
        ):
            raise ValueError("Invalid terminal reference")

    def save(self, changes):
        if self.invalid or self.owner < 0:
            raise SafetyError(RECOVERY_RECOVERY_IS_UNAVAILABLE)
        record = {
            "schema": 1,
            "boot": self.boot,
            "build": self.build,
            "session": secrets.token_hex(16),
            "created": time.monotonic(),
            **(self.record or {}),
            **changes,
        }
        self.validate(record)
        data = _bytes(
            {"payload": record, "sha256": hashlib.sha256(_bytes(record)).hexdigest()}
        )
        if len(data) > LIMIT:
            raise SafetyError(RECOVERY_RECOVERY_RECORD_TOO_LARGE)
        name = ".recovery-" + secrets.token_hex(12)
        fd = self._file(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        replaced = False
        try:
            while data:
                n = os.write(fd, data)
                if n <= 0:
                    raise OSError("Incomplete recovery write")
                data = data[n:]
            os.fsync(fd)
            os.replace(name, NAME, src_dir_fd=self.fd, dst_dir_fd=self.fd)
            replaced = True
            # The new journal is now visible. A failed directory sync makes
            # durability uncertain, so keep this phase in memory and block
            # further writes until recovery reopens the on-disk record.
            self.record = record
            os.fsync(self.fd)
        except BaseException:
            if replaced:
                self.invalid = True
            raise
        finally:
            try:
                os.close(fd)
            except BaseException:
                if replaced:
                    self.invalid = True
                raise
            finally:
                try:
                    os.unlink(name, dir_fd=self.fd)
                except FileNotFoundError:
                    pass
                except BaseException:
                    if replaced:
                        self.invalid = True
                    raise

    def _release_quiescent(self):
        fd = self.quiescent
        self.quiescent = -1  # A failed close may already have retired this fd.
        try:
            os.close(fd)
        except BaseException:
            self.invalid = True
            raise

    def begin_new_session(self):
        """Rotate the journal only after the UI resolved the previous report.

        Keep old evidence/log files, and retain interface ownership throughout.
        The runner lock proves that no old process can still be writing.
        """
        if self.invalid or self.record is None or not self.is_quiescent():
            raise SafetyError(RECOVERY_PREVIOUS_ERASE_IS_NOT_CONFIRMED_STOPPED)
        # A manually started pinned engine may not hold our wipe.lock. Keep
        # the journal and this UI owner until its absence is proved too.
        from beamo_wipe.nwipe_runner import pinned_nwipe_already_running

        try:
            pinned_busy = pinned_nwipe_already_running() is not False
        except Exception:
            pinned_busy = True
        if pinned_busy:
            raise SafetyError(RECOVERY_PREVIOUS_ERASE_IS_NOT_CONFIRMED_STOPPED)
        self.save({"phase": "preflight", "context": None, "terminal": None,
                   "session": secrets.token_hex(16), "created": time.monotonic()})
        self.previous = False
        self._release_quiescent()

    def resume_previous_preflight(self) -> bool:
        """Rotate a valid pre-spawn journal after ruling out an active engine.

        The caller must not restore any confirmation or erase request. The
        exclusive runner lock covers the gap between the process probe and
        writing the new journal.
        """
        if (
            not self.previous or self.invalid or self.record is None
            or self.record.get("phase") != "preflight"
            or self.record.get("context") is not None
            or self.record.get("terminal") is not None
            or not self.is_quiescent()
        ):
            return False
        from beamo_wipe.nwipe_runner import pinned_nwipe_already_running

        if pinned_nwipe_already_running() is not False:
            return False
        self.begin_new_session()
        return True

    def arm(self, discovery, request):
        if self.record is None or self.record["phase"] != "preflight" or self.previous:
            raise SafetyError(RECOVERY_THIS_SESSION_CANNOT_START_ANOTHER_ERASE)
        disks = []
        for disk in discovery.disks:
            item = asdict(disk)
            item["mountpoints"] = []  # no filesystem paths needed for recovery/export
            disks.append(item)
        self.save(
            {
                "phase": "armed",
                "terminal": None,
                "context": {
                    "disks": disks,
                    "target": request.device,
                    "boot": request.boot_device,
                    "method": request.method.value,
                    "logfile": request.logfile,
                    "target_rdev": request.device_rdev,
                    "boot_rdev": request.boot_rdev,
                },
            }
        )

    def disarm_unstarted(self):
        """Restore preflight only when the caller proved no engine was spawned."""
        if (
            self.invalid or self.previous or self.record is None
            or self.record["phase"] != "armed" or not self.is_quiescent()
        ):
            raise SafetyError(RECOVERY_PREVIOUS_ERASE_IS_NOT_CONFIRMED_STOPPED)
        self.save({"phase": "preflight", "context": None, "terminal": None})
        self._release_quiescent()

    def finish(self, path):
        if Path(path).parent != self.directory:
            raise SafetyError(RECOVERY_FOREIGN_EVIDENCE_DIRECTORY)
        data = self.read(Path(path).name)
        sidecar = self.read(Path(path).name + ".sha256")
        digest = hashlib.sha256(data).hexdigest()
        if sidecar != f"{digest}  {Path(path).name}\n".encode():
            raise SafetyError(RECOVERY_INCOMPLETE_TERMINAL_EVIDENCE)
        self.save(
            {
                "phase": "terminal",
                "terminal": {"name": Path(path).name, "sha256": digest},
            }
        )

    def is_quiescent(self):
        if self.quiescent >= 0:
            return True
        fd = self._file("wipe.lock", os.O_RDWR | os.O_CREAT)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            return False
        except BaseException:
            os.close(fd)
            raise
        self.quiescent = fd  # Retain through recovery/export, never attach or signal.
        return True

    def context(self):
        context = self.record["context"]
        disks = tuple(_disk(d) for d in context["disks"])
        boot = next(d for d in disks if d.path == context["boot"])
        target = next(d for d in disks if d.path == context["target"])
        return (
            context,
            DiscoveryResult(disks=disks, boot=boot, boot_identified=True),
            target,
        )

    def terminal(self):
        from beamo_wipe.evidence import SUPPORTED_SCHEMA_VERSIONS, recover_result
        from beamo_wipe.outcomes import present_evidence

        reference = self.record["terminal"]
        path = self.directory / reference["name"]
        raw = self.read(reference["name"])
        digest = hashlib.sha256(raw).hexdigest()
        if (
            digest != reference["sha256"]
            or self.read(reference["name"] + ".sha256")
            != f"{digest}  {path.name}\n".encode()
        ):
            raise SafetyError(RECOVERY_TERMINAL_EVIDENCE_CHANGED)
        evidence = json.loads(raw, object_pairs_hook=_object)
        context, _, target = self.context()
        from beamo_wipe.evidence import _device_identity

        if (
            evidence.get("device") != _device_identity(target)
            or evidence.get("boot_device") != context["boot"]
            or evidence.get("logfile") != context["logfile"]
            or evidence.get("method", {}).get("id") != context["method"]
            or evidence.get("beamo_wipe_version") != __version__
            or evidence.get("nwipe_version") != NWIPE_PINNED_VERSION
            or evidence.get("nwipe_commit") != NWIPE_PINNED_COMMIT
            or evidence.get("schema_version") not in SUPPORTED_SCHEMA_VERSIONS
            or evidence.get("provenance", {}).get("evidence_file") != str(path)
        ):
            raise SafetyError(RECOVERY_CONTRADICTORY_TERMINAL_EVIDENCE)
        times = evidence.get("timestamps", {})
        start, end = times.get("started_monotonic"), times.get("ended_monotonic")
        if (
            type(start) not in {int, float}
            or type(end) not in {int, float}
            or not self.record["created"] <= start <= end <= time.monotonic()
        ):
            raise SafetyError(RECOVERY_STALE_TERMINAL_EVIDENCE)
        view = recover_result(path, expected_sha256=digest)
        if view.code == "indeterminate" or view != present_evidence(evidence):
            raise SafetyError(RECOVERY_TERMINAL_RESULT_CANNOT_BE_PROVED)
        if view.success or view.code in {"occupied", "open_failed", "geometry_unusable"}:
            # recover_result validates the exact log suffix; additionally reject
            # unsafe log modes/links before using a log-backed verdict.
            fd = self._file(Path(context["logfile"]).name)
            os.close(fd)
        return path, evidence

    def close(self):
        first_error = None
        for key in ("quiescent", "owner", "fd"):
            fd = getattr(self, key)
            # A failed close may already have retired this fd. Never retain a
            # stale number that a later close could use against another file.
            setattr(self, key, -1)
            if fd >= 0:
                try:
                    os.close(fd)
                except BaseException as exc:
                    if first_error is None:
                        first_error = exc
        if first_error is not None:
            raise first_error
