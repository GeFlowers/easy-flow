#!/usr/bin/env bash
# 校验项目的全部版本来源保持一致，防止发布产物版本漂移。
#
# 校验来源：
#   deploy/helm/deer-flow/Chart.yaml   — version + appVersion
#   backend/pyproject.toml             — version
#   frontend/package.json              — version
#
# 用法：
#   scripts/verify_versions.sh             # 所有来源必须彼此相等
#   scripts/verify_versions.sh 2.1.0       # 所有来源必须等于 2.1.0
#
# 一致时退出码为 0，否则为 1。发布工作流会在 v* tag 上经由
# .github/workflows/verify-versions.yml 调用它，避免遗漏某个版本来源仍继续发布。

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

CHART="$ROOT/deploy/helm/deer-flow/Chart.yaml"
PYPROJECT="$ROOT/backend/pyproject.toml"
PACKAGE="$ROOT/frontend/package.json"

for f in "$CHART" "$PYPROJECT" "$PACKAGE"; do
  if [ ! -f "$f" ]; then
    echo "::error::missing version file: $f" >&2
    exit 1
  fi
done

CHART_VERSION=$(awk '/^version:/ {print $2; exit}' "$CHART")
APP_VERSION=$(awk '/^appVersion:/ {gsub(/"/, ""); print $2; exit}' "$CHART")
PY_VERSION=$(awk -F'"' '/^version[[:space:]]*=/ {print $2; exit}' "$PYPROJECT")
JS_VERSION=$(grep -m1 '"version"' "$PACKAGE" | awk -F'"' '{print $4}')

printf 'Chart.yaml version:     %s\n' "$CHART_VERSION"
printf 'Chart.yaml appVersion:  %s\n' "$APP_VERSION"
printf 'backend/pyproject.toml: %s\n' "$PY_VERSION"
printf 'frontend/package.json:  %s\n' "$JS_VERSION"

# 比较一个版本来源；不一致时输出 GitHub Actions 标注并返回 1，便于 CI 聚合全部差异。
mismatch() {
  if [ "$2" != "$3" ]; then
    echo "::error::$1 is '$2' but expected '$3'." >&2
    return 1
  fi
  return 0
}

EXPECTED="${1:-}"
status=0

if [ -n "$EXPECTED" ]; then
  printf 'Expected:               %s (from tag v%s)\n\n' "$EXPECTED" "$EXPECTED"
  mismatch "Chart.yaml version"     "$CHART_VERSION" "$EXPECTED" || status=1
  mismatch "Chart.yaml appVersion"  "$APP_VERSION"   "$EXPECTED" || status=1
  mismatch "backend/pyproject.toml" "$PY_VERSION"    "$EXPECTED" || status=1
  mismatch "frontend/package.json"  "$JS_VERSION"    "$EXPECTED" || status=1
else
  echo
  mismatch "Chart.yaml appVersion"  "$APP_VERSION"  "$CHART_VERSION" || status=1
  mismatch "backend/pyproject.toml" "$PY_VERSION"   "$CHART_VERSION" || status=1
  mismatch "frontend/package.json"  "$JS_VERSION"   "$CHART_VERSION" || status=1
fi

if [ "$status" -ne 0 ]; then
  if [ -n "$EXPECTED" ]; then
    echo "Tip: run scripts/bump_version.sh $EXPECTED to align all sources." >&2
  else
    echo "Tip: run scripts/bump_version.sh <version> to align all sources." >&2
  fi
  exit 1
fi

echo "OK — all version sources agree on ${CHART_VERSION}."
