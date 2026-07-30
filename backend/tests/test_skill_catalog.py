'未说明'

from pathlib import Path

import pytest

from deerflow.skills.catalog import MAX_RESULTS, SkillCatalog
from deerflow.skills.types import Skill, SkillCategory

# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_skill(
    name: str,
    description: str = "A skill",
    category: SkillCategory = SkillCategory.PUBLIC,
    allowed_tools: tuple[str, ...] | None = None,
) -> Skill:
    '未说明'
    base = Path("/mnt/skills") / category.value / name
    return Skill(
        name=name,
        description=description,
        license=None,
        skill_dir=base,
        skill_file=base / "SKILL.md",
        relative_path=Path(name),
        category=category,
        allowed_tools=allowed_tools,
        enabled=True,
    )


@pytest.fixture
def sample_skills() -> list[Skill]:
    '未说明'
    return [
        _make_skill("data-analysis", "Analyze data with Python, pandas, jupyter"),
        _make_skill("deep-research", "Conduct multi-source research with fact-checking"),
        _make_skill("chart-visualization", "Visualize data with interactive charts"),
        _make_skill("podcast-generation", "Generate podcast scripts and audio"),
        _make_skill("music-generation", "Generate music compositions"),
        _make_skill("video-generation", "Generate video from text prompts"),
        _make_skill("image-generation", "Generate images from descriptions"),
        _make_skill("ppt-generation", "Generate PowerPoint presentations"),
        _make_skill("custom-analyzer", "Custom data analyzer", category=SkillCategory.CUSTOM),
    ]


@pytest.fixture
def catalog(sample_skills: list[Skill]) -> SkillCatalog:
    '未说明'
    return SkillCatalog(tuple(sample_skills))


# ── Name property ─────────────────────────────────────────────────────────────


def test_names_returns_frozenset(catalog: SkillCatalog):
    '未说明'
    assert isinstance(catalog.names, frozenset)


def test_names_contains_all_skills(catalog: SkillCatalog, sample_skills: list[Skill]):
    '未说明'
    expected = {s.name for s in sample_skills}
    assert catalog.names == expected


def test_empty_catalog_names():
    '未说明'
    catalog = SkillCatalog(())
    assert catalog.names == frozenset()


# ── Exact selection (select:) ─────────────────────────────────────────────────


def test_select_single(catalog: SkillCatalog):
    '未说明'
    result = catalog.search("select:data-analysis")
    assert len(result) == 1
    assert result[0].name == "data-analysis"


def test_select_multiple(catalog: SkillCatalog):
    '未说明'
    result = catalog.search("select:data-analysis,deep-research")
    names = {s.name for s in result}
    assert names == {"data-analysis", "deep-research"}


def test_select_nonexistent(catalog: SkillCatalog):
    '未说明'
    result = catalog.search("select:nonexistent-skill")
    assert result == []


def test_select_partial_match(catalog: SkillCatalog):
    '未说明'
    result = catalog.search("select:data-analysis,nonexistent")
    assert len(result) == 1
    assert result[0].name == "data-analysis"


def test_select_returns_all_requested(catalog: SkillCatalog, sample_skills: list[Skill]):
    '未说明'
    all_names = ",".join(sorted(catalog.names))
    result = catalog.search(f"select:{all_names}")
    assert len(result) == len(sample_skills)


# ── Required-prefix search (+) ────────────────────────────────────────────────


def test_required_prefix_filters_by_name(catalog: SkillCatalog):
    '未说明'
    result = catalog.search("+podcast")
    assert all("podcast" in s.name for s in result)


def test_required_prefix_with_ranking(catalog: SkillCatalog):
    '未说明'
    result = catalog.search("+gen generation")
    assert all("gen" in s.name for s in result)


def test_required_prefix_bare_plus(catalog: SkillCatalog):
    '未说明'
    result = catalog.search("+")
    assert result == []


def test_required_prefix_no_match(catalog: SkillCatalog):
    '未说明'
    result = catalog.search("+zzz_nonexistent")
    assert result == []


# ── Free-text regex search ────────────────────────────────────────────────────


def test_keyword_matches_name(catalog: SkillCatalog):
    '未说明'
    result = catalog.search("podcast")
    assert any(s.name == "podcast-generation" for s in result)


def test_keyword_matches_description(catalog: SkillCatalog):
    '未说明'
    result = catalog.search("pandas")
    assert any(s.name == "data-analysis" for s in result)


def test_name_match_scores_higher_than_description(catalog: SkillCatalog):
    '未说明'
    # 'data-analysis' name matches 'data', description also matches 'data'
    # 'deep-research' description matches 'data' (no, it doesn't)
    # Let's use 'chart' — matches chart-visualization by name
    result = catalog.search("chart")
    assert result[0].name == "chart-visualization"


def test_regex_case_insensitive(catalog: SkillCatalog):
    '未说明'
    result_lower = catalog.search("data")
    result_upper = catalog.search("DATA")
    assert {s.name for s in result_lower} == {s.name for s in result_upper}


def test_invalid_regex_falls_back_to_literal(catalog: SkillCatalog):
    '未说明'
    result = catalog.search("(invalid")
    # Should not raise; may or may not match anything
    assert isinstance(result, list)


def test_empty_query(catalog: SkillCatalog):
    '未说明'
    result = catalog.search("")
    assert result == []


def test_whitespace_only_query(catalog: SkillCatalog):
    '未说明'
    result = catalog.search("   ")
    assert result == []


def test_max_results_cap(catalog: SkillCatalog):
    '未说明'
    # 'generation' matches many descriptions
    result = catalog.search("generation")
    assert len(result) <= MAX_RESULTS


# ── Edge cases ────────────────────────────────────────────────────────────────


def test_frozen_catalog_is_hashable(catalog: SkillCatalog):
    '未说明'
    assert hash(catalog) is not None


def test_names_cached_property_stable(catalog: SkillCatalog):
    '未说明'
    assert catalog.names is catalog.names
