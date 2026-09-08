import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from roasloop.config import Config  # noqa: E402


@pytest.fixture
def cfg() -> Config:
    return Config.load(ROOT / "config")


@pytest.fixture
def rules(cfg) -> dict:
    return cfg.rules
