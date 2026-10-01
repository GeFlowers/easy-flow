'''校验技能说明文件的元数据字段、命名规则和工具权限声明。'''

import re
from pathlib import Path

from deerflow.skills.frontmatter import ALLOWED_FRONTMATTER_PROPERTIES, split_skill_markdown
from deerflow.skills.parser import parse_allowed_tools
from deerflow.skills.types import SKILL_MD_FILE


def _validate_skill_frontmatter(skill_dir: Path) -> tuple[bool, str, str | None]:
    '''校验技能目录中的 ``SKILL.md`` 元数据，并返回校验状态、原因和技能名。'''
    skill_md = skill_dir / SKILL_MD_FILE
    if not skill_md.exists():
        return False, f"{SKILL_MD_FILE} not found", None

    content = skill_md.read_text(encoding="utf-8")
    parts, error = split_skill_markdown(content)
    if error:
        return False, error, None
    if parts is None:
        return False, "Invalid frontmatter format", None
    frontmatter = parts.metadata

    # 拒绝当前规范未定义的元数据字段。
    unexpected_keys = set(frontmatter.keys()) - ALLOWED_FRONTMATTER_PROPERTIES
    if unexpected_keys:
        return False, f"Unexpected key(s) in SKILL.md frontmatter: {', '.join(sorted(unexpected_keys))}", None

    # 确认名称和描述这两个必填字段存在。
    if "name" not in frontmatter:
        return False, "Missing 'name' in frontmatter", None
    if "description" not in frontmatter:
        return False, "Missing 'description' in frontmatter", None

    # 校验名称类型、非空性、字符格式和长度限制。
    name = frontmatter.get("name", "")
    if not isinstance(name, str):
        return False, f"Name must be a string, got {type(name).__name__}", None
    name = name.strip()
    if not name:
        return False, "Name cannot be empty", None

    # 名称采用小写字母、数字和连字符组成的 kebab-case 格式。
    if not re.match(r"^[a-z0-9-]+$", name):
        return False, f"Name '{name}' should be hyphen-case (lowercase letters, digits, and hyphens only)", None
    if name.startswith("-") or name.endswith("-") or "--" in name:
        return False, f"Name '{name}' cannot start/end with hyphen or contain consecutive hyphens", None
    if len(name) > 64:
        return False, f"Name is too long ({len(name)} characters). Maximum is 64 characters.", None

    # 描述必须为字符串，且不得包含尖括号或超过长度限制。
    description = frontmatter.get("description", "")
    if not isinstance(description, str):
        return False, f"Description must be a string, got {type(description).__name__}", None
    description = description.strip()
    if description:
        if "<" in description or ">" in description:
            return False, "Description cannot contain angle brackets (< or >)", None
        if len(description) > 1024:
            return False, f"Description is too long ({len(description)} characters). Maximum is 1024 characters.", None

    try:
        parse_allowed_tools(frontmatter.get("allowed-tools"), skill_md)
    except ValueError as e:
        return False, str(e).replace(str(skill_md), SKILL_MD_FILE), None

    required_secrets = frontmatter.get("required-secrets")
    if required_secrets is not None and not isinstance(required_secrets, list):
        return False, f"required-secrets in {SKILL_MD_FILE} must be a list", None

    secrets_autonomous = frontmatter.get("secrets-autonomous")
    if secrets_autonomous is not None and not isinstance(secrets_autonomous, bool):
        return False, f"secrets-autonomous in {SKILL_MD_FILE} must be a boolean", None

    return True, "Skill is valid!", name
