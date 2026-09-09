"""桌面应用非敏感偏好设置。"""

from __future__ import annotations

import json
from pathlib import Path

SETTINGS_FILENAME = "settings.json"
LAST_INPUT_DIRECTORY_KEY = "lastInputDirectory"


def load_last_input_directory(cache_directory: Path) -> Path | None:
    """读取上一次有效的输入目录；无效缓存应当静默失效。"""

    settings_path = cache_directory / SETTINGS_FILENAME
    try:
        payload = json.loads(settings_path.read_text(encoding="utf-8"))
        raw_path = payload.get(LAST_INPUT_DIRECTORY_KEY)
        if not isinstance(raw_path, str) or not raw_path.strip():
            return None
        selected = Path(raw_path).expanduser().resolve()
        return selected if selected.is_dir() else None
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def save_last_input_directory(cache_directory: Path, selected: Path | str) -> Path:
    """以原子替换方式保存上一次选择的有效输入目录。"""

    normalized = Path(selected).expanduser().resolve()
    if not normalized.is_dir():
        raise ValueError(f"输入目录不存在或不是目录：{normalized}")

    cache_directory.mkdir(parents=True, exist_ok=True)
    settings_path = cache_directory / SETTINGS_FILENAME
    temporary_path = cache_directory / f".{SETTINGS_FILENAME}.tmp"
    payload = {LAST_INPUT_DIRECTORY_KEY: str(normalized)}
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(settings_path)
    return normalized
