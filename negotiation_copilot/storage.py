"""Local persistence helpers rooted at a caller-supplied directory.

Never uses browser storage (CLAUDE.md "Never do"); every caller passes the
directory it wants to root under, so this module has no hidden global state
and callers use `config.app_data_dir` at the call site rather than here.
"""

import json
from pathlib import Path
from typing import Any


def _cache_path(base_dir: Path, namespace: str, key: str) -> Path:
    return base_dir / "cache" / namespace / f"{key}.json"


def cache_get(base_dir: Path, namespace: str, key: str) -> Any | None:
    path = _cache_path(base_dir, namespace, key)
    if not path.exists():
        return None
    return json.loads(path.read_text())


def cache_set(base_dir: Path, namespace: str, key: str, value: Any) -> None:
    path = _cache_path(base_dir, namespace, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
