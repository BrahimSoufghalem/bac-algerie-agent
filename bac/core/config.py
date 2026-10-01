from dataclasses import dataclass
from pathlib import Path
import os
from bac.vendor.bookforge.core.config import load_env


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path("data")
    secure_cookies: bool = False
    session_hours: int = 168
    agent_workers: int = 2
    max_run_steps: int = 8
    max_run_seconds: int = 180
    max_context_chars: int = 60000
    max_tool_chars: int = 22000
    max_daily_requests: int = 50
    extraction_workers: int = 2
    max_upload_mb: int = 100
    science_timeout: int = 6
    science_cpu_seconds: int = 4
    science_memory_mb: int = 256
    allow_private_model_urls: bool = False

    @classmethod
    def from_env(cls):
        load_env()
        s = cls(
            data_dir=Path(os.getenv("DATA_DIR", "data")),
            secure_cookies=os.getenv("SECURE_COOKIES", "false") == "true",
            agent_workers=int(os.getenv("AGENT_WORKERS", "2")),
            extraction_workers=int(os.getenv("EXTRACTION_WORKERS", "2")),
            max_run_steps=int(os.getenv("MAX_RUN_STEPS", "8")),
            max_run_seconds=int(os.getenv("MAX_RUN_SECONDS", "180")),
            max_context_chars=int(os.getenv("MAX_CONTEXT_CHARS", "60000")),
            max_tool_chars=int(os.getenv("MAX_TOOL_CHARS", "22000")),
            max_daily_requests=int(os.getenv("MAX_DAILY_REQUESTS", "50")),
            max_upload_mb=int(os.getenv("MAX_UPLOAD_MB", "100")),
            science_timeout=int(os.getenv("SCIENCE_TIMEOUT", "6")),
            science_cpu_seconds=int(os.getenv("SCIENCE_CPU_SECONDS", "4")),
            science_memory_mb=int(os.getenv("SCIENCE_MEMORY_MB", "256")),
            allow_private_model_urls=os.getenv("ALLOW_PRIVATE_MODEL_URLS", "false")
            == "true",
        )
        if not (
            1 <= s.agent_workers <= 16
            and 1 <= s.extraction_workers <= 16
            and 1 <= s.max_run_steps <= 20
            and 10 <= s.max_run_seconds <= 600
        ):
            raise ValueError("Invalid worker/run limits")
        if not (
            10000 <= s.max_context_chars <= 300000
            and 1000 <= s.max_tool_chars <= s.max_context_chars
            and s.max_daily_requests >= 1
        ):
            raise ValueError("Invalid context/usage limits")
        if not (
            2 <= s.science_timeout <= 15
            and 1 <= s.science_cpu_seconds <= s.science_timeout
            and 128 <= s.science_memory_mb <= 512
        ):
            raise ValueError("Invalid scientific process limits")
        return s
