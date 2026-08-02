from __future__ import annotations

import json

from services.config import DATA_DIR

TAGS_FILE = DATA_DIR / "image_tags.json"


def _ensure_file() -> None:
    TAGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not TAGS_FILE.exists():
        TAGS_FILE.write_text("{}", encoding="utf-8")


def load_tags() -> dict[str, list[str]]:
    _ensure_file()
    try:
        data = json.loads(TAGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def save_tags(data: dict[str, list[str]]) -> None:
    _ensure_file()
    TAGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def get_tags(image_rel: str) -> list[str]:
    return load_tags().get(image_rel, [])


def set_tags(image_rel: str, tags: list[str]) -> list[str]:
    data = load_tags()
    cleaned = list(dict.fromkeys(t.strip() for t in tags if t.strip()))
    if cleaned:
        data[image_rel] = cleaned
    else:
        data.pop(image_rel, None)
    save_tags(data)
    return cleaned


def remove_tags(image_rel: str) -> None:
    data = load_tags()
    if data.pop(image_rel, None) is not None:
        save_tags(data)


def delete_tag(tag: str) -> int:
    """从所有图片中删除指定标签，返回受影响的图片数。"""
    data = load_tags()
    count = 0
    for rel in list(data):
        if tag in data[rel]:
            data[rel] = [t for t in data[rel] if t != tag]
            if not data[rel]:
                del data[rel]
            count += 1
    if count > 0:
        save_tags(data)
    return count


def get_all_tags() -> list[str]:
    data = load_tags()
    seen: set[str] = set()
    result: list[str] = []
    for tags in data.values():
        for t in tags:
            if t not in seen:
                seen.add(t)
                result.append(t)
    return result
