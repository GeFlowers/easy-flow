'未说明'

from __future__ import annotations

import logging
from pathlib import Path

from deerflow.skills.parser import parse_skill_file

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_skill(tmp_path: Path, front_matter: str, body: str = "# My Skill\n") -> Path:
    '未说明'
    skill_dir = tmp_path / "my-skill"
    skill_dir.mkdir()
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(f"---\n{front_matter}\n---\n{body}", encoding="utf-8")
    return skill_file


# ---------------------------------------------------------------------------
# Basic parsing
# ---------------------------------------------------------------------------


def test_parse_plain_name(tmp_path):
    '未说明'
    skill_file = _write_skill(tmp_path, "name: my-skill\ndescription: A test skill")
    skill = parse_skill_file(skill_file, category="custom")
    assert skill is not None
    assert skill.name == "my-skill"


def test_parse_quoted_name_no_quotes_in_result(tmp_path):
    '未说明'
    skill_file = _write_skill(tmp_path, 'name: "my-skill"\ndescription: A test skill')
    skill = parse_skill_file(skill_file, category="custom")
    assert skill is not None
    assert skill.name == "my-skill", f"Expected 'my-skill', got {skill.name!r}"


def test_parse_single_quoted_name(tmp_path):
    '未说明'
    skill_file = _write_skill(tmp_path, "name: 'my-skill'\ndescription: A test skill")
    skill = parse_skill_file(skill_file, category="custom")
    assert skill is not None
    assert skill.name == "my-skill"


def test_parse_description_returned(tmp_path):
    '未说明'
    skill_file = _write_skill(tmp_path, "name: my-skill\ndescription: Does amazing things")
    skill = parse_skill_file(skill_file, category="custom")
    assert skill is not None
    assert skill.description == "Does amazing things"


def test_parse_multiline_description(tmp_path):
    '未说明'
    front_matter = "name: my-skill\ndescription: >\n  A folded\n  description"
    skill_file = _write_skill(tmp_path, front_matter)
    skill = parse_skill_file(skill_file, category="custom")
    assert skill is not None
    assert "folded" in skill.description


def test_parse_license_field(tmp_path):
    '未说明'
    skill_file = _write_skill(tmp_path, "name: my-skill\ndescription: Test\nlicense: MIT")
    skill = parse_skill_file(skill_file, category="custom")
    assert skill is not None
    assert skill.license == "MIT"


def test_parse_missing_allowed_tools_returns_none(tmp_path):
    '未说明'
    skill_file = _write_skill(tmp_path, "name: my-skill\ndescription: Test")
    skill = parse_skill_file(skill_file, category="custom")
    assert skill is not None
    assert skill.allowed_tools is None


def test_parse_allowed_tools_list(tmp_path):
    '未说明'
    skill_file = _write_skill(tmp_path, 'name: my-skill\ndescription: Test\nallowed-tools: ["bash", "read_file"]')
    skill = parse_skill_file(skill_file, category="custom")
    assert skill is not None
    assert skill.allowed_tools == ("bash", "read_file")


def test_parse_empty_allowed_tools_list(tmp_path):
    '未说明'
    skill_file = _write_skill(tmp_path, "name: my-skill\ndescription: Test\nallowed-tools: []")
    skill = parse_skill_file(skill_file, category="custom")
    assert skill is not None
    assert skill.allowed_tools == ()


def test_parse_invalid_allowed_tools_returns_none(tmp_path):
    '未说明'
    skill_file = _write_skill(tmp_path, "name: my-skill\ndescription: Test\nallowed-tools: bash")
    skill = parse_skill_file(skill_file, category="custom")
    assert skill is None


def test_parse_missing_name_returns_none(tmp_path):
    '未说明'
    skill_file = _write_skill(tmp_path, "description: A test skill")
    skill = parse_skill_file(skill_file, category="custom")
    assert skill is None


def test_parse_missing_description_returns_none(tmp_path):
    '未说明'
    skill_file = _write_skill(tmp_path, "name: my-skill")
    skill = parse_skill_file(skill_file, category="custom")
    assert skill is None


def test_parse_no_front_matter_returns_none(tmp_path):
    '未说明'
    skill_dir = tmp_path / "no-fm"
    skill_dir.mkdir()
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text("# No front matter here\n", encoding="utf-8")
    skill = parse_skill_file(skill_file, category="public")
    assert skill is None


def test_parse_invalid_yaml_returns_none(tmp_path):
    '未说明'
    skill_file = _write_skill(tmp_path, "name: [unclosed")
    skill = parse_skill_file(skill_file, category="custom")
    assert skill is None


def test_parse_category_stored(tmp_path):
    '未说明'
    skill_file = _write_skill(tmp_path, "name: my-skill\ndescription: Test")
    skill = parse_skill_file(skill_file, category="public")
    assert skill is not None
    assert skill.category == "public"


def test_parse_nonexistent_file_returns_none(tmp_path):
    '未说明'
    skill = parse_skill_file(tmp_path / "ghost" / "SKILL.md", category="custom")
    assert skill is None


# ---------------------------------------------------------------------------
# Friendly YAML error reporting
# ---------------------------------------------------------------------------


def test_parse_unquoted_colon_value_logs_line_and_hint(tmp_path, caplog):
    '未说明'

    # The description value is intentionally long enough to trigger
    # PyYAML's own '...' truncation in the rendered str(exc); our hint
    # must echo the *full* value regardless.
    long_value = "StarRun collector: progress, errors, tables out, plus assorted diagnostic notes"
    front_matter = f"name: collect-startrun\ndescription: {long_value}"
    skill_file = _write_skill(tmp_path, front_matter)

    with caplog.at_level(logging.ERROR, logger="deerflow.skills.parser"):
        skill = parse_skill_file(skill_file, category="custom")

    assert skill is None
    combined = "\n".join(rec.getMessage() for rec in caplog.records)
    assert "Invalid YAML front-matter" in combined

    # 1. File-line, not front-matter-line. `description` is the 2nd line
    #    of the front-matter body, which is line 3 of the file (line 1
    #    is the leading `---` fence). Before this PR the log said
    #    `line 2`, which sent authors to the wrong row.
    assert f"line 3: description: {long_value}" in combined

    # 2. The full value is preserved -- PyYAML's own message truncates
    #    long values with '...', so the presence of the un-truncated tail
    #    proves we are reading the source line ourselves, not echoing
    #    PyYAML's snippet.
    assert "plus assorted diagnostic notes" in combined
    assert "..." not in [line for line in combined.splitlines() if line.startswith("  line ")][0]

    # 3. The copy-pasteable quoting hint is the actually-new diagnostic.
    assert f'hint: values containing ":" must be quoted, e.g. description: "{long_value}"' in combined


def test_parse_unquoted_colon_value_preserves_nested_key_indent(tmp_path, caplog):
    '未说明'

    # A two-space-indented nested key triggers the same scanner error,
    # but its hint must keep the indentation.
    front_matter = "name: nested-skill\nmetadata:\n  author: Jane: Doe"
    skill_file = _write_skill(tmp_path, front_matter)

    with caplog.at_level(logging.ERROR, logger="deerflow.skills.parser"):
        skill = parse_skill_file(skill_file, category="custom")

    assert skill is None
    combined = "\n".join(rec.getMessage() for rec in caplog.records)
    # Two leading spaces in front of `author` are preserved.
    assert 'hint: values containing ":" must be quoted, e.g.   author: "Jane: Doe"' in combined


def test_parse_unrelated_yaml_error_omits_quoting_hint(tmp_path, caplog):
    '未说明'

    # Unclosed flow sequence is a scanner error of a different shape; the
    # quoting hint would be misleading and must be suppressed.
    skill_file = _write_skill(tmp_path, "name: [unclosed\ndescription: x")

    with caplog.at_level(logging.ERROR, logger="deerflow.skills.parser"):
        skill = parse_skill_file(skill_file, category="custom")

    assert skill is None
    combined = "\n".join(rec.getMessage() for rec in caplog.records)
    assert "Invalid YAML front-matter" in combined
    assert "hint:" not in combined


def test_parse_valid_skill_emits_no_error_log(tmp_path, caplog):
    '未说明'

    skill_file = _write_skill(tmp_path, 'name: ok-skill\ndescription: "Foo: bar"')

    with caplog.at_level(logging.ERROR, logger="deerflow.skills.parser"):
        skill = parse_skill_file(skill_file, category="custom")

    assert skill is not None
    assert skill.description == "Foo: bar"
    assert not caplog.records, "valid SKILL.md must not log errors"


def test_parse_unquoted_colon_value_escapes_backslashes_in_hint(tmp_path, caplog):
    '未说明'

    # The second ``: `` (after ``path``) is what trips PyYAML's
    # "mapping values are not allowed here"; the ``C:\Temp`` segment
    # carries the backslash that the hint must escape.
    front_matter = "name: path-skill\ndescription: Windows path: C:\\Temp"
    skill_file = _write_skill(tmp_path, front_matter)

    with caplog.at_level(logging.ERROR, logger="deerflow.skills.parser"):
        skill = parse_skill_file(skill_file, category="custom")

    assert skill is None
    combined = "\n".join(rec.getMessage() for rec in caplog.records)
    assert r'description: "Windows path: C:\\Temp"' in combined


def test_parse_unquoted_colon_value_escapes_regex_in_hint(tmp_path, caplog):
    '未说明'

    front_matter = "name: regex-skill\ndescription: match: \\d+ digits"
    skill_file = _write_skill(tmp_path, front_matter)

    with caplog.at_level(logging.ERROR, logger="deerflow.skills.parser"):
        skill = parse_skill_file(skill_file, category="custom")

    assert skill is None
    combined = "\n".join(rec.getMessage() for rec in caplog.records)
    assert r'description: "match: \\d+ digits"' in combined
