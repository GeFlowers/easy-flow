"""测试模块：覆盖本文件定义的回归边界、模拟失败与资源生命周期。"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig
from deerflow.agents.memory.backends.deermem.deermem.core.updater import (
    MemoryUpdater,
    _build_consolidation_section,
    _normalize_memory_update_data,
    _select_consolidation_candidates,
)

# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。


def _memory_config(**overrides: object) -> DeerMemConfig:
    """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
    config = DeerMemConfig()
    for key, value in overrides.items():
        if key == "enabled":
            continue
        setattr(config, key, value)
    return config


def _make_updater(**config_overrides: object) -> MemoryUpdater:
    """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
    return MemoryUpdater(_memory_config(**config_overrides), MagicMock(), None)


def _make_fact(
    fact_id: str,
    content: str = "test content",
    category: str = "knowledge",
    confidence: float = 0.9,
) -> dict:
    """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
    return {
        "id": fact_id,
        "content": content,
        "category": category,
        "confidence": confidence,
        "createdAt": "2026-01-01T00:00:00Z",
        "source": "thread-test",
    }


def _make_memory(facts: list[dict] | None = None) -> dict:
    """测试辅助定义：构造输入或替身，并保持调用方断言依赖的状态、异常和资源边界。"""
    return {
        "version": "1.0",
        "lastUpdated": "",
        "user": {
            "workContext": {"summary": "", "updatedAt": ""},
            "personalContext": {"summary": "", "updatedAt": ""},
            "topOfMind": {"summary": "", "updatedAt": ""},
        },
        "history": {
            "recentMonths": {"summary": "", "updatedAt": ""},
            "earlierContext": {"summary": "", "updatedAt": ""},
            "longTermBackground": {"summary": "", "updatedAt": ""},
        },
        "facts": facts or [],
    }


# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。


class TestSelectConsolidationCandidates:
    """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
    def test_empty_facts(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        memory = _make_memory([])
        config = _memory_config(consolidation_min_facts=8)
        assert _select_consolidation_candidates(memory, config) == {}

    def test_below_threshold(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        memory = _make_memory([_make_fact(f"fact_{i}", category="knowledge") for i in range(5)])
        config = _memory_config(consolidation_min_facts=8)
        assert _select_consolidation_candidates(memory, config) == {}

    def test_at_threshold(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        memory = _make_memory([_make_fact(f"fact_{i}", category="knowledge") for i in range(8)])
        config = _memory_config(consolidation_min_facts=8)
        result = _select_consolidation_candidates(memory, config)
        assert "knowledge" in result
        assert len(result["knowledge"]) == 8

    def test_above_threshold(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        memory = _make_memory([_make_fact(f"fact_{i}", category="knowledge") for i in range(12)])
        config = _memory_config(consolidation_min_facts=8)
        result = _select_consolidation_candidates(memory, config)
        assert "knowledge" in result
        assert len(result["knowledge"]) == 12

    def test_multiple_categories(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        facts = [_make_fact(f"k_{i}", category="knowledge") for i in range(10)] + [_make_fact(f"p_{i}", category="preference") for i in range(9)] + [_make_fact(f"c_{i}", category="context") for i in range(3)]
        memory = _make_memory(facts)
        config = _memory_config(consolidation_min_facts=8)
        result = _select_consolidation_candidates(memory, config)
        assert "knowledge" in result
        assert "preference" in result
        assert "context" not in result  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。

    def test_non_dict_facts_skipped(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        memory = _make_memory(
            [_make_fact(f"fact_{i}", category="knowledge") for i in range(8)] + ["not a dict", 42]  # type: ignore[list-item]
        )
        config = _memory_config(consolidation_min_facts=8)
        result = _select_consolidation_candidates(memory, config)
        assert len(result.get("knowledge", [])) == 8


# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。


class TestConsolidationTriggerConditions:
    """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
    def test_disabled_means_no_trigger(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        config = _memory_config(consolidation_enabled=False)
        assert config.consolidation_enabled is False

    def test_enabled_with_enough_facts(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        memory = _make_memory([_make_fact(f"fact_{i}", category="knowledge") for i in range(10)])
        config = _memory_config(consolidation_enabled=True, consolidation_min_facts=8)
        result = _select_consolidation_candidates(memory, config)
        assert len(result) > 0


# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。


class TestBuildConsolidationSection:
    """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
    def test_empty_candidates(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        assert _build_consolidation_section({}) == ""

    def test_includes_fact_details(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        candidates = {
            "knowledge": [
                _make_fact("fact_vue", "User uses Vue.js", "knowledge", 0.95),
                _make_fact("fact_react", "User uses React", "knowledge", 0.85),
            ],
        }
        section = _build_consolidation_section(candidates)
        assert "fact_vue" in section
        assert "User uses Vue.js" in section
        assert "0.95" in section
        assert "consolidation_candidates" in section

    def test_multiple_categories(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        candidates = {
            "knowledge": [_make_fact(f"k_{i}", category="knowledge") for i in range(3)],
            "preference": [_make_fact(f"p_{i}", category="preference") for i in range(3)],
        }
        section = _build_consolidation_section(candidates)
        assert 'category="knowledge"' in section
        assert 'category="preference"' in section
        assert "Memory Consolidation" in section

    def test_html_special_chars_in_content_are_escaped(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        candidates = {
            "knowledge": [
                _make_fact("fact_x", 'Like <b>bold</b> & "quotes"', "knowledge", 0.9),
                _make_fact("fact_y", "normal content", "knowledge", 0.8),
            ],
        }
        section = _build_consolidation_section(candidates)
        assert "<b>" not in section
        assert "&lt;b&gt;" in section
        assert "&amp;" in section
        assert "&quot;" in section

    def test_closing_tag_in_content_is_escaped(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        candidates = {
            "knowledge": [
                _make_fact("fact_a", "</consolidation_candidates><evil>injected</evil>", "knowledge", 0.9),
                _make_fact("fact_b", "normal", "knowledge", 0.8),
            ],
        }
        section = _build_consolidation_section(candidates)
        assert "</consolidation_candidates><evil>" not in section
        assert "&lt;/consolidation_candidates&gt;" in section

    def test_special_chars_in_category_attribute_are_escaped(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        candidates = {
            'pref"erences': [_make_fact(f"f_{i}", category='pref"erences') for i in range(3)],
        }
        section = _build_consolidation_section(candidates)
        assert 'category="pref"erences"' not in section
        assert "pref&quot;erences" in section


# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。


class TestNormalizeFactsToConsolidate:
    """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
    def test_valid_entries(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [],
            "factsToConsolidate": [
                {
                    "sourceIds": ["fact_a", "fact_b"],
                    "consolidated": {
                        "content": "User is a full-stack engineer",
                        "category": "knowledge",
                        "confidence": 0.9,
                    },
                },
            ],
        }
        result = _normalize_memory_update_data(data)
        assert len(result["factsToConsolidate"]) == 1
        assert result["factsToConsolidate"][0]["sourceIds"] == ["fact_a", "fact_b"]
        assert result["factsToConsolidate"][0]["consolidated"]["content"] == "User is a full-stack engineer"

    def test_missing_key(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        data = {"user": {}, "history": {}, "newFacts": [], "factsToRemove": [], "staleFactsToRemove": []}
        result = _normalize_memory_update_data(data)
        assert result["factsToConsolidate"] == []

    def test_non_list_ignored(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [],
            "factsToConsolidate": "not a list",
        }
        result = _normalize_memory_update_data(data)
        assert result["factsToConsolidate"] == []

    def test_single_source_skipped(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [],
            "factsToConsolidate": [
                {
                    "sourceIds": ["fact_only"],
                    "consolidated": {"content": "should be skipped", "category": "knowledge", "confidence": 0.9},
                },
            ],
        }
        result = _normalize_memory_update_data(data)
        assert result["factsToConsolidate"] == []

    def test_empty_content_skipped(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [],
            "factsToConsolidate": [
                {
                    "sourceIds": ["fact_a", "fact_b"],
                    "consolidated": {"content": "  ", "category": "knowledge", "confidence": 0.9},
                },
            ],
        }
        result = _normalize_memory_update_data(data)
        assert result["factsToConsolidate"] == []

    def test_non_dict_consolidated_skipped(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [],
            "factsToConsolidate": [
                {
                    "sourceIds": ["fact_a", "fact_b"],
                    "consolidated": "just a string",
                },
            ],
        }
        result = _normalize_memory_update_data(data)
        assert result["factsToConsolidate"] == []


# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。


class TestApplyUpdatesConsolidation:
    """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
    def test_consolidation_removes_sources_adds_merged(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        updater = _make_updater(
            max_facts=100,
            consolidation_enabled=True,
            consolidation_min_facts=3,
            consolidation_max_groups_per_cycle=3,
            consolidation_max_sources=8,
        )
        current_memory = _make_memory(
            [
                _make_fact("fact_a", "User uses React", "knowledge", 0.9),
                _make_fact("fact_b", "User uses Python", "knowledge", 0.85),
                _make_fact("fact_c", "User uses PostgreSQL", "knowledge", 0.8),
                _make_fact("fact_keep", "User likes music", "preference", 0.7),
            ]
        )
        update_data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [],
            "factsToConsolidate": [
                {
                    "sourceIds": ["fact_a", "fact_b", "fact_c"],
                    "consolidated": {
                        "content": "Full-stack: React frontend, Python backend, PostgreSQL",
                        "category": "knowledge",
                        "confidence": 0.9,
                    },
                },
            ],
        }

        result = updater._apply_updates(current_memory, update_data)

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        assert len(result["facts"]) == 2
        remaining_ids = {f["id"] for f in result["facts"]}
        assert "fact_keep" in remaining_ids
        assert "fact_a" not in remaining_ids
        assert "fact_b" not in remaining_ids
        assert "fact_c" not in remaining_ids
        consolidated = [f for f in result["facts"] if f.get("source") == "consolidation"]
        assert len(consolidated) == 1
        assert "Full-stack" in consolidated[0]["content"]
        assert consolidated[0]["consolidatedFrom"] == ["fact_a", "fact_b", "fact_c"]

    def test_max_groups_cap(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        updater = _make_updater(
            max_facts=100,
            consolidation_enabled=True,
            consolidation_max_groups_per_cycle=2,  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
            consolidation_max_sources=8,
        )
        facts = [_make_fact(f"f_{i}", f"Fact {i}", "knowledge", 0.8) for i in range(10)]
        current_memory = _make_memory(facts)
        update_data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [],
            "factsToConsolidate": [
                {"sourceIds": ["f_0", "f_1"], "consolidated": {"content": "Group 1", "category": "knowledge", "confidence": 0.8}},
                {"sourceIds": ["f_2", "f_3"], "consolidated": {"content": "Group 2", "category": "knowledge", "confidence": 0.8}},
                {"sourceIds": ["f_4", "f_5"], "consolidated": {"content": "Group 3", "category": "knowledge", "confidence": 0.8}},
            ],
        }

        result = updater._apply_updates(current_memory, update_data)

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        consolidated = [f for f in result["facts"] if f.get("source") == "consolidation"]
        assert len(consolidated) == 2

    def test_nonexistent_source_id_refused(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        updater = _make_updater(
            max_facts=100,
            consolidation_enabled=True,
            consolidation_min_facts=2,
            consolidation_max_sources=8,
        )
        current_memory = _make_memory(
            [
                _make_fact("fact_a", "Fact A", "knowledge", 0.9),
                _make_fact("fact_b", "Fact B", "knowledge", 0.8),
            ]
        )
        update_data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [],
            "factsToConsolidate": [
                {
                    "sourceIds": ["fact_a", "fact_hallucinated"],
                    "consolidated": {"content": "Should not apply", "category": "knowledge", "confidence": 0.9},
                },
            ],
        }

        result = updater._apply_updates(current_memory, update_data)

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        assert len(result["facts"]) == 2

    def test_over_max_sources_refused(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        updater = _make_updater(
            max_facts=100,
            consolidation_enabled=True,
            consolidation_max_sources=5,
        )
        facts = [_make_fact(f"f_{i}", f"Fact {i}", "knowledge", 0.8) for i in range(10)]
        current_memory = _make_memory(facts)
        update_data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [],
            "factsToConsolidate": [
                {
                    "sourceIds": [f"f_{i}" for i in range(10)],  # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
                    "consolidated": {"content": "Over-merged", "category": "knowledge", "confidence": 0.8},
                },
            ],
        }

        result = updater._apply_updates(current_memory, update_data)

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        assert len(result["facts"]) == 10

    def test_double_consume_prevented(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        updater = _make_updater(
            max_facts=100,
            consolidation_enabled=True,
            consolidation_min_facts=3,
            consolidation_max_groups_per_cycle=3,
            consolidation_max_sources=8,
        )
        current_memory = _make_memory(
            [
                _make_fact("fact_a", "A", "knowledge", 0.9),
                _make_fact("fact_b", "B", "knowledge", 0.8),
                _make_fact("fact_c", "C", "knowledge", 0.7),
            ]
        )
        update_data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [],
            "factsToConsolidate": [
                {"sourceIds": ["fact_a", "fact_b"], "consolidated": {"content": "AB", "category": "knowledge", "confidence": 0.9}},
                {"sourceIds": ["fact_b", "fact_c"], "consolidated": {"content": "BC", "category": "knowledge", "confidence": 0.8}},
            ],
        }

        result = updater._apply_updates(current_memory, update_data)

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        consolidated = [f for f in result["facts"] if f.get("source") == "consolidation"]
        assert len(consolidated) == 1
        assert consolidated[0]["content"] == "AB"

    def test_consolidation_with_staleness_and_contradiction(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        updater = _make_updater(
            max_facts=100,
            consolidation_enabled=True,
            consolidation_min_facts=2,
            staleness_max_removals_per_cycle=10,
            consolidation_max_groups_per_cycle=3,
            consolidation_max_sources=8,
        )
        old_date = (datetime.now(UTC) - timedelta(days=200)).isoformat().replace("+00:00", "Z")
        current_memory = _make_memory(
            [
                {"id": "fact_contradicted", "content": "Old claim", "category": "knowledge", "confidence": 0.7, "createdAt": old_date, "source": "test"},
                {"id": "fact_stale", "content": "Stale fact", "category": "knowledge", "confidence": 0.6, "createdAt": old_date, "source": "test"},
                {"id": "fact_a", "content": "React", "category": "knowledge", "confidence": 0.9, "createdAt": old_date, "source": "test"},
                {"id": "fact_b", "content": "Python", "category": "knowledge", "confidence": 0.85, "createdAt": old_date, "source": "test"},
            ]
        )
        update_data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": ["fact_contradicted"],
            "staleFactsToRemove": [{"id": "fact_stale", "reason": "outdated"}],
            "factsToConsolidate": [
                {"sourceIds": ["fact_a", "fact_b"], "consolidated": {"content": "React + Python", "category": "knowledge", "confidence": 0.9}},
            ],
        }

        result = updater._apply_updates(current_memory, update_data)

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        assert len(result["facts"]) == 1
        assert result["facts"][0]["content"] == "React + Python"


# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。


class TestReviewerFindings:
    """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
    def test_duplicate_source_ids_rejected(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [],
            "factsToConsolidate": [
                {
                    "sourceIds": ["fact_a", "fact_a"],
                    "consolidated": {"content": "Rewritten", "category": "knowledge", "confidence": 0.9},
                },
            ],
        }
        result = _normalize_memory_update_data(data)
        assert result["factsToConsolidate"] == [], "duplicate IDs should collapse to 1 and be rejected"

    def test_protected_category_not_selected(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        correction_facts = [_make_fact(f"c_{i}", category="correction") for i in range(10)]
        knowledge_facts = [_make_fact(f"k_{i}", category="knowledge") for i in range(10)]
        memory = _make_memory(correction_facts + knowledge_facts)
        config = _memory_config(consolidation_min_facts=8, consolidation_enabled=True)
        result = _select_consolidation_candidates(memory, config)
        assert "correction" not in result, "protected category must not appear in consolidation candidates"
        assert "knowledge" in result

    def test_count_attribute_capped_at_max_sources(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        big_group = [_make_fact(f"f_{i}", category="knowledge") for i in range(20)]
        candidates = {"knowledge": big_group}
        section = _build_consolidation_section(candidates, max_groups=3, max_sources=8)
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        assert 'count="8"' in section
        assert 'count="20"' not in section

    def test_category_stripped_in_normalization(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [],
            "factsToConsolidate": [
                {
                    "sourceIds": ["fact_a", "fact_b"],
                    "consolidated": {"content": "Merged", "category": "  knowledge  ", "confidence": 0.9},
                },
                {
                    "sourceIds": ["fact_c", "fact_d"],
                    "consolidated": {"content": "Also merged", "category": "   ", "confidence": 0.85},
                },
            ],
        }
        result = _normalize_memory_update_data(data)
        assert result["factsToConsolidate"][0]["consolidated"]["category"] == "knowledge"
        assert result["factsToConsolidate"][1]["consolidated"]["category"] == "context"

    def test_consolidation_runs_after_trim(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        updater = _make_updater(
            max_facts=3,
            consolidation_enabled=True,
            consolidation_min_facts=2,
            fact_confidence_threshold=0.7,
            consolidation_max_groups_per_cycle=3,
            consolidation_max_sources=8,
        )
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        facts = [
            _make_fact("low_a", "Low conf A", "knowledge", 0.71),
            _make_fact("low_b", "Low conf B", "knowledge", 0.71),
            # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
            _make_fact("high_keep", "High conf fact", "preference", 0.99),
        ]
        current_memory = _make_memory(facts)
        update_data = {
            "user": {},
            "history": {},
            "newFacts": [
                # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
                # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
                {"content": "New high 1", "category": "knowledge", "confidence": 0.98},
                {"content": "New high 2", "category": "knowledge", "confidence": 0.97},
            ],
            "factsToRemove": [],
            "staleFactsToRemove": [],
            "factsToConsolidate": [
                {
                    "sourceIds": ["low_a", "low_b"],
                    "consolidated": {"content": "Merged low", "category": "knowledge", "confidence": 0.9},
                },
            ],
        }
        result = updater._apply_updates(current_memory, update_data)

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        ids = {f["id"] for f in result["facts"]}
        contents = {f["content"] for f in result["facts"]}
        assert "Merged low" not in contents, "consolidated fact must not appear when sources were trimmed"
        assert "Low conf A" not in contents, "evicted source must not reappear"
        assert "Low conf B" not in contents, "evicted source must not reappear"
        assert len(result["facts"]) == 3
        assert "high_keep" in ids

    def test_source_error_propagated(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        updater = _make_updater(
            max_facts=100,
            consolidation_enabled=True,
            consolidation_min_facts=2,
            consolidation_max_groups_per_cycle=3,
            consolidation_max_sources=8,
        )
        facts = [
            {**_make_fact("fact_a", "Fact A", "knowledge", 0.9), "sourceError": "Agent used wrong approach"},
            _make_fact("fact_b", "Fact B", "knowledge", 0.85),
        ]
        current_memory = _make_memory(facts)
        update_data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [],
            "factsToConsolidate": [
                {
                    "sourceIds": ["fact_a", "fact_b"],
                    "consolidated": {"content": "Merged AB", "category": "knowledge", "confidence": 0.9},
                },
            ],
        }
        result = updater._apply_updates(current_memory, update_data)

        merged = [f for f in result["facts"] if f.get("source") == "consolidation"]
        assert len(merged) == 1
        assert merged[0].get("sourceError") == "Agent used wrong approach"

    def test_protected_category_rejected_at_apply_time(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        updater = _make_updater(
            max_facts=100,
            consolidation_enabled=True,
            consolidation_min_facts=8,
            consolidation_max_groups_per_cycle=3,
            consolidation_max_sources=8,
        )
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        correction_facts = [{**_make_fact(f"corr_{i}", f"Correction {i}", "correction", 0.95), "sourceError": "wrong approach"} for i in range(3)]
        current_memory = _make_memory(correction_facts)
        update_data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [],
            "factsToConsolidate": [
                {
                    "sourceIds": ["corr_0", "corr_1"],
                    "consolidated": {"content": "Merged corrections", "category": "correction", "confidence": 0.95},
                },
            ],
        }
        result = updater._apply_updates(current_memory, update_data)

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        assert len(result["facts"]) == 3
        ids = {f["id"] for f in result["facts"]}
        assert "corr_0" in ids and "corr_1" in ids and "corr_2" in ids
        assert all(f.get("source") != "consolidation" for f in result["facts"])

    def test_confidence_cap_and_threshold_gate(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        updater = _make_updater(
            max_facts=100,
            consolidation_enabled=True,
            fact_confidence_threshold=0.7,
            consolidation_min_facts=2,
            consolidation_max_groups_per_cycle=3,
            consolidation_max_sources=8,
        )
        facts = [
            _make_fact("fact_a", "Fact A", "knowledge", 0.75),
            _make_fact("fact_b", "Fact B", "knowledge", 0.75),
        ]
        current_memory = _make_memory(facts)

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        update_data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [],
            "factsToConsolidate": [
                {
                    "sourceIds": ["fact_a", "fact_b"],
                    "consolidated": {"content": "Merged", "category": "knowledge", "confidence": 1.0},
                },
            ],
        }
        result = updater._apply_updates(current_memory, update_data)

        merged = [f for f in result["facts"] if f.get("source") == "consolidation"]
        assert len(merged) == 1, "merge should succeed"
        assert merged[0]["confidence"] == 0.75, "confidence must be capped at max source confidence"

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        facts2 = [
            _make_fact("fact_c", "Fact C", "knowledge", 0.65),
            _make_fact("fact_d", "Fact D", "knowledge", 0.60),
        ]
        current_memory2 = _make_memory(facts2)
        update_data2 = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [],
            "factsToConsolidate": [
                {
                    "sourceIds": ["fact_c", "fact_d"],
                    "consolidated": {"content": "Below threshold", "category": "knowledge", "confidence": 1.0},
                },
            ],
        }
        result2 = updater._apply_updates(current_memory2, update_data2)

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        assert len(result2["facts"]) == 2
        assert all(f.get("source") != "consolidation" for f in result2["facts"])

    def test_apply_gate_consolidation_disabled(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        updater = _make_updater(
            max_facts=100,
            consolidation_enabled=False,
            consolidation_max_groups_per_cycle=3,
            consolidation_max_sources=8,
        )
        facts = [
            _make_fact("fact_a", "Fact A", "knowledge", 0.9),
            _make_fact("fact_b", "Fact B", "knowledge", 0.85),
        ]
        current_memory = _make_memory(facts)
        update_data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [],
            "factsToConsolidate": [
                {
                    "sourceIds": ["fact_a", "fact_b"],
                    "consolidated": {"content": "Should not merge", "category": "knowledge", "confidence": 0.9},
                },
            ],
        }
        result = updater._apply_updates(current_memory, update_data)

        assert len(result["facts"]) == 2, "both source facts must survive when consolidation is disabled"
        assert all(f.get("source") != "consolidation" for f in result["facts"])

    def test_consolidation_enabled_defaults_to_false(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        assert DeerMemConfig().consolidation_enabled is False

    def test_null_confidence_renders_consistently_with_cap(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        null_fact = {**_make_fact("fact_null", "null conf fact", "knowledge"), "confidence": None}
        other_fact = _make_fact("fact_b", "normal fact", "knowledge", 0.9)

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        section = _build_consolidation_section({"knowledge": [null_fact, other_fact]})
        assert "0.50" in section, "null confidence must render as 0.50 (coerced default), not 0.00"
        assert "0.00" not in section

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        updater = _make_updater(
            max_facts=100,
            fact_confidence_threshold=0.5,
            consolidation_enabled=True,
            consolidation_min_facts=2,
            consolidation_max_groups_per_cycle=3,
            consolidation_max_sources=8,
        )
        current_memory = _make_memory([null_fact, other_fact])
        update_data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [],
            "factsToConsolidate": [
                {
                    "sourceIds": ["fact_null", "fact_b"],
                    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
                    "consolidated": {"content": "Merged", "category": "knowledge", "confidence": 1.0},
                },
            ],
        }
        result = updater._apply_updates(current_memory, update_data)

        merged = [f for f in result["facts"] if f.get("source") == "consolidation"]
        assert len(merged) == 1, "merge should succeed"
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        assert merged[0]["confidence"] == pytest.approx(0.9)

    def test_consolidated_created_at_tracks_newest_source(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        updater = _make_updater(
            max_facts=100,
            consolidation_enabled=True,
            consolidation_min_facts=2,
            consolidation_max_groups_per_cycle=3,
            consolidation_max_sources=8,
        )
        older_date = "2025-01-01T00:00:00Z"
        newer_date = "2026-03-15T12:00:00Z"
        facts = [
            {**_make_fact("fact_old", "Old fact", "knowledge", 0.9), "createdAt": older_date},
            {**_make_fact("fact_new", "New fact", "knowledge", 0.85), "createdAt": newer_date},
        ]
        current_memory = _make_memory(facts)
        update_data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [],
            "factsToConsolidate": [
                {
                    "sourceIds": ["fact_old", "fact_new"],
                    "consolidated": {"content": "Old and new merged", "category": "knowledge", "confidence": 0.9},
                },
            ],
        }
        result = updater._apply_updates(current_memory, update_data)

        merged = [f for f in result["facts"] if f.get("source") == "consolidation"]
        assert len(merged) == 1
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        assert merged[0]["createdAt"] == newer_date, "createdAt must equal newest source's date"
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        assert "consolidatedAt" in merged[0], "consolidatedAt must be set for auditability"
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        assert merged[0]["consolidatedAt"] > newer_date

    def test_confidence_fallback_to_max_source_when_llm_omits_field(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        updater = _make_updater(
            max_facts=100,
            consolidation_enabled=True,
            consolidation_min_facts=2,
            consolidation_max_groups_per_cycle=3,
            consolidation_max_sources=8,
        )
        facts = [
            _make_fact("fact_a", "Fact A", "knowledge", 0.85),
            _make_fact("fact_b", "Fact B", "knowledge", 0.75),
        ]
        current_memory = _make_memory(facts)
        update_data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [],
            "factsToConsolidate": [
                {
                    "sourceIds": ["fact_a", "fact_b"],
                    # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
                    "consolidated": {"content": "Merged without confidence", "category": "knowledge"},
                },
            ],
        }
        result = updater._apply_updates(current_memory, update_data)

        merged = [f for f in result["facts"] if f.get("source") == "consolidation"]
        assert len(merged) == 1, "merge should succeed"
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        assert merged[0]["confidence"] == pytest.approx(0.85)


# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。


class TestPrepareUpdatePromptConsolidation:
    """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""
    def test_consolidation_section_included_when_triggered(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        updater = _make_updater(
            consolidation_enabled=True,
            consolidation_min_facts=8,
        )
        facts = [_make_fact(f"fact_{i}", f"Knowledge {i}", "knowledge", 0.8) for i in range(10)]
        memory = _make_memory(facts)

        msg = MagicMock()
        msg.type = "human"
        msg.content = "Hello"

        with patch.object(updater, "get_memory_data", return_value=memory):
            result = updater._prepare_update_prompt(
                messages=[msg],
                agent_name=None,
                correction_detected=False,
                reinforcement_detected=False,
            )

        assert result is not None
        _, prompt = result
        assert "Memory Consolidation" in prompt
        assert "consolidation_candidates" in prompt

    def test_consolidation_section_omitted_when_not_triggered(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        updater = _make_updater(
            consolidation_enabled=True,
            consolidation_min_facts=8,
        )
        memory = _make_memory([_make_fact("fact_only", category="knowledge")])

        msg = MagicMock()
        msg.type = "human"
        msg.content = "Hello"

        with patch.object(updater, "get_memory_data", return_value=memory):
            result = updater._prepare_update_prompt(
                messages=[msg],
                agent_name=None,
                correction_detected=False,
                reinforcement_detected=False,
            )

        assert result is not None
        _, prompt = result
        assert "Memory Consolidation" not in prompt

    def test_consolidation_section_omitted_when_disabled(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        updater = _make_updater(
            consolidation_enabled=False,
        )
        facts = [_make_fact(f"fact_{i}", category="knowledge") for i in range(20)]
        memory = _make_memory(facts)

        msg = MagicMock()
        msg.type = "human"
        msg.content = "Hello"

        with patch.object(updater, "get_memory_data", return_value=memory):
            result = updater._prepare_update_prompt(
                messages=[msg],
                agent_name=None,
                correction_detected=False,
                reinforcement_detected=False,
            )

        assert result is not None
        _, prompt = result
        assert "Memory Consolidation" not in prompt


# 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。


class TestStalenessKeyErrorRegression:
    """测试分组：集中定义同一验证边界的测试替身、输入和断言。"""

    def test_stale_candidate_without_id_does_not_raise(self):
        """验证该用例的可观察结果：固定断言、模拟失败分支和资源生命周期边界，防止行为回归。"""
        updater = _make_updater(max_facts=100, staleness_max_removals_per_cycle=10)
        aged = (datetime.now(UTC) - timedelta(days=120)).isoformat().replace("+00:00", "Z")
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        idless_fact = {"content": "User uses Vue.js", "category": "knowledge", "confidence": 0.8, "createdAt": aged}
        keep_fact = {"id": "fact_keep", "content": "User knows Python", "category": "knowledge", "confidence": 0.9, "createdAt": aged, "source": "test"}
        current_memory = _make_memory([keep_fact, idless_fact])
        update_data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [
                {"id": "fact_keep", "reason": "outdated"},
            ],
        }

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        result = updater._apply_updates(current_memory, update_data)

        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        # 说明：该位置固定测试输入、替身、失败分支或资源生命周期的验证边界。
        contents = {f.get("content") for f in result["facts"]}
        assert "User uses Vue.js" in contents
        assert "User knows Python" not in contents
