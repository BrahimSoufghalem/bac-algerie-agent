"""Offline, integrity-checked full-data backup. Archives contain private data + keys."""

import hashlib, json, os, shutil, sqlite3, tempfile, time, zipfile
from pathlib import Path, PurePosixPath
from bac.ops.guard import DataGuard

REQUIRED = {
    "platform.sqlite3",
    "extraction/state.sqlite3",
    ".encryption.key",
    "extraction/.encryption.key",
}
SKIP = {".runtime.lock", ".migration.lock", "platform.sqlite3.migration.lock"}


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024**2), b""):
            h.update(chunk)
    return h.hexdigest()


def integrity(root):
    if not all((root / p).is_file() for p in REQUIRED):
        raise ValueError("Backup requires both databases and both encryption keys")
    from cryptography.fernet import Fernet

    for p in (".encryption.key", "extraction/.encryption.key"):
        Fernet((root / p).read_bytes())
    for p in ("platform.sqlite3", "extraction/state.sqlite3"):
        with sqlite3.connect(f"file:{root / p}?mode=ro", uri=True) as c:
            if (
                c.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
                or c.execute("PRAGMA foreign_key_check").fetchone()
            ):
                raise ValueError("Database integrity check failed")


def backup(root, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    if output.is_relative_to(root) or output.exists():
        raise ValueError("Choose a new backup path outside DATA_DIR")
    if not root.is_dir():
        raise ValueError("Existing DATA_DIR required")
    output.parent.mkdir(parents=True, exist_ok=True)
    with DataGuard(root, exclusive=True):
        integrity(root)
        # No active application process now. Merge WAL before enumerating files.
        for db in ("platform.sqlite3", "extraction/state.sqlite3"):
            with sqlite3.connect(root / db) as c:
                if c.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0]:
                    raise RuntimeError("Database is busy; stop every data user")
        fd, temporary = tempfile.mkstemp(prefix=".masar-backup-", dir=output.parent)
        try:
            os.fchmod(fd, 0o600)
            os.close(fd)
            manifest = {
                "format": "masar-backup-v1",
                "app_version": "0.5.0",
                "created_at": time.time(),
                "files": {},
            }
            with zipfile.ZipFile(
                temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1
            ) as z:
                for file in sorted(root.rglob("*")):
                    if file.is_symlink():
                        raise ValueError("Symlinks are not allowed in DATA_DIR backups")
                    if (
                        not file.is_file()
                        or file.name in SKIP
                        or file.name.endswith(("-wal", "-shm", ".migration.lock"))
                    ):
                        continue
                    name = file.relative_to(root).as_posix()
                    if name == "manifest.json":
                        raise ValueError("Reserved backup manifest path")
                    manifest["files"][name] = {
                        "bytes": file.stat().st_size,
                        "sha256": digest(file),
                    }
                    z.write(file, name)
                z.writestr("manifest.json", json.dumps(manifest))
            with open(temporary, "rb") as f:
                os.fsync(f.fileno())
            # Exclusive target creation; never silently overwrite an existing archive.
            os.link(temporary, output)
            return {
                "files": len(manifest["files"]),
                "bytes": output.stat().st_size,
                "sha256": digest(output),
            }
        finally:
            Path(temporary).unlink(missing_ok=True)


def restore(archive, destination, max_bytes=5 * 1024**3, max_files=100000):
    """Only restore a trusted archive to a NEW directory. Hashes are not signatures."""
    destination = Path(destination).absolute()
    if destination.exists():
        raise ValueError(
            "Restore destination must not exist; never overwrite live data"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".masar-restore-", dir=destination.parent))
    try:
        with zipfile.ZipFile(archive) as z:
            infos = z.infolist()
            names = [i.filename for i in infos]
            if (
                len(names) > max_files
                or len(names) != len(set(names))
                or sum(i.file_size for i in infos) > max_bytes
            ):
                raise ValueError("Archive exceeds limits or has duplicate entries")
            for i in infos:
                p = PurePosixPath(i.filename)
                if (
                    not p.parts
                    or p.is_absolute()
                    or ".." in p.parts
                    or "\\" in i.filename
                    or ":" in i.filename
                    or "\x00" in i.filename
                    or i.is_dir()
                    or (i.external_attr >> 16) & 0o170000 == 0o120000
                ):
                    raise ValueError("Unsafe archive path/type")
            mi = z.getinfo("manifest.json")
            if mi.file_size > 20 * 1024**2:
                raise ValueError("Manifest exceeds limit")
            manifest = json.loads(z.read(mi))
            files = manifest.get("files", {})
            if (
                manifest.get("format") != "masar-backup-v1"
                or set(names) != set(files) | {"manifest.json"}
                or not REQUIRED.issubset(files)
            ):
                raise ValueError("Invalid/incomplete backup manifest")
            for i in infos:
                if i.filename == "manifest.json":
                    continue
                expected = files[i.filename]
                if i.file_size != expected["bytes"]:
                    raise ValueError("File length mismatch")
                out = stage / i.filename
                out.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                h, count = hashlib.sha256(), 0
                with os.fdopen(fd, "wb") as target, z.open(i) as source:
                    for chunk in iter(lambda: source.read(1024**2), b""):
                        count += len(chunk)
                        if count > i.file_size:
                            raise ValueError("Expanded length mismatch")
                        target.write(chunk)
                        h.update(chunk)
                if count != expected["bytes"] or h.hexdigest() != expected["sha256"]:
                    raise ValueError("Backup hash mismatch")
        integrity(stage)
        # rename is atomic on this filesystem; refuse any concurrently created destination.
        if destination.exists():
            raise ValueError("Restore destination was created concurrently")
        os.rename(stage, destination)
        return {"files": len(files), "destination": str(destination)}
    finally:
        if stage.exists():
            shutil.rmtree(stage)
