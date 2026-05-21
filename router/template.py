from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class TemplateAction:
    kind: str          # 'text', 'image', or 'menu'
    payload: str       # text content or file path


class TemplateMatcher:
    """Substring keyword matcher over three JSON dicts.

    Matches:
      - 关键词回复.json  → TemplateAction(kind='text')
      - 关键词发图.json  → TemplateAction(kind='image')
      - 菜单格式.json    → TemplateAction(kind='menu')
    """

    def __init__(self, replies_path: Path, images_path: Path, menus_path: Path):
        self._replies = self._load(replies_path)
        self._images = self._load(images_path)
        self._menus = self._load(menus_path)

    @staticmethod
    def _load(path: Path) -> dict[str, str]:
        path = Path(path)
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def match(self, text: str) -> list[TemplateAction]:
        actions: list[TemplateAction] = []
        actions.extend(
            TemplateAction("text", reply)
            for kw, reply in self._replies.items()
            if kw in text
        )
        actions.extend(
            TemplateAction("image", path)
            for kw, path in self._images.items()
            if kw in text
        )
        actions.extend(
            TemplateAction("menu", payload)
            for kw, payload in self._menus.items()
            if kw in text
        )
        return actions

    def reload(self) -> None:
        # Re-read all three files (for config hot-reload).
        pass    # Implemented in Phase 3 polish if needed
