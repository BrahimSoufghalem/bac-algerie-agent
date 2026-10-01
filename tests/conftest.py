import pytest
from bac.core.config import Settings
from bac.core.services import Services


@pytest.fixture
def services(tmp_path):
    return Services(
        Settings(
            data_dir=tmp_path,
            max_run_seconds=20,
            max_run_steps=5,
            max_daily_requests=20,
        )
    )
