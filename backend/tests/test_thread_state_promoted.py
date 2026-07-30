'未说明'
from deerflow.agents.thread_state import merge_promoted


def test_merge_promoted_preserves_existing_when_new_is_none():
    '未说明'
    existing = {"catalog_hash": "abc", "names": ["search"]}

    assert merge_promoted(existing, None) is existing


def test_merge_promoted_preserves_existing_when_new_is_empty_dict():
    '未说明'
    existing = {"catalog_hash": "abc", "names": ["search"]}

    assert merge_promoted(existing, {}) is existing


def test_merge_promoted_replaces_none_existing_with_deduplicated_new_names():
    '未说明'
    result = merge_promoted(None, {"catalog_hash": "abc", "names": ["search", "search", "fetch"]})

    assert result == {"catalog_hash": "abc", "names": ["search", "fetch"]}


def test_merge_promoted_replaces_when_catalog_hash_changes():
    '未说明'
    existing = {"catalog_hash": "abc", "names": ["old"]}

    result = merge_promoted(existing, {"catalog_hash": "def", "names": ["new", "new", "old"]})

    assert result == {"catalog_hash": "def", "names": ["new", "old"]}


def test_merge_promoted_unions_names_when_catalog_hash_matches():
    '未说明'
    existing = {"catalog_hash": "abc", "names": ["search", "fetch"]}

    result = merge_promoted(existing, {"catalog_hash": "abc", "names": ["fetch", "scrape"]})

    assert result == {"catalog_hash": "abc", "names": ["search", "fetch", "scrape"]}


def test_merge_promoted_replaces_malformed_existing_without_crash():
    # A forward-incompatible / externally-injected persisted state could lack
    # catalog_hash; the reducer must treat it as a mismatch and replace, not crash.
    '未说明'
    result = merge_promoted({"names": ["stale"]}, {"catalog_hash": "abc", "names": ["search"]})

    assert result == {"catalog_hash": "abc", "names": ["search"]}
