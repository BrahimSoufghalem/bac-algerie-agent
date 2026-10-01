from pathlib import Path
from typing import Protocol
import os
import uuid


class Storage(Protocol):
    def path(self, relative: str) -> Path: ...
    def write(self, relative: str, data: bytes) -> None: ...
    def read(self, relative: str) -> bytes: ...


class LocalStorage:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)

    def path(self, relative: str) -> Path:
        p = (self.root / relative).resolve()
        if p != self.root and self.root not in p.parents:
            raise ValueError('Unsafe storage path')
        return p

    def write(self, relative: str, data: bytes):
        p = self.path(relative)
        p.parent.mkdir(parents=True, exist_ok=True)
        temp = p.with_name(p.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            with open(temp, 'xb') as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp, p)
        finally:
            temp.unlink(missing_ok=True)

    def read(self, relative: str) -> bytes:
        return self.path(relative).read_bytes()
