#!/bin/bash

# 安装技能并链接到项目的 skills/custom 目录。
# 用法：./skills/install-skill.sh <owner/repo@skill-name>
# 示例：./skills/install-skill.sh vercel-labs/agent-skills@vercel-react-best-practices

set -e

if [[ -z "$1" ]]; then
  echo "Usage: $0 <owner/repo@skill-name>"
  echo "Example: $0 vercel-labs/agent-skills@vercel-react-best-practices"
  exit 1
fi

FULL_SKILL_NAME="$1"

# 提取 @ 后的技能名，供全局安装路径与项目链接使用。
SKILL_NAME="${FULL_SKILL_NAME##*@}"

if [[ -z "$SKILL_NAME" || "$SKILL_NAME" == "$FULL_SKILL_NAME" ]]; then
  echo "Error: Invalid skill format. Expected: owner/repo@skill-name"
  exit 1
fi

# 向上查找 deer-flow.code-workspace 来定位项目根目录，避免依赖当前工作目录。
find_project_root() {
  local dir="$PWD"
  while [[ "$dir" != "/" ]]; do
    if [[ -f "$dir/deer-flow.code-workspace" ]]; then
      echo "$dir"
      return 0
    fi
    dir="$(dirname "$dir")"
  done
  echo ""
  return 1
}

PROJECT_ROOT=$(find_project_root)

if [[ -z "$PROJECT_ROOT" ]]; then
  echo "Error: Could not find project root (deer-flow.code-workspace not found)"
  exit 1
fi

SKILL_SOURCE="$HOME/.agents/skills/$SKILL_NAME"
SKILL_TARGET="$PROJECT_ROOT/skills/custom"

# 第 1 步：用 npx 安装全局技能包。
npx skills add "$FULL_SKILL_NAME" -g -y > /dev/null 2>&1

# 第 2 步：确认全局安装目录存在，避免建立悬空链接。
if [[ ! -d "$SKILL_SOURCE" ]]; then
  echo "Skill '$SKILL_NAME' installation failed"
  exit 1
fi

# 第 3 步：创建项目链接，使自定义技能目录引用全局安装结果。
mkdir -p "$SKILL_TARGET"
ln -sf "$SKILL_SOURCE" "$SKILL_TARGET/"

echo "Skill '$SKILL_NAME' installed successfully"
