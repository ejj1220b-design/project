"""config/*.yaml 과 환경변수 로딩."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_CONFIG_DIR = Path(os.environ.get("ROASLOOP_CONFIG", "config"))


def _load(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"설정 파일이 없습니다: {path}")
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


@dataclass
class MetaCredentials:
    access_token: str
    ad_account_id: str
    page_id: str = ""
    instagram_id: str = ""
    pixel_id: str = ""

    @classmethod
    def from_env(cls) -> "MetaCredentials":
        token = os.environ.get("META_ACCESS_TOKEN", "")
        account = os.environ.get("META_AD_ACCOUNT_ID", "")
        missing = [n for n, v in (("META_ACCESS_TOKEN", token), ("META_AD_ACCOUNT_ID", account)) if not v]
        if missing:
            raise RuntimeError(
                f"환경변수가 비어 있습니다: {', '.join(missing)}. .env.example 을 참고하세요."
            )
        if not account.startswith("act_"):
            account = f"act_{account}"
        return cls(
            access_token=token,
            ad_account_id=account,
            page_id=os.environ.get("META_PAGE_ID", ""),
            instagram_id=os.environ.get("META_IG_ACCOUNT_ID", ""),
            pixel_id=os.environ.get("META_PIXEL_ID", ""),
        )


@dataclass
class Config:
    taxonomy: dict
    landings: dict
    account: dict
    rules: dict
    matrix: dict = field(default_factory=dict)
    config_dir: Path = DEFAULT_CONFIG_DIR

    @classmethod
    def load(cls, config_dir: Path | str | None = None) -> "Config":
        d = Path(config_dir) if config_dir else DEFAULT_CONFIG_DIR
        matrix_path = d / "matrix.yaml"
        return cls(
            taxonomy=_load(d / "taxonomy.yaml"),
            landings=_load(d / "landing.yaml").get("landings", {}),
            account=_load(d / "account.yaml"),
            rules=_load(d / "rules.yaml"),
            matrix=_load(matrix_path) if matrix_path.exists() else {},
            config_dir=d,
        )

    # 자주 쓰는 값들
    @property
    def defaults(self) -> dict:
        return self.account.get("defaults", {})

    @property
    def utm(self) -> dict:
        return self.account.get("utm", {})

    @property
    def conversion(self) -> dict:
        return self.account.get("conversion", {})

    @property
    def currency(self) -> str:
        return self.account.get("account", {}).get("currency", "KRW")
