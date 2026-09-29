import os
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_yaml(name: str):
    """Load config/<name>. ${ENV_VAR} references are expanded, so personal
    details can live in GitHub Secrets instead of the repo."""
    text = (ROOT / "config" / name).read_text(encoding="utf-8")
    return yaml.safe_load(re.sub(r"\$\{(\w+)\}", lambda m: os.environ.get(m.group(1), ""), text))


def profile() -> dict:
    return load_yaml("profile.yaml")


def companies() -> list[dict]:
    return load_yaml("companies.yaml")["companies"]


def resume() -> dict:
    return load_yaml("resume.yaml")
