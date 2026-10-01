"""Single-host Linux advisory lifecycle lock, also used by offline maintenance."""

import fcntl
from pathlib import Path


class DataGuard:
    def __init__(self, root: Path, exclusive=False):
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.file = open(root / ".runtime.lock", "a")
        try:
            fcntl.flock(
                self.file,
                (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB,
            )
        except BlockingIOError:
            self.file.close()
            raise RuntimeError(
                "Data is in use: stop API and worker before offline maintenance"
            ) from None

    def close(self):
        if not self.file.closed:
            fcntl.flock(self.file, fcntl.LOCK_UN)
            self.file.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
