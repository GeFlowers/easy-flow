'''根据名称和描述建立技能索引，并支持精确选择、必含词过滤及文本匹配。'''

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import cached_property

from deerflow.skills.types import Skill

logger = logging.getLogger(__name__)

MAX_RESULTS = 5


def _compile_catalog_regex(pattern: str) -> re.Pattern[str]:
    '''优先将查询编译为不区分大小写的正则表达式；语法错误时按普通文本匹配。'''
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error:
        return re.compile(re.escape(pattern), re.IGNORECASE)


@dataclass(frozen=True)
class SkillCatalog:
    '''保存不可变的技能集合，并缓存名称集合供提示构建和检索复用。'''

    skills: tuple[Skill, ...]

    @cached_property
    def names(self) -> frozenset[str]:
        '''返回当前目录中所有技能名称的不可变集合。'''
        return frozenset(s.name for s in self.skills)

    def search(self, query: str) -> list[Skill]:
        '''按精确选择、必含名称片段或名称与描述正则匹配技能，最多返回五项。'''
        query = query.strip()
        if not query:
            return []

        if query.startswith("select:"):
            wanted = {n.strip() for n in query[7:].split(",")}
            return [s for s in self.skills if s.name in wanted]

        if query.startswith("+"):
            parts = query[1:].split(None, 1)
            if not parts:
                return []
            required = parts[0].lower()
            candidates = [s for s in self.skills if required in s.name.lower()]
            if len(parts) > 1:
                pattern = _compile_catalog_regex(parts[1])
                candidates.sort(
                    key=lambda s: _catalog_regex_score(pattern, s),
                    reverse=True,
                )
            return candidates[:MAX_RESULTS]

        regex = _compile_catalog_regex(query)
        scored: list[tuple[int, Skill]] = []
        for s in self.skills:
            searchable = f"{s.name} {s.description or ''}"
            if regex.search(searchable):
                scored.append((2 if regex.search(s.name) else 1, s))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [s for _, s in scored][:MAX_RESULTS]


def _catalog_regex_score(pattern: re.Pattern[str], s: Skill) -> int:
    '''统计查询模式在技能名称和描述中的匹配次数，用于候选技能排序。'''
    return len(pattern.findall(f"{s.name} {s.description or ''}"))
