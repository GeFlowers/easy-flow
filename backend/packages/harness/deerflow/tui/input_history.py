'未说明'

from __future__ import annotations

DEFAULT_LIMIT = 200


class InputHistory:
    '未说明'
    def __init__(self, entries: list[str] | None = None, limit: int = DEFAULT_LIMIT) -> None:
        '未说明'
        self._limit = max(1, limit)
        self._entries: list[str] = list(entries or [])[-self._limit :]
        self._cursor: int | None = None  # None => not navigating
        self._draft: str = ""

    def entries(self) -> list[str]:
        '未说明'
        return list(self._entries)

    def add(self, text: str) -> None:
        '未说明'
        self._cursor = None
        self._draft = ""
        if not text.strip():
            return
        if self._entries and self._entries[-1] == text:
            return
        self._entries.append(text)
        if len(self._entries) > self._limit:
            self._entries = self._entries[-self._limit :]

    def up(self, draft: str = "") -> str:
        '未说明'
        if not self._entries:
            return draft
        if self._cursor is None:
            self._draft = draft
            self._cursor = len(self._entries) - 1
        elif self._cursor > 0:
            self._cursor -= 1
        return self._entries[self._cursor]

    def down(self) -> str:
        '未说明'
        if self._cursor is None:
            return self._draft
        if self._cursor < len(self._entries) - 1:
            self._cursor += 1
            return self._entries[self._cursor]
        self._cursor = None
        return self._draft

    def reset(self) -> None:
        '未说明'
        self._cursor = None
        self._draft = ""
