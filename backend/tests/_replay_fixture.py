'定义 _replay_fixture 模块提供的职责与可复用接口。\n\nShared config + gateway-drive helpers for the record/replay e2e.\n\nRecord (``scripts/record_gateway.py`` + ``scripts/build_fixture_from_jsonl.py``)\nand replay (``tests/test_replay_golden.py``)\nMUST drive the gateway through an identical, prompt-affecting config — otherwise\nthe system prompt differs and the recorded input hashes never match on replay.\nCentralising the config builder + drive loop here makes that identity hold by\nconstruction; only the ``models[].use`` block differs (real model vs\n``ReplayChatModel``).\n'

from __future__ import annotations

import json
import uuid
from pathlib import Path

# mode -> (thinking_enabled, is_plan_mode, subagent_enabled). Mirrors the
# frontend mapping in core/threads/hooks.ts.
MODE_CONTEXT: dict[str, tuple[bool, bool, bool]] = {
    "flash": (False, False, False),
    "thinking": (True, False, False),
    "pro": (True, True, False),
    # thinking_enabled mirrors the frontend `context.mode !== "flash"` (hooks.ts),
    # so ultra is thinking-enabled too.
    "ultra": (True, True, True),
}

# The replay model block: same model NAME as recording (so nothing in the prompt
# shifts), only ``use`` swapped to the deterministic replay provider.
REPLAY_MODEL_BLOCK = """\
  - name: scenario-model
    display_name: Scenario Model
    use: replay_provider:ReplayChatModel
    model: replay
    supports_thinking: true"""


def real_model_block(model: str) -> str:
    '执行 real_model_block 的明确职责，并返回与调用约定一致的结果'
    return f"""\
  - name: scenario-model
    display_name: Scenario Model
    use: langchain_openai:ChatOpenAI
    model: {model}
    api_key: $OPENAI_API_KEY
    base_url: $OPENAI_API_BASE"""


def build_config_yaml(*, model_block: str, home: Path) -> str:
    '构建并返回，并遵守 build_config_yaml 所表达的接口约束。\n\nFull gateway config. Only ``model_block`` varies between record/replay.\n\n    Everything that shapes the system prompt is pinned so record, replay, and CI\n    produce byte-identical prompts regardless of the machine:\n    - sandbox / tool_groups / tools — fixed here\n    - skills — pointed at an empty ``<home>/skills`` so filesystem skills (incl.\n      gitignored custom skills present only on a dev box) never leak into the\n      prompt. Pair with an empty ``extensions_config.json`` (no MCP) via\n      :func:`prepare_hermetic_extras`.\n    - memory / summarization — disabled (background, non-deterministic timing)\n    '
    return f"""\
log_level: warning
models:
{model_block}
sandbox:
  use: deerflow.sandbox.local:LocalSandboxProvider
skills:
  path: {home / "skills"}
  container_path: /mnt/skills
tool_groups:
  - name: file:read
  - name: file:write
tools:
  - name: ls
    group: file:read
    use: deerflow.sandbox.tools:ls_tool
  - name: read_file
    group: file:read
    use: deerflow.sandbox.tools:read_file_tool
  - name: write_file
    group: file:write
    use: deerflow.sandbox.tools:write_file_tool
# Memory + summarization make background / debounced model calls whose timing is
# non-deterministic; disable them so record and replay see the same model-call
# set. Title stays enabled, but the default title.model_name: null path is a
# local state update rather than a recorded model call.
memory:
  enabled: false
  injection_enabled: false
summarization:
  enabled: false
agents_api:
  enabled: true
database:
  backend: sqlite
  sqlite_dir: {home / "db"}
"""


def prepare_hermetic_extras(home: Path) -> Path:
    '执行 prepare_hermetic_extras 的明确职责，并返回与调用约定一致的结果。\n\nCreate the empty skills tree + an empty extensions_config.json so the\n    system prompt has no environment-dependent skills/MCP content.\n\n    Returns the extensions-config path; the caller must point\n    ``DEER_FLOW_EXTENSIONS_CONFIG_PATH`` at it. Call before starting the gateway.\n    '
    (home / "skills" / "public").mkdir(parents=True, exist_ok=True)
    (home / "skills" / "custom").mkdir(parents=True, exist_ok=True)
    extensions = home / "extensions_config.json"
    extensions.write_text(json.dumps({"mcpServers": {}, "skills": {}}), encoding="utf-8")
    return extensions


def sse_event_shapes(resp) -> list[dict]:
    '执行 sse_event_shapes 的明确职责，并返回与调用约定一致的结果。\n\nReduce an SSE stream to (event name, sorted top-level data keys).\n\n    Snapshots the *shape* of the stream, not volatile values, so the golden is\n    stable across runs while still catching event-sequence / payload-shape drift.\n    '
    events: list[dict] = []
    current: str | None = None
    for line in resp.iter_lines():
        if line.startswith("event:"):
            current = line[len("event:") :].strip()
        elif line.startswith("data:"):
            raw = line[len("data:") :].strip()
            try:
                data = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                data = {"_raw": raw[:200]}
            events.append({"event": current, "keys": sorted(data.keys()) if isinstance(data, dict) else None})
    return events


def drive_gateway(app, *, prompt: str, context: dict) -> list[dict]:
    "执行 drive_gateway 的明确职责，并返回与调用约定一致的结果。\n\nRegister -> create thread -> POST /runs/stream; return SSE event shapes.\n\n    This is the exact wire path the React frontend uses (LangGraph SDK), driven\n    in-process via Starlette's TestClient with the real auth flow.\n    "
    from starlette.testclient import TestClient

    with TestClient(app) as client:
        reg = client.post(
            "/api/v1/auth/register",
            json={"email": f"e2e-{uuid.uuid4().hex[:8]}@example.com", "password": "very-strong-password-123"},
        )
        assert reg.status_code == 201, reg.text
        csrf = client.cookies.get("csrf_token")
        assert csrf, "register must set csrf_token cookie"

        thread_id = str(uuid.uuid4())
        created = client.post("/api/threads", json={"thread_id": thread_id, "metadata": {}}, headers={"X-CSRF-Token": csrf})
        assert created.status_code == 200, created.text

        body = {
            "assistant_id": "lead_agent",
            "input": {"messages": [{"role": "user", "content": prompt}]},
            "config": {"recursion_limit": 50},
            "context": context,
            "stream_mode": ["values"],
        }
        with client.stream("POST", f"/api/threads/{thread_id}/runs/stream", json=body, headers={"X-CSRF-Token": csrf}) as resp:
            assert resp.status_code == 200, resp.read().decode()
            return sse_event_shapes(resp)
