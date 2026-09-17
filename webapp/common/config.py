"""Load webapp/config/settings.yaml (falling back to sane defaults).

Both the API and worker containers mount `webapp/config/` read-only at
`/config` and read `CATRANGE_SETTINGS_PATH` (defaulting to
`/config/settings.yaml`). See `webapp/config/settings.example.yaml` for the
documented schema and `webapp/README.md` for how to fill in real values.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_SETTINGS_PATH = os.environ.get("CATRANGE_SETTINGS_PATH", "/config/settings.yaml")
DEFAULT_DATA_DIR = os.environ.get("CATRANGE_DATA_DIR", "/data")


@dataclass
class LocalSettings:
    max_concurrent_jobs: int = 1
    max_queue_depth: int = 5
    device: str = "auto"


@dataclass
class HccSettings:
    enabled: bool = False
    ssh_host: str = ""
    ssh_user: str = ""
    ssh_key_path: str = ""
    partition: str = "ssbio"
    account: str = ""
    qos: str = ""
    remote_work_dir: str = "/work/ssbio/catrange_jobs"
    max_concurrent_jobs: int = 2
    poll_interval_seconds: int = 60


@dataclass
class EmailSettings:
    enabled: bool = False
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    from_address: str = "catrange@sahassbio.com"


@dataclass
class SiteSettings:
    base_url: str = "https://catrange.sahassbio.com"
    colab_url: str = (
        "https://colab.research.google.com/github/ssbio/CatRange/blob/main/"
        "CatRange_Inference_Interface.ipynb"
    )


@dataclass
class StorageSettings:
    data_dir: str = DEFAULT_DATA_DIR
    job_ttl_days: int = 14


@dataclass
class Settings:
    local: LocalSettings = field(default_factory=LocalSettings)
    hcc: HccSettings = field(default_factory=HccSettings)
    email: EmailSettings = field(default_factory=EmailSettings)
    site: SiteSettings = field(default_factory=SiteSettings)
    storage: StorageSettings = field(default_factory=StorageSettings)


def _merge(dataclass_cls, raw: dict | None):
    raw = raw or {}
    return dataclass_cls(**{k: v for k, v in raw.items() if k in dataclass_cls.__dataclass_fields__})


def load_settings(path: str | Path | None = None) -> Settings:
    settings_path = Path(path or DEFAULT_SETTINGS_PATH)
    raw: dict = {}
    if settings_path.exists():
        with settings_path.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
    else:
        # No settings.yaml mounted yet (e.g. first run before the lab copies
        # settings.example.yaml). Fall back to defaults everywhere except
        # site.base_url so the service still boots and behaves safely
        # (HCC/email disabled, small local concurrency).
        pass

    return Settings(
        local=_merge(LocalSettings, raw.get("local")),
        hcc=_merge(HccSettings, raw.get("hcc")),
        email=_merge(EmailSettings, raw.get("email")),
        site=_merge(SiteSettings, raw.get("site")),
        storage=_merge(StorageSettings, raw.get("storage")),
    )


_settings: Settings | None = None


def get_settings(refresh: bool = False) -> Settings:
    global _settings
    if _settings is None or refresh:
        _settings = load_settings()
    return _settings
