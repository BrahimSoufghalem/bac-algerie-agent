from pathlib import Path
from dataclasses import replace
from bac.core.config import Settings
from bac.library.cache import ContentCache
from bac.core.db import DB
from bac.vendor.bookforge.core.storage import LocalStorage
from bac.vendor.bookforge.core.secrets import SecretVault
from bac.vendor.bookforge.core.config import Settings as ExtractionSettings
from bac.vendor.bookforge.database.db import Database as ExtractionDB
from bac.vendor.bookforge.workers.queue import Queue
from bac.vendor.bookforge.workers.engine import Engine

ROOT = Path(__file__).resolve().parents[2]


class Services:
    def __init__(
        self,
        settings=None,
        vision_factory=None,
        chat_factory=None,
        connection_transport=None,
    ):
        self.settings = settings or Settings.from_env()
        self.store = LocalStorage(self.settings.data_dir)
        self.db = DB(self.store.root / "platform.sqlite3")
        self.vault = SecretVault(self.store.root)
        self.extraction_settings = replace(
            ExtractionSettings.from_env(),
            data_dir=self.store.root / "extraction",
            max_workers=self.settings.extraction_workers,
            worker_ceiling=max(16, self.settings.extraction_workers),
            max_upload_mb=self.settings.max_upload_mb,
            prompt_file=ROOT / "config/extraction.yaml",
            allow_private_model_urls=self.settings.allow_private_model_urls,
        )
        self.extraction_store = LocalStorage(self.extraction_settings.data_dir)
        self.extraction_db = ExtractionDB(
            self.extraction_store.root / "state.sqlite3",
            self.settings.extraction_workers,
        )
        self.extraction_queue = Queue(self.extraction_db, self.extraction_settings)
        self.extraction_engine = Engine(
            self.extraction_db,
            self.extraction_store,
            self.extraction_settings,
            vision_factory,
        )
        from bac.learning.usage import MeteredVision

        original_factory = self.extraction_engine.provider_factory
        self.extraction_engine.provider_factory = lambda cfg, key: MeteredVision(
            self, original_factory(cfg, key), cfg
        )
        self.connection_transport = connection_transport
        self.chat_factory = chat_factory
        self.library_cache = ContentCache()
