"""
VPS Panel - Core Configuration Module
"""

import os
import yaml
from pathlib import Path
from functools import lru_cache

BASE_DIR = Path(__file__).parent.parent


@lru_cache()
def load_config():
    config_path = BASE_DIR / "config.yaml"
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def get_config():
    return load_config()


def get_db_path():
    config = get_config()
    db_path = BASE_DIR / config["database"]["path"]
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return str(db_path)
