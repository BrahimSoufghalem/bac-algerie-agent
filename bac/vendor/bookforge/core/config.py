from dataclasses import dataclass
from pathlib import Path
import os
import math


def load_env(path: Path = Path(".env")):
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path("data")
    max_workers: int = 4
    worker_ceiling: int = 32
    max_retries: int = 3
    page_dpi: int = 200
    max_pixels: int = 16_000_000
    max_upload_mb: int = 512
    max_pages: int = 10000
    request_timeout: float = 180
    lease_seconds: int = 240
    min_request_interval: float = 0.25
    app_auth_token: str = ""
    agent_api_token: str = ""
    allow_private_model_urls: bool = False
    prompt_file: Path = Path("config/prompts.yaml")
    output_format: str = "markdown"

    def __post_init__(self):
        if not 1 <= self.max_workers <= self.worker_ceiling <= 128:
            raise ValueError("Invalid worker limits")
        if not 72 <= self.page_dpi <= 600 or not 0 <= self.max_retries <= 20:
            raise ValueError("Invalid DPI or retries")
        if (
            self.lease_seconds < 10
            or not math.isfinite(self.request_timeout)
            or self.request_timeout <= 0
            or self.min_request_interval < 0
        ):
            raise ValueError("Invalid timeouts")
        if self.max_pixels < 1_000_000 or self.max_upload_mb < 1 or self.max_pages < 1:
            raise ValueError("Invalid resource limits")
        if self.output_format != "markdown":
            raise ValueError("Only markdown output is currently supported")

    @classmethod
    def from_env(cls):
        load_env()
        return cls(
            data_dir=Path(os.getenv("DATA_DIR", "data")),
            max_workers=int(os.getenv("MAX_WORKERS", "4")),
            worker_ceiling=int(os.getenv("WORKER_CEILING", "32")),
            max_retries=int(os.getenv("MAX_RETRIES", "3")),
            page_dpi=int(os.getenv("PAGE_DPI", "200")),
            max_pixels=int(os.getenv("MAX_PIXELS", "16000000")),
            max_upload_mb=int(os.getenv("MAX_UPLOAD_MB", "512")),
            max_pages=int(os.getenv("MAX_PAGES", "10000")),
            request_timeout=float(os.getenv("REQUEST_TIMEOUT", "180")),
            lease_seconds=int(os.getenv("LEASE_SECONDS", "240")),
            min_request_interval=float(os.getenv("MIN_REQUEST_INTERVAL", "0.25")),
            app_auth_token=os.getenv("APP_AUTH_TOKEN", ""),
            agent_api_token=os.getenv("AGENT_API_TOKEN", ""),
            allow_private_model_urls=os.getenv(
                "ALLOW_PRIVATE_MODEL_URLS", "false"
            ).lower()
            == "true",
            prompt_file=Path(os.getenv("PROMPT_FILE", "config/prompts.yaml")),
            output_format=os.getenv("OUTPUT_FORMAT", "markdown"),
        )
