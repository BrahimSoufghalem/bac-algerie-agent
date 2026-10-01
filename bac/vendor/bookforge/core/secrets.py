from pathlib import Path
from cryptography.fernet import Fernet
import os
import time


class SecretVault:
    """Resume-safe encryption; the machine key must be backed up with the database."""
    def __init__(self, root: Path):
        root.mkdir(parents=True, exist_ok=True)
        p = root / '.encryption.key'
        try:
            fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, 'wb') as f:
                f.write(Fernet.generate_key())
                f.flush()
                os.fsync(f.fileno())
        for _ in range(50):
            key = p.read_bytes()
            if len(key) == 44:
                self.cipher = Fernet(key)
                break
            time.sleep(0.02)
        else:
            raise RuntimeError('Invalid encryption key; restore the original key backup')

    def encrypt(self, value: str) -> str:
        return self.cipher.encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        return self.cipher.decrypt(value.encode()).decode()
