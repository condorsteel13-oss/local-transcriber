"""Small, dependency-free persistence helpers for Local Transcriber."""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def signature(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def atomic_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".partial", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as target:
            target.write(value)
            target.flush()
            os.fsync(target.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def atomic_json(path: Path, value: object) -> None:
    atomic_bytes(
        path,
        (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode(),
    )


def read_json(path: Path) -> object:
    def pairs(items):
        output = {}
        for key, value in items:
            if key in output:
                raise ValueError(f"Duplicate JSON key: {key}")
            output[key] = value
        return output

    def constant(value):
        raise ValueError(f"Invalid JSON constant: {value}")

    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=pairs,
        parse_constant=constant,
    )


def artifact(path: Path, job: Path) -> dict:
    return {
        "path": str(path.relative_to(job)),
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
    }


def verified(job: Path, stage: dict) -> bool:
    if stage.get("status") != "succeeded" or not stage.get("artifacts"):
        return False
    for item in stage["artifacts"]:
        path = job / item["path"]
        if (
            not path.is_file()
            or path.stat().st_size != item["bytes"]
            or sha256(path) != item["sha256"]
        ):
            return False
    return True


@contextlib.contextmanager
def exclusive_lock(output_root: Path, job_id: str):
    directory = output_root / ".locks"
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / f"{job_id}.lock").open("a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("This recording is already being processed.") from error
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)

\n