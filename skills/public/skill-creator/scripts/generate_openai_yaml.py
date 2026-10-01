#!/usr/bin/env python3
'''
为技能目录生成 agents/openai.yaml 文件。

用法：
    generate_openai_yaml.py <技能目录> [--name <技能名称>] [--interface 字段=值]
'''

import argparse
import re
import sys
from pathlib import Path

ACRONYMS = {
    "GH",
    "MCP",
    "API",
    "CI",
    "CLI",
    "LLM",
    "PDF",
    "PR",
    "UI",
    "URL",
    "SQL",
}

BRANDS = {
    "openai": "OpenAI",
    "openapi": "OpenAPI",
    "github": "GitHub",
    "pagerduty": "PagerDuty",
    "datadog": "DataDog",
    "sqlite": "SQLite",
    "fastapi": "FastAPI",
}

SMALL_WORDS = {"and", "or", "to", "up", "with"}

ALLOWED_INTERFACE_KEYS = {
    "display_name",
    "short_description",
    "icon_small",
    "icon_large",
    "brand_color",
    "default_prompt",
}


def yaml_quote(value):
    '''转义 YAML 字符串中的特殊字符，并以双引号包裹后返回。'''
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def format_display_name(skill_name):
    '''将技能名称转换为界面展示名称，并保留常见缩写、品牌名和小词写法。'''
    words = [word for word in skill_name.split("-") if word]
    formatted = []
    for index, word in enumerate(words):
        lower = word.lower()
        upper = word.upper()
        if upper in ACRONYMS:
            formatted.append(upper)
            continue
        if lower in BRANDS:
            formatted.append(BRANDS[lower])
            continue
        if index > 0 and lower in SMALL_WORDS:
            formatted.append(lower)
            continue
        formatted.append(word.capitalize())
    return " ".join(formatted)


def generate_short_description(display_name):
    '''根据展示名称生成符合界面长度限制的英文技能简介。'''
    description = f"Help with {display_name} tasks"

    if len(description) < 25:
        description = f"Help with {display_name} tasks and workflows"
    if len(description) < 25:
        description = f"Help with {display_name} tasks with guidance"

    if len(description) > 64:
        description = f"Help with {display_name}"
    if len(description) > 64:
        description = f"{display_name} helper"
    if len(description) > 64:
        description = f"{display_name} tools"
    if len(description) > 64:
        suffix = " helper"
        max_name_length = 64 - len(suffix)
        trimmed = display_name[:max_name_length].rstrip()
        description = f"{trimmed}{suffix}"
    if len(description) > 64:
        description = description[:64].rstrip()

    if len(description) < 25:
        description = f"{description} workflows"
        if len(description) > 64:
            description = description[:64].rstrip()

    return description


def read_frontmatter_name(skill_dir):
    '''读取技能说明文件的 YAML 元数据，校验并返回其中的技能名称。'''
    skill_md = Path(skill_dir) / "SKILL.md"
    if not skill_md.exists():
        print(f"[ERROR] SKILL.md not found in {skill_dir}")
        return None
    content = skill_md.read_text()
    match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if not match:
        print("[ERROR] Invalid SKILL.md frontmatter format.")
        return None
    frontmatter_text = match.group(1)

    import yaml

    try:
        frontmatter = yaml.safe_load(frontmatter_text)
    except yaml.YAMLError as exc:
        print(f"[ERROR] Invalid YAML frontmatter: {exc}")
        return None
    if not isinstance(frontmatter, dict):
        print("[ERROR] Frontmatter must be a YAML dictionary.")
        return None
    name = frontmatter.get("name", "")
    if not isinstance(name, str) or not name.strip():
        print("[ERROR] Frontmatter 'name' is missing or invalid.")
        return None
    return name.strip()


def parse_interface_overrides(raw_overrides):
    '''解析并校验命令行传入的界面字段覆盖值，同时保留可选字段顺序。'''
    overrides = {}
    optional_order = []
    for item in raw_overrides:
        if "=" not in item:
            print(f"[ERROR] Invalid interface override '{item}'. Use key=value.")
            return None, None
        key, value = item.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            print(f"[ERROR] Invalid interface override '{item}'. Key is empty.")
            return None, None
        if key not in ALLOWED_INTERFACE_KEYS:
            allowed = ", ".join(sorted(ALLOWED_INTERFACE_KEYS))
            print(f"[ERROR] Unknown interface field '{key}'. Allowed: {allowed}")
            return None, None
        overrides[key] = value
        if (
            key not in ("display_name", "short_description")
            and key not in optional_order
        ):
            optional_order.append(key)
    return overrides, optional_order


def write_openai_yaml(skill_dir, skill_name, raw_overrides):
    '''组合技能展示元数据并写入 agents/openai.yaml；参数不合法时返回 None。'''
    overrides, optional_order = parse_interface_overrides(raw_overrides)
    if overrides is None:
        return None

    display_name = overrides.get("display_name") or format_display_name(skill_name)
    short_description = overrides.get(
        "short_description"
    ) or generate_short_description(display_name)

    if not (25 <= len(short_description) <= 64):
        print(
            "[ERROR] short_description must be 25-64 characters "
            f"(got {len(short_description)})."
        )
        return None

    interface_lines = [
        "interface:",
        f"  display_name: {yaml_quote(display_name)}",
        f"  short_description: {yaml_quote(short_description)}",
    ]

    for key in optional_order:
        value = overrides.get(key)
        if value is not None:
            interface_lines.append(f"  {key}: {yaml_quote(value)}")

    agents_dir = Path(skill_dir) / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    output_path = agents_dir / "openai.yaml"
    output_path.write_text("\n".join(interface_lines) + "\n")
    print(f"[OK] Created agents/openai.yaml")
    return output_path


def main():
    '''解析命令行参数，确定技能名称并调用元数据文件生成流程。'''
    parser = argparse.ArgumentParser(
        description="Create agents/openai.yaml for a skill directory.",
    )
    parser.add_argument("skill_dir", help="Path to the skill directory")
    parser.add_argument(
        "--name",
        help="Skill name override (defaults to SKILL.md frontmatter)",
    )
    parser.add_argument(
        "--interface",
        action="append",
        default=[],
        help="Interface override in key=value format (repeatable)",
    )
    args = parser.parse_args()

    skill_dir = Path(args.skill_dir).resolve()
    if not skill_dir.exists():
        print(f"[ERROR] Skill directory not found: {skill_dir}")
        sys.exit(1)
    if not skill_dir.is_dir():
        print(f"[ERROR] Path is not a directory: {skill_dir}")
        sys.exit(1)

    skill_name = args.name or read_frontmatter_name(skill_dir)
    if not skill_name:
        sys.exit(1)

    result = write_openai_yaml(skill_dir, skill_name, args.interface)
    if result:
        sys.exit(0)
    sys.exit(1)


if __name__ == "__main__":
    main()
