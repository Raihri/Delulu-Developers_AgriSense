from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from config import SOURCE_REGISTRY


@lru_cache(maxsize=4)
def load_registry(path: str | Path = SOURCE_REGISTRY) -> dict[str, Any]:
    registry_path = Path(path)
    with registry_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict) or not isinstance(data.get("sources"), list):
        raise ValueError(f"Invalid source registry: {registry_path}")
    return data


def sources_by_id(path: str | Path = SOURCE_REGISTRY) -> dict[str, dict[str, Any]]:
    registry = load_registry(path)
    return {source["id"]: source for source in registry["sources"]}
