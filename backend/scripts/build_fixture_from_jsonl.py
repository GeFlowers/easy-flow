"""本脚本负责构建 夹具。安全边界：仅处理显式指定的输入与路径，不作为常驻生产服务入口。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    '未说明'
    parser = argparse.ArgumentParser()
    parser.add_argument("--jsonl", required=True)
    parser.add_argument("--meta", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--model", default="gpt-5.5")
    args = parser.parse_args()

    turns = [json.loads(line) for line in Path(args.jsonl).read_text(encoding="utf-8").splitlines() if line.strip()]
    meta = json.loads(Path(args.meta).read_text(encoding="utf-8"))
    fixture = {
        "scenario": meta["scenario"],
        "mode": meta["mode"],
        "model": args.model,
        "prompt": meta["prompt"],
        "context": meta.get("context", {}),
        "turns": turns,
    }
    Path(args.out).write_text(json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(turns)} turn(s) -> {args.out}")
    for index, turn in enumerate(turns):
        data = turn["output"].get("data", {})
        tool_calls = [tc.get("name") for tc in (data.get("tool_calls") or [])]
        caller = turn.get("caller", "legacy")
        print(f"  turn {index}: caller={caller} hash={turn['input_hash'][:12]} tool_calls={tool_calls} content={str(data.get('content'))[:50]!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
