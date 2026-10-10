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
    # Legacy constructor argument only; coordinated mode has a per-model ceiling.
    max_run_steps: int = 0
    max_run_seconds: int = 180
    max_context_chars: int = 60000
    max_tool_chars: int = 22000
    max_daily_requests: int = 50
    max_upload_mb: int = 100
    science_timeout: int = 6
    science_cpu_seconds: int = 4
    science_memory_mb: int = 256
    allow_private_model_urls: bool = False

    public_origin: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_from: str = ""
    smtp_user: str = ""
    smtp_password: str = ""
    require_verified_email: bool = False
    trusted_hosts: tuple[str, ...] = ()

    @classmethod
    def from_env(cls):
        load_env()
        s = cls(
            public_origin=os.getenv("PUBLIC_ORIGIN", ""),
            smtp_host=os.getenv("SMTP_HOST", ""),
            smtp_port=int(os.getenv("SMTP_PORT", "587")),
            smtp_from=os.getenv("SMTP_FROM", ""),
            smtp_user=os.getenv("SMTP_USER", ""),
            smtp_password=os.getenv("SMTP_PASSWORD", ""),
            require_verified_email=os.getenv("REQUIRE_VERIFIED_EMAIL", "false")
            == "true",
            trusted_hosts=tuple(
                x.strip()
                for x in os.getenv("TRUSTED_HOSTS", "").split(",")
                if x.strip()
            ),
            data_dir=Path(os.getenv("DATA_DIR", "data")),
            secure_cookies=os.getenv("SECURE_COOKIES", "false") == "true",
            agent_workers=int(os.getenv("AGENT_WORKERS", "2")),
            max_run_steps=0,
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
        if s.smtp_host and (
            not s.public_origin.startswith("https://") or not s.smtp_from
        ):
            raise ValueError("SMTP requires HTTPS PUBLIC_ORIGIN and SMTP_FROM")
        if s.require_verified_email and not s.smtp_host:
            raise ValueError("Verified email policy requires configured SMTP")
        return s
