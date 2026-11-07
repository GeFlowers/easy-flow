#!/usr/bin/env python3
'''
从模板初始化新技能目录。

用法：
    init_skill.py <skill-name> --path <path> [--resources scripts,references,assets] [--examples] [--interface key=value]

示例：
    init_skill.py my-new-skill --path skills/public
    init_skill.py my-new-skill --path skills/public --resources scripts,references
    init_skill.py my-api-helper --path skills/private --resources scripts --examples
    init_skill.py custom-skill --path /custom/location
    init_skill.py my-skill --path skills/public --interface short_description="用于界面展示的简短技能说明"
'''

import argparse
import re
import sys
from pathlib import Path

from generate_openai_yaml import write_openai_yaml

MAX_SKILL_NAME_LENGTH = 64
ALLOWED_RESOURCES = {"scripts", "references", "assets"}

SKILL_TEMPLATE = """---
name: {skill_name}
description: "[TODO: 简要描述技能的用途和适用情况。]"
---


[TODO: 添加 Codex 完成该任务所需的专用指导，只在相关时引用配套文件。]
"""

EXAMPLE_SCRIPT = """#!/usr/bin/env python3
'''{skill_name} 技能的示例辅助脚本。

此脚本是可直接运行的占位示例；请替换为实际实现，或在不需要时删除。

其他技能中的真实脚本示例：
- pdf/scripts/fill_fillable_fields.py：填写 PDF 表单字段
- pdf/scripts/convert_pdf_to_images.py：将 PDF 页面转换为图像
'''

def main():
    '''输出示例脚本提示，供新技能作者替换为实际逻辑。'''
    print("这是 {skill_name} 技能的示例脚本")
    # TODO：在此添加实际脚本逻辑。
    # 可在此实现数据处理、文件转换或接口调用等工作。

if __name__ == "__main__":
    main()
"""

EXAMPLE_REFERENCE = """# {skill_title} 参考说明

用需维护的任务专属细节替换本占位内容，例如操作约束、本地数据结构或容易出错的集成行为。
只保留 Codex 无法可靠自行推断的信息。

没有工作流程需要时删除本文件。
"""

EXAMPLE_ASSET = """# 示例资源文件

这里是资源文件的存放位置。替换为真实模板、图片、字体等，不需要时删除。
资源用于 Codex 生成的结果，不应直接作为指令加载进上下文。

其他技能的资源示例：
- 品牌规范：logo.png、slides_template.pptx。
- 前端构建：hello-world/ 目录中的 HTML/React 起始项目。
- 排版：custom-font.ttf、font-family.woff2。
- 数据：sample_data.csv、test_dataset.json。

常见类型：
- 模板：.pptx、.docx、基础项目目录。
- 图片：.png、.jpg、.svg、.gif。
- 字体：.ttf、.otf、.woff、.woff2。
- 基础代码：项目目录、起始文件。
- 图标：.ico、.svg。
- 数据文件：.csv、.json、.xml、.yaml。

本文件只是文字占位，真实资源可以是任意文件类型。
"""


def normalize_skill_name(skill_name):
    '''将技能名称规范化为小写连字符格式。'''
    normalized = skill_name.strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized)
    normalized = normalized.strip("-")
    normalized = re.sub(r"-{2,}", "-", normalized)
    return normalized


def title_case_skill_name(skill_name):
    '''将连字符分隔的技能名称转换为便于展示的标题格式。'''
    return " ".join(word.capitalize() for word in skill_name.split("-"))


def parse_resources(raw_resources):
    '''解析逗号分隔的资源目录选项，去重并拒绝不支持的目录类型。'''
    if not raw_resources:
        return []
    resources = [item.strip() for item in raw_resources.split(",") if item.strip()]
    invalid = sorted({item for item in resources if item not in ALLOWED_RESOURCES})
    if invalid:
        allowed = ", ".join(sorted(ALLOWED_RESOURCES))
        print(f"[ERROR] 未知资源类型： {', '.join(invalid)}")
        print(f"   允许值： {allowed}")
        sys.exit(1)
    deduped = []
    seen = set()
    for resource in resources:
        if resource not in seen:
            deduped.append(resource)
            seen.add(resource)
    return deduped


def create_resource_dirs(
    skill_dir, skill_name, skill_title, resources, include_examples
):
    '''按选项创建脚本、参考资料或资源目录，并可选择写入示例文件。'''
    for resource in resources:
        resource_dir = skill_dir / resource
        resource_dir.mkdir(exist_ok=True)
        if resource == "scripts":
            if include_examples:
                example_script = resource_dir / "example.py"
                example_script.write_text(EXAMPLE_SCRIPT.format(skill_name=skill_name), encoding="utf-8")
                example_script.chmod(0o755)
                print("[OK] 已创建 scripts/example.py")
            else:
                print("[OK] 已创建 scripts/")
        elif resource == "references":
            if include_examples:
                example_reference = resource_dir / "api_reference.md"
                example_reference.write_text(
                    EXAMPLE_REFERENCE.format(skill_title=skill_title), encoding="utf-8"
                )
                print("[OK] 已创建 references/api_reference.md")
            else:
                print("[OK] 已创建 references/")
        elif resource == "assets":
            if include_examples:
                example_asset = resource_dir / "example_asset.txt"
                example_asset.write_text(EXAMPLE_ASSET, encoding="utf-8")
                print("[OK] 已创建 assets/example_asset.txt")
            else:
                print("[OK] 已创建 assets/")


def init_skill(skill_name, path, resources, include_examples, interface_overrides):
    '''
    根据模板创建技能说明和指定资源目录，按需生成示例及界面元数据。

    Args:
        skill_name: 新技能的目录名称。
        path: 用于存放新技能的父目录。
        resources: 需要创建的资源子目录。
        include_examples: 是否在资源目录中生成示例文件。
        interface_overrides: 用于生成界面元数据的覆盖项。

    Returns:
        创建成功时返回技能目录，失败时返回 None。
    '''
    skill_dir = Path(path).resolve() / skill_name

    if skill_dir.exists():
        print(f"[ERROR] 技能目录已存在： {skill_dir}")
        return None

    try:
        skill_dir.mkdir(parents=True, exist_ok=False)
        print(f"[OK] 已创建技能目录： {skill_dir}")
    except Exception as e:
        print(f"[ERROR] 创建目录失败： {e}")
        return None

    # 根据模板生成 SKILL.md。
    skill_title = title_case_skill_name(skill_name)
    skill_content = SKILL_TEMPLATE.format(
        skill_name=skill_name, skill_title=skill_title
    )

    skill_md_path = skill_dir / "SKILL.md"
    try:
        skill_md_path.write_text(skill_content, encoding="utf-8")
        print("[OK] 已创建 SKILL.md")
    except Exception as e:
        print(f"[ERROR] 创建 SKILL.md 失败： {e}")
        return None

    try:
        result = write_openai_yaml(skill_dir, skill_name, interface_overrides)
        if not result:
            return None
    except Exception as e:
        print(f"[ERROR] 创建 agents/openai.yaml 失败： {e}")
        return None

    if resources:
        try:
            create_resource_dirs(
                skill_dir, skill_name, skill_title, resources, include_examples
            )
        except Exception as e:
            print(f"[ERROR] 创建资源目录失败： {e}")
            return None

    print(f"\n[OK] 技能 '{skill_name}' 已初始化到 {skill_dir}")
    print("\n后续步骤：")
    print("1. 编辑 SKILL.md，完成 TODO 待办并更新描述")
    if resources:
        if include_examples:
            print(
                "2. 按需修改或删除 scripts/、references/、assets/ 中的示例"
            )
        else:
            print("2. 按需向 scripts/、references/、assets/ 添加资源")
    else:
        print(
            "2. 只在需要时创建 scripts/、references/、assets/ 资源目录"
        )
    print("3. 需要不同界面元数据时更新 agents/openai.yaml")
    print("4. 完成后运行验证器，检查技能结构")
    print(
        "5. 只有复杂度或风险确有需要时才进行独立前向验证"
    )

    return skill_dir


def main():
    '''解析初始化选项、规范化技能名称，并执行目录和模板文件的创建。'''
    parser = argparse.ArgumentParser(
        description="创建包含 SKILL.md 模板的新技能目录。",
    )
    parser.add_argument("skill_name", help="技能名，将规范化为小写连字符格式")
    parser.add_argument("--path", required=True, help="技能输出目录")
    parser.add_argument(
        "--resources",
        default="",
        help="用逗号分隔的资源列表：scripts,references,assets",
    )
    parser.add_argument(
        "--examples",
        action="store_true",
        help="在所选资源目录内创建示例文件",
    )
    parser.add_argument(
        "--interface",
        action="append",
        default=[],
        help="以 key=value 覆盖界面字段，可重复传入",
    )
    args = parser.parse_args()

    raw_skill_name = args.skill_name
    skill_name = normalize_skill_name(raw_skill_name)
    if not skill_name:
        print("[ERROR] 技能名必须至少包含一个字母或数字。")
        sys.exit(1)
    if len(skill_name) > MAX_SKILL_NAME_LENGTH:
        print(
            f"[ERROR] Skill name '{skill_name}' is too long ({len(skill_name)} characters). "
            f"最多允许 {MAX_SKILL_NAME_LENGTH} 个字符。"
        )
        sys.exit(1)
    if skill_name != raw_skill_name:
        print(f"提示：已将技能名从 '{raw_skill_name}' 规范化为 '{skill_name}'。")

    resources = parse_resources(args.resources)
    if args.examples and not resources:
        print("[ERROR] 使用 --examples 时必须指定 --resources。")
        sys.exit(1)

    path = args.path

    print(f"正在初始化技能： {skill_name}")
    print(f"   位置： {path}")
    if resources:
        print(f"   资源： {', '.join(resources)}")
        if args.examples:
            print("   示例：启用")
    else:
        print("   资源：无，可按需创建")
    print()

    result = init_skill(skill_name, path, resources, args.examples, args.interface)

    if result:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
