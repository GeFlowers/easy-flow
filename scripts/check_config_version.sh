#!/usr/bin/env bash
# 检查 Helm chart 内嵌 config_version 不落后于 config.example.yaml。
#
# deploy/helm/deer-flow/values.yaml 的 chart `config:` 块内嵌 config_version，
# 不得落后于 config.example.yaml。集群内的过期版本不会被发现（镜像不携带用于比较的
# 示例文件，因此 _check_config_version 不会告警），却表示 chart 配置基于旧 schema；
# 故在构建阶段失败，而不把问题留给用户安装时。config_version 不控制运行行为，仅驱动
# 过期告警，所以单独提升版本无需变更字段。
#
# 用法：
#   scripts/check_config_version.sh
#
# 由 .github/workflows/chart.yaml（PR 与 v* tag 的 validate-chart）及
# .github/workflows/nightly.yaml（validate-chart）调用，以保持二者一致。
#
# chart 为最新时退出码为 0，否则为 1。

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

EXAMPLE_YAML="$ROOT/config.example.yaml"
VALUES_YAML="$ROOT/deploy/helm/deer-flow/values.yaml"

for f in "$EXAMPLE_YAML" "$VALUES_YAML"; do
  if [ ! -f "$f" ]; then
    echo "::error::missing file: $f" >&2
    exit 1
  fi
done

example=$(grep -E '^config_version:[[:space:]]+[0-9]+' "$EXAMPLE_YAML" | head -1 | awk '{print $2}')
chart=$(awk '/^config:[[:space:]]*\|/{f=1; next} f && /^[[:space:]]+config_version:[[:space:]]+[0-9]+/ {print $2; exit}' "$VALUES_YAML")

printf 'config.example.yaml config_version=%s\n' "$example"
printf 'chart values.yaml     config_version=%s\n' "$chart"

if [ -z "$example" ] || [ -z "$chart" ]; then
  echo "::error::could not parse config_version from one of the files" >&2
  exit 1
fi

if [ "$chart" -lt "$example" ]; then
  echo "::error::chart config_version ($chart) is behind config.example.yaml ($example). Bump 'config_version' in deploy/helm/deer-flow/values.yaml (and the README example) to $example." >&2
  exit 1
fi

echo "OK - chart config_version ($chart) is current with config.example.yaml ($example)."
