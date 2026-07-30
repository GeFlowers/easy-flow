'未说明'

from typing import get_type_hints

import pytest

from deerflow.agents import thread_state as thread_state_module
from deerflow.agents.thread_state import (
    _SKILL_CONTEXT_MAX_ENTRIES,
    TERMINAL_STATUSES,
    SkillEntry,
    ThreadState,
    merge_artifacts,
    merge_delegations,
    merge_goal,
    merge_sandbox,
    merge_skill_context,
    merge_todos,
    merge_viewed_images,
)
from deerflow.subagents.status_contract import SUBAGENT_STATUS_VALUES


class TestMergeSandbox:
    '未说明'

    def test_none_new_preserves_existing(self):
        '未说明'
        existing = {"sandbox_id": "sandbox-1"}
        assert merge_sandbox(existing, None) == existing

    def test_none_existing_accepts_new(self):
        '未说明'
        new = {"sandbox_id": "sandbox-1"}
        assert merge_sandbox(None, new) == new

    def test_same_sandbox_id_is_idempotent(self):
        '未说明'
        existing = {"sandbox_id": "sandbox-1"}
        new = {"sandbox_id": "sandbox-1"}
        assert merge_sandbox(existing, new) == existing

    def test_both_none_sandbox_id_is_idempotent(self):
        '未说明'
        existing = {"sandbox_id": None}
        new = {"sandbox_id": None}
        assert merge_sandbox(existing, new) == existing

    def test_omitted_sandbox_id_is_idempotent(self):
        '未说明'
        existing = {}
        new = {}
        assert merge_sandbox(existing, new) == existing

    def test_conflicting_sandbox_ids_raise(self):
        '未说明'
        existing = {"sandbox_id": "sandbox-1"}
        new = {"sandbox_id": "sandbox-2"}
        with pytest.raises(ValueError, match="Conflicting sandbox state updates"):
            merge_sandbox(existing, new)


class TestMergeTodos:
    '未说明'

    def test_new_value_overrides_existing(self):
        '未说明'
        existing = [{"id": 1, "text": "old", "done": False}]
        new = [{"id": 1, "text": "old", "done": True}]
        assert merge_todos(existing, new) == new

    def test_none_new_preserves_existing(self):
        '未说明'
        existing = [{"id": 1, "text": "task", "done": False}]
        assert merge_todos(existing, None) == existing

    def test_none_existing_accepts_new(self):
        '未说明'
        new = [{"id": 1, "text": "first todo"}]
        assert merge_todos(None, new) == new

    def test_both_none_returns_none(self):
        '未说明'
        assert merge_todos(None, None) is None

    def test_empty_list_is_explicit_clear(self):
        '未说明'
        existing = [{"id": 1, "text": "task"}]
        assert merge_todos(existing, []) == []


class TestMergeGoal:
    '未说明'

    def test_none_new_preserves_existing(self):
        '未说明'
        existing = {"objective": "ship the feature", "status": "active"}
        assert merge_goal(existing, None) == existing

    def test_none_existing_accepts_new(self):
        '未说明'
        new = {"objective": "ship the feature", "status": "active"}
        assert merge_goal(None, new) == new

    def test_new_value_overrides_existing(self):
        '未说明'
        existing = {"objective": "old", "status": "active"}
        new = {"objective": "new", "status": "active"}
        assert merge_goal(existing, new) == new


class TestMergeArtifacts:
    '未说明'

    def test_dedupes_and_preserves_order(self):
        '未说明'
        assert merge_artifacts(["a", "b"], ["b", "c"]) == ["a", "b", "c"]

    def test_none_new_preserves_existing(self):
        '未说明'
        assert merge_artifacts(["a"], None) == ["a"]

    def test_none_existing_accepts_new(self):
        '未说明'
        assert merge_artifacts(None, ["a"]) == ["a"]


class TestMergeViewedImages:
    '未说明'

    def test_merges_dicts(self):
        '未说明'
        existing = {"k1": {"mime_type": "image/png", "size": 1, "actual_path": "/a"}}
        new = {"k2": {"mime_type": "image/jpeg", "size": 2, "actual_path": "/b"}}
        merged = merge_viewed_images(existing, new)
        assert set(merged.keys()) == {"k1", "k2"}

    def test_empty_dict_clears(self):
        '未说明'
        existing = {"k1": {"mime_type": "image/png", "size": 1, "actual_path": "/a"}}
        assert merge_viewed_images(existing, {}) == {}


class TestMergeDelegations:
    '未说明'

    def test_terminal_statuses_derived_from_status_contract(self):
        '未说明'
        assert TERMINAL_STATUSES == frozenset(SUBAGENT_STATUS_VALUES)
        assert "in_progress" not in TERMINAL_STATUSES

    def test_none_new_preserves_existing(self):
        '未说明'
        existing = [{"id": "a", "status": "completed"}]
        assert merge_delegations(existing, None) == existing

    def test_none_existing_returns_new(self):
        '未说明'
        new = [{"id": "a", "status": "completed"}]
        assert merge_delegations(None, new) == new

    def test_append_new_id_preserves_order(self):
        '未说明'
        existing = [{"id": "a", "status": "completed"}]
        new = [{"id": "b", "status": "completed"}]
        out = merge_delegations(existing, new)
        assert [entry["id"] for entry in out] == ["a", "b"]

    def test_same_id_latest_wins(self):
        '未说明'
        existing = [{"id": "a", "status": "running"}]
        new = [{"id": "a", "status": "completed"}]
        out = merge_delegations(existing, new)
        assert out == [{"id": "a", "status": "completed"}]
        assert len(out) == 1

    def test_same_id_terminal_status_is_not_downgraded(self):
        '未说明'
        existing = [{"id": "a", "status": "completed"}]
        new = [{"id": "a", "status": "in_progress"}]
        out = merge_delegations(existing, new)
        assert out == [{"id": "a", "status": "completed"}]

    def test_same_id_preserves_original_created_at(self):
        '未说明'
        existing = [{"id": "a", "status": "completed", "created_at": "first"}]
        new = [{"id": "a", "status": "completed", "created_at": "second", "result_sha256": "x"}]

        out = merge_delegations(existing, new)

        assert out == [{"id": "a", "status": "completed", "created_at": "first", "result_sha256": "x"}]

    def test_over_cap_keeps_most_recent_entries(self):
        '未说明'
        cap = getattr(thread_state_module, "_DELEGATION_LEDGER_MAX_ENTRIES", None)
        assert isinstance(cap, int)
        existing = [{"id": f"call_{i}", "status": "completed"} for i in range(cap)]
        new = [{"id": "call_new", "status": "completed"}]

        out = merge_delegations(existing, new)

        assert len(out) == cap
        assert out[0]["id"] == "call_1"
        assert out[-1]["id"] == "call_new"


def test_skill_entry_is_a_reference_not_content():
    '未说明'
    assert "description" in SkillEntry.__annotations__
    assert "content" not in SkillEntry.__annotations__


def _skill(path: str, description: str = "desc", loaded_at: int = 0) -> "SkillEntry":
    '未说明'
    name = path.rstrip("/").rsplit("/", 2)[-2] if path.endswith("SKILL.md") else path.rstrip("/").rsplit("/", 1)[-1]
    return {"name": name, "path": path, "description": description, "loaded_at": loaded_at}


class TestMergeSkillContext:
    '未说明'
    def test_new_none_preserves_existing(self):
        '未说明'
        existing = [_skill("/mnt/skills/a/SKILL.md")]
        assert merge_skill_context(existing, None) == existing

    def test_new_none_normalizes_legacy_existing_and_drops_content(self):
        '未说明'
        existing = [
            {
                "name": "legacy",
                "path": "/mnt/skills/public/legacy/SKILL.md",
                "content": "VERBATIM_SKILL_BODY",
                "loaded_at": 3,
            }
        ]

        out = merge_skill_context(existing, None)

        assert out == [
            {
                "name": "legacy",
                "path": "/mnt/skills/public/legacy/SKILL.md",
                "description": "",
                "loaded_at": 3,
            }
        ]
        assert "content" not in out[0]
        assert "VERBATIM_SKILL_BODY" not in repr(out)

    def test_existing_none_returns_new(self):
        '未说明'
        new = [_skill("/mnt/skills/a/SKILL.md")]
        assert merge_skill_context(None, new) == new

    def test_merging_new_path_normalizes_legacy_existing_and_drops_content(self):
        '未说明'
        existing = [
            {
                "name": "legacy",
                "path": "/mnt/skills/public/legacy/SKILL.md",
                "content": "VERBATIM_SKILL_BODY",
                "loaded_at": 3,
            }
        ]
        new = [_skill("/mnt/skills/public/new/SKILL.md")]

        out = merge_skill_context(existing, new)

        assert [entry["path"] for entry in out] == [
            "/mnt/skills/public/legacy/SKILL.md",
            "/mnt/skills/public/new/SKILL.md",
        ]
        assert out[0]["description"] == ""
        assert "content" not in out[0]
        assert "VERBATIM_SKILL_BODY" not in repr(out)

    def test_appends_distinct_paths_in_first_seen_order(self):
        '未说明'
        existing = [_skill("/mnt/skills/a/SKILL.md")]
        new = [_skill("/mnt/skills/b/SKILL.md")]
        out = merge_skill_context(existing, new)
        assert [e["path"] for e in out] == ["/mnt/skills/a/SKILL.md", "/mnt/skills/b/SKILL.md"]

    def test_same_path_later_overwrites_in_place(self):
        '未说明'
        existing = [_skill("/mnt/skills/public/a/SKILL.md", description="old", loaded_at=1)]
        new = [_skill("/mnt/skills/public/a/SKILL.md", description="new", loaded_at=9)]
        out = merge_skill_context(existing, new)
        assert len(out) == 1
        assert out[0]["description"] == "new"
        assert out[0]["loaded_at"] == 9

    def test_over_cap_evicts_oldest_first_seen(self):
        '未说明'
        existing = [_skill(f"/mnt/skills/s{i}/SKILL.md") for i in range(_SKILL_CONTEXT_MAX_ENTRIES)]
        new = [_skill("/mnt/skills/newest/SKILL.md")]
        out = merge_skill_context(existing, new)
        assert len(out) == _SKILL_CONTEXT_MAX_ENTRIES
        assert out[0]["path"] == "/mnt/skills/s1/SKILL.md"
        assert out[-1]["path"] == "/mnt/skills/newest/SKILL.md"

    def test_reloaded_skill_refreshes_recency_before_cap_eviction(self):
        '未说明'
        existing = [_skill(f"/mnt/skills/s{i}/SKILL.md") for i in range(_SKILL_CONTEXT_MAX_ENTRIES)]
        new = [
            _skill("/mnt/skills/s0/SKILL.md", description="refreshed"),
            _skill("/mnt/skills/newest/SKILL.md"),
        ]

        out = merge_skill_context(existing, new)

        assert len(out) == _SKILL_CONTEXT_MAX_ENTRIES
        paths = [entry["path"] for entry in out]
        assert "/mnt/skills/s0/SKILL.md" in paths
        assert "/mnt/skills/s1/SKILL.md" not in paths
        assert paths[-2:] == ["/mnt/skills/s0/SKILL.md", "/mnt/skills/newest/SKILL.md"]
        assert out[-2]["description"] == "refreshed"

    def test_description_is_capped_when_normalizing_legacy_entries(self):
        '未说明'
        existing = [_skill("/mnt/skills/public/huge/SKILL.md", description="x" * 2000)]

        out = merge_skill_context(existing, None)

        assert len(out[0]["description"]) <= 500


class TestThreadStateAnnotations:
    '未说明'

    def test_todos_field_is_wired_to_merge_todos(self):
        '未说明'
        hints = get_type_hints(ThreadState, include_extras=True)
        todos_hint = hints["todos"]
        assert hasattr(todos_hint, "__metadata__"), "ThreadState.todos must be Annotated with a reducer"
        assert merge_todos in todos_hint.__metadata__, "ThreadState.todos must be wired to merge_todos reducer (see #3123)"

    def test_goal_field_is_wired_to_merge_goal(self):
        '未说明'
        hints = get_type_hints(ThreadState, include_extras=True)
        goal_hint = hints["goal"]
        assert hasattr(goal_hint, "__metadata__"), "ThreadState.goal must be Annotated with a reducer"
        assert merge_goal in goal_hint.__metadata__, "ThreadState.goal must be wired to merge_goal reducer"

    def test_artifacts_field_is_wired_to_merge_artifacts(self):
        '未说明'
        hints = get_type_hints(ThreadState, include_extras=True)
        assert merge_artifacts in hints["artifacts"].__metadata__

    def test_sandbox_field_is_wired_to_merge_sandbox(self):
        '未说明'
        hints = get_type_hints(ThreadState, include_extras=True)
        assert merge_sandbox in hints["sandbox"].__metadata__

    def test_delegations_field_is_wired_to_merge_delegations(self):
        '未说明'
        hints = get_type_hints(ThreadState, include_extras=True)
        assert merge_delegations in hints["delegations"].__metadata__

    def test_summary_text_field_exists(self):
        '未说明'
        hints = get_type_hints(ThreadState, include_extras=True)
        assert "summary_text" in hints

    def test_skill_context_field_is_wired_to_merge_skill_context(self):
        '未说明'
        hints = get_type_hints(ThreadState, include_extras=True)
        assert merge_skill_context in hints["skill_context"].__metadata__
