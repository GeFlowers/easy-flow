'''读取技能文件并校验头部元数据，将有效配置转换为运行时技能模型。'''

import logging
import re
from pathlib import Path

import yaml

from .types import SKILL_MD_FILE, SecretRequirement, Skill, SkillCategory

logger = logging.getLogger(__name__)

_ENV_VAR_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _format_yaml_error(skill_file: Path, exc: yaml.YAMLError, source: str) -> str:
    '''把 YAML 解析错误整理为包含文件行号和常见未加引号冒号提示的诊断信息。'''

    lines = [f"Invalid YAML front-matter in {skill_file}: {exc}"]

    mark = getattr(exc, "problem_mark", None)
    source_lines = source.splitlines()
    if mark is not None and 0 <= mark.line < len(source_lines):
        offending = source_lines[mark.line]

        file_line_number = mark.line + 2
        lines.append(f"  line {file_line_number}: {offending}")

        if getattr(exc, "problem", "") == "mapping values are not allowed here" and ":" in offending:
            key, _, value = offending.partition(":")
            value = value.strip()
            if value and value[0] not in {'"', "'", "|", ">", "[", "{"}:
                escaped = value.replace("\\", "\\\\").replace('"', '\\"')
                lines.append(f'  hint: values containing ":" must be quoted, e.g. {key}: "{escaped}"')

    return "\n".join(lines)


def parse_allowed_tools(raw: object, skill_file: Path) -> tuple[str, ...] | None:
    '''解析允许工具字段；缺省返回 None，格式错误或空工具名则拒绝该技能。'''
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise ValueError(f"allowed-tools in {skill_file} must be a list of strings")

    allowed_tools: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise ValueError(f"allowed-tools in {skill_file} must contain only strings")
        tool_name = item.strip()
        if not tool_name:
            raise ValueError(f"allowed-tools in {skill_file} cannot contain empty tool names")
        allowed_tools.append(tool_name)
    return tuple(allowed_tools)


def parse_required_secrets(raw: object, skill_file: Path) -> tuple[SecretRequirement, ...]:
    '''解析技能要求的环境变量，校验名称、可选标记并去除重复项。'''
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError(f"required-secrets in {skill_file} must be a list")

    secrets: list[SecretRequirement] = []
    seen: set[str] = set()
    for item in raw:
        if isinstance(item, str):
            name, optional = item.strip(), False
        elif isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            optional = bool(item.get("optional", False))
        else:
            logger.warning("Ignoring malformed required-secrets entry in %s: %r", skill_file, item)
            continue

        if not _ENV_VAR_NAME_RE.match(name):
            logger.warning("Ignoring required-secrets entry with invalid env var name in %s: %r", skill_file, name)
            continue
        if name in seen:
            continue
        seen.add(name)
        secrets.append(SecretRequirement(name=name, optional=optional))
    return tuple(secrets)


def parse_secrets_autonomous(raw: object, skill_file: Path) -> bool:
    '''解析是否允许技能在无人值守情况下绑定密钥，异常配置按不允许处理。'''
    if raw is None:
        return True
    if isinstance(raw, bool):
        return raw
    logger.warning("Ignoring malformed secrets-autonomous value in %s: %r (autonomous binding disabled)", skill_file, raw)
    return False


def parse_skill_file(skill_file: Path, category: SkillCategory, relative_path: Path | None = None) -> Skill | None:
    '''读取并验证 SKILL.md 的名称、描述、许可、工具和密钥声明，构造启用状态待配置的技能对象。'''
    if not skill_file.exists() or skill_file.name != SKILL_MD_FILE:
        return None

    try:
        content = skill_file.read_text(encoding="utf-8")

        front_matter_match = re.match(r"^---\s*\n(.*?)\n---\s*\n?", content, re.DOTALL)
        if not front_matter_match:
            return None
        front_matter_text = front_matter_match.group(1)
        try:
            metadata = yaml.safe_load(front_matter_text)
        except yaml.YAMLError as exc:
            logger.error("%s", _format_yaml_error(skill_file, exc, front_matter_text))
            return None
        if not isinstance(metadata, dict):
            logger.error("Invalid SKILL.md front-matter in %s: Frontmatter must be a YAML dictionary", skill_file)
            return None

        name = metadata.get("name")
        description = metadata.get("description")

        if not name or not isinstance(name, str):
            return None
        if not description or not isinstance(description, str):
            return None

        name = name.strip()
        description = description.strip()

        if not name or not description:
            return None

        license_text = metadata.get("license")
        if license_text is not None:
            license_text = str(license_text).strip() or None

        try:
            allowed_tools = parse_allowed_tools(metadata.get("allowed-tools"), skill_file)
        except ValueError as exc:
            logger.error("Invalid allowed-tools in %s: %s", skill_file, exc)
            return None

        try:
            required_secrets = parse_required_secrets(metadata.get("required-secrets"), skill_file)
        except ValueError as exc:
            logger.error("Invalid required-secrets in %s: %s", skill_file, exc)
            return None

        secrets_autonomous = parse_secrets_autonomous(metadata.get("secrets-autonomous"), skill_file)

        return Skill(
            name=name,
            description=description,
            license=license_text,
            skill_dir=skill_file.parent,
            skill_file=skill_file,
            relative_path=relative_path or Path(skill_file.parent.name),
            category=category,
            allowed_tools=allowed_tools,
            enabled=True,
            required_secrets=required_secrets,
            secrets_autonomous=secrets_autonomous,
        )

    except Exception:
        logger.exception("Unexpected error parsing skill file %s", skill_file)
        return None
