'''维护终端输入历史，并支持上下方向键浏览及返回尚未提交的草稿。'''

from __future__ import annotations

DEFAULT_LIMIT = 200


class InputHistory:
    '''保存最近的输入条目并限制历史长度。'''

    def __init__(self, entries: list[str] | None = None, limit: int = DEFAULT_LIMIT) -> None:
        '''载入最近的历史记录并初始化导航游标和当前草稿。'''
        self._limit = max(1, limit)
        self._entries: list[str] = list(entries or [])[-self._limit :]
        self._cursor: int | None = None
        self._draft: str = ""

    def entries(self) -> list[str]:
        '''返回历史记录副本，避免调用方修改内部列表。'''
        return list(self._entries)

    def add(self, text: str) -> None:
        '''追加非空且与最近一条不同的输入，并裁剪至配置上限。'''
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
        '''向上浏览历史；首次浏览时先保存当前编辑内容作为草稿。'''
        if not self._entries:
            return draft
        if self._cursor is None:
            self._draft = draft
            self._cursor = len(self._entries) - 1
        elif self._cursor > 0:
            self._cursor -= 1
        return self._entries[self._cursor]

    def down(self) -> str:
        '''向下浏览更新的历史条目，越过末尾时恢复最初草稿。'''
        if self._cursor is None:
            return self._draft
        if self._cursor < len(self._entries) - 1:
            self._cursor += 1
            return self._entries[self._cursor]
        self._cursor = None
        return self._draft

    def reset(self) -> None:
        '''结束历史导航并清除暂存草稿。'''
        self._cursor = None
        self._draft = ""
