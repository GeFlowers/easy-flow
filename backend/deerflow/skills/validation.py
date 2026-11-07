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
        return False, f"找不到 {SKILL_MD_FILE}", None

    content = skill_md.read_text(encoding="utf-8")
    parts, error = split_skill_markdown(content)
    if error:
        return False, error, None
    if parts is None:
        return False, "前置元数据格式无效", None
    frontmatter = parts.metadata

    # 拒绝当前规范未定义的元数据字段。
    unexpected_keys = set(frontmatter.keys()) - ALLOWED_FRONTMATTER_PROPERTIES
    if unexpected_keys:
        return False, f"SKILL.md 前置元数据中存在意外的键： {', '.join(sorted(unexpected_keys))}", None

    # 确认名称和描述这两个必填字段存在。
    if "name" not in frontmatter:
        return False, "前置元数据缺少 'name'", None
    if "description" not in frontmatter:
        return False, "前置元数据缺少 'description'", None

    # 校验名称类型、非空性、字符格式和长度限制。
    name = frontmatter.get("name", "")
    if not isinstance(name, str):
        return False, f"名称必须是字符串，实际类型为 {type(name).__name__}", None
    name = name.strip()
    if not name:
        return False, "名称不能为空", None

    # 名称采用小写字母、数字和连字符组成的短横线连接格式。
    if not re.match(r"^[a-z0-9-]+$", name):
        return False, f"Name '{name}' 必须采用连字符命名（仅包含小写字母、数字和连字符）", None
    if name.startswith("-") or name.endswith("-") or "--" in name:
        return False, f"Name '{name}' 不能以连字符开头或结尾，也不能包含连续连字符", None
    if len(name) > 64:
        return False, f"名称过长（{len(name)} 个字符）。最多允许 64 个字符。", None

    # 描述必须为字符串，且不得包含尖括号或超过长度限制。
    description = frontmatter.get("description", "")
    if not isinstance(description, str):
        return False, f"描述必须是字符串，实际类型为 {type(description).__name__}", None
    description = description.strip()
    if description:
        if "<" in description or ">" in description:
            return False, "描述不能包含尖括号（< 或 >）", None
        if len(description) > 1024:
            return False, f"描述过长（{len(description)} 个字符）。最多允许 1024 个字符。", None

    try:
        parse_allowed_tools(frontmatter.get("allowed-tools"), skill_md)
    except ValueError as e:
        return False, str(e).replace(str(skill_md), SKILL_MD_FILE), None

    required_secrets = frontmatter.get("required-secrets")
    if required_secrets is not None and not isinstance(required_secrets, list):
        return False, f"required-secrets 所在文件 {SKILL_MD_FILE} 必须为列表", None

    secrets_autonomous = frontmatter.get("secrets-autonomous")
    if secrets_autonomous is not None and not isinstance(secrets_autonomous, bool):
        return False, f"secrets-autonomous 所在文件 {SKILL_MD_FILE} 必须为布尔值", None

    return True, "技能有效！", name
