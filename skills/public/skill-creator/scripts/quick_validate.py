#!/usr/bin/env python3
'''
技能目录快速校验脚本，提供最基本的结构检查。
'''

import re
import sys
from pathlib import Path

import yaml

MAX_SKILL_NAME_LENGTH = 64


def validate_skill(skill_path):
    '''检查技能目录及其必需文件是否符合基本结构要求。'''
    skill_path = Path(skill_path)

    skill_md = skill_path / "SKILL.md"
    if not skill_md.exists():
        return False, "未找到 SKILL.md"

    content = skill_md.read_text(encoding="utf-8")
    if not content.startswith("---"):
        return False, "未找到 YAML 前置信息"

    match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return False, "前置信息格式无效"

    frontmatter_text = match.group(1)

    try:
        frontmatter = yaml.safe_load(frontmatter_text)
        if not isinstance(frontmatter, dict):
            return False, "前置信息必须是 YAML 字典"
    except yaml.YAMLError as e:
        return False, f"前置信息中的 YAML 无效： {e}"

    allowed_properties = {"name", "description", "license", "allowed-tools", "metadata"}

    unexpected_keys = set(frontmatter.keys()) - allowed_properties
    if unexpected_keys:
        allowed = ", ".join(sorted(allowed_properties))
        unexpected = ", ".join(sorted(unexpected_keys))
        return (
            False,
            f"SKILL.md 前置信息包含未知字段：{unexpected}。允许字段：{allowed}",
        )

    if "name" not in frontmatter:
        return False, "前置信息缺少 name"
    if "description" not in frontmatter:
        return False, "前置信息缺少 description"

    name = frontmatter.get("name", "")
    if not isinstance(name, str):
        return False, f"name 必须是字符串，实际为 {type(name).__name__}"
    name = name.strip()
    if name:
        if not re.match(r"^[a-z0-9-]+$", name):
            return (
                False,
                f"名称 '{name}' 必须为小写连字符格式，只允许小写字母、数字和连字符",
            )
        if name.startswith("-") or name.endswith("-") or "--" in name:
            return (
                False,
                f"名称 '{name}' 不能以连字符开头或结尾，也不能包含连续连字符",
            )
        if len(name) > MAX_SKILL_NAME_LENGTH:
            return (
                False,
                f"名称过长（{len(name)} 个字符）。"
                f"最多允许 {MAX_SKILL_NAME_LENGTH} 个字符。",
            )

    description = frontmatter.get("description", "")
    if not isinstance(description, str):
        return False, f"description 必须是字符串，实际为 {type(description).__name__}"
    description = description.strip()
    if description.startswith("[TODO:"):
        return False, "描述包含未完成的 TODO 占位内容"
    if description:
        if "<" in description or ">" in description:
            return False, "描述不能包含尖括号（< 或 >）"
        if len(description) > 1024:
            return (
                False,
                f"描述过长（{len(description)} 个字符），最多允许 1024 个。",
            )

    body = content[match.end() :]
    fence_marker = None
    fence_length = 0
    for line in body.splitlines():
        fence = re.match(r"^[ \t]*(?:(?:[-+*]|\d+[.)])[ \t]+)?(`{3,}|~{3,})(.*)$", line)
        if fence:
            marker = fence.group(1)
            if fence_marker is None:
                fence_marker = marker[0]
                fence_length = len(marker)
            elif (
                marker[0] == fence_marker
                and len(marker) >= fence_length
                and not fence.group(2).strip()
            ):
                fence_marker = None
                fence_length = 0
            continue

        if fence_marker is None and re.fullmatch(
            r"[ ]{0,3}\[TODO:[^\n]*\][ \t]*", line
        ):
            return False, "技能说明包含未完成的 TODO 占位内容"

    return True, "技能验证通过！"


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("用法：python quick_validate.py <技能目录>")
        sys.exit(1)

    valid, message = validate_skill(sys.argv[1])
    print(message)
    sys.exit(0 if valid else 1)
