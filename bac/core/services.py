from pathlib import Path
from bac.core.config import Settings
from bac.library.cache import ContentCache
from bac.core.db import DB
from bac.vendor.bookforge.core.storage import LocalStorage
from bac.vendor.bookforge.core.secrets import SecretVault

ROOT = Path(__file__).resolve().parents[2]


class Services:
    def __init__(
        self,
        settings=None,
        chat_factory=None,
        connection_transport=None,
    ):
        self.settings = settings or Settings.from_env()
        from bac.ops.guard import DataGuard

        self.guard = DataGuard(self.settings.data_dir.resolve())
        self.store = LocalStorage(self.settings.data_dir)
        self.db = DB(self.store.root / "platform.sqlite3")
        self.vault = SecretVault(self.store.root)
        self.selector_transport = None
        self.connection_transport = connection_transport
        self.chat_factory = chat_factory
        self.library_cache = ContentCache()
        from bac.library.service import Library

        Library(self).cleanup()

    def close(self):
        self.guard.close()
