'未说明'

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from _agent_e2e_helpers import FakeToolCallingModel, build_single_tool_call_model


def _build_fake_create_chat_model(agent_name: str):
    '未说明'

    def fake_create_chat_model(*args: Any, **kwargs: Any) -> FakeToolCallingModel:
        '未说明'
        return build_single_tool_call_model(
            tool_name="setup_agent",
            tool_args={
                "soul": f"# Real HTTP E2E SOUL for {agent_name}",
                "description": "real-http-e2e agent",
            },
            tool_call_id="call_real_http_1",
            final_text=f"Agent {agent_name} created via real HTTP e2e.",
        )

    return fake_create_chat_model


@pytest.fixture
def isolated_deer_flow_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    '未说明'
    home = tmp_path / "deer-flow-home"
    home.mkdir()
    monkeypatch.setenv("DEER_FLOW_HOME", str(home))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake-key-not-used-because-llm-is-mocked")
    monkeypatch.setenv("OPENAI_API_BASE", "https://example.invalid")

    # Hermetic config: do not depend on whether the dev machine has a real
    # ``config.yaml`` at the repo root. CI's ``actions/checkout`` only ships
    # ``config.example.yaml`` (and its ``models:`` list is commented out, so
    # AppConfig validation would reject it). Write a minimal, self-sufficient
    # config to tmp_path and pin ``DEER_FLOW_CONFIG_PATH`` to it.
    staged_config = tmp_path / "config.yaml"
    staged_config.write_text(_MINIMAL_CONFIG_YAML, encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(staged_config))

    return home


# Minimal config that satisfies AppConfig + LeadAgent's _resolve_model_name.
# The model `use` path must resolve to a real class for config parsing to
# succeed; the test patches ``create_chat_model`` on the lead agent module,
# so the model is never actually instantiated. SandboxConfig.use is required
# at schema level; LocalSandboxProvider is the only sandbox that runs without
# Docker.
_MINIMAL_CONFIG_YAML = """\
log_level: info
models:
  - name: fake-test-model
    display_name: Fake Test Model
    use: langchain_openai:ChatOpenAI
    model: gpt-4o-mini
    api_key: $OPENAI_API_KEY
    base_url: $OPENAI_API_BASE
sandbox:
  use: deerflow.sandbox.local:LocalSandboxProvider
agents_api:
  enabled: true
database:
  backend: sqlite
"""


def _reset_process_singletons(monkeypatch: pytest.MonkeyPatch) -> None:
    '未说明'
    from deerflow.config import app_config as app_config_module
    from deerflow.config import paths as paths_module
    from deerflow.persistence import engine as engine_module

    for module, attr in (
        (app_config_module, "_app_config"),
        (app_config_module, "_app_config_path"),
        (app_config_module, "_app_config_mtime"),
        (paths_module, "_paths_singleton"),
        (engine_module, "_engine"),
        (engine_module, "_session_factory"),
    ):
        monkeypatch.setattr(module, attr, None, raising=False)


@pytest.fixture
def isolated_app(isolated_deer_flow_home: Path, monkeypatch: pytest.MonkeyPatch):
    '未说明'
    _reset_process_singletons(monkeypatch)

    # Re-resolve the config from the test-only DEER_FLOW_HOME and pin its
    # sqlite path into tmp_path so the lifespan-time engine init lands there.
    from deerflow.config import app_config as app_config_module

    cfg = app_config_module.get_app_config()
    cfg.database.sqlite_dir = str(isolated_deer_flow_home / "db")

    from app.gateway.app import create_app

    return create_app()


def _drain_stream(response, *, timeout: float = 30.0, max_bytes: int = 4 * 1024 * 1024) -> str:
    '未说明'
    import time as _time

    deadline = _time.monotonic() + timeout
    body = b""
    for chunk in response.iter_bytes():
        body += chunk
        if b"event: end" in body:
            break
        if len(body) >= max_bytes:
            break
        if _time.monotonic() >= deadline:
            break
    return body.decode("utf-8", errors="replace")


def _wait_for_file(path: Path, *, timeout: float = 10.0) -> bool:
    '未说明'
    import time as _time

    deadline = _time.monotonic() + timeout
    while _time.monotonic() < deadline:
        if path.exists():
            return True
        _time.sleep(0.05)
    return False


@pytest.mark.no_auto_user
def test_real_http_create_agent_lands_in_authenticated_user_dir(
    isolated_app: Any,
    isolated_deer_flow_home: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    '未说明'
    # ``deerflow.agents.lead_agent.agent`` imports ``create_chat_model`` with
    # ``from deerflow.models import create_chat_model`` at module load time,
    # rebinding the symbol into its own namespace. So the only patch that
    # intercepts the call is the bound name on ``lead_agent.agent`` — patching
    # ``deerflow.models.create_chat_model`` would be too late.
    agent_name = "real-http-agent"

    from starlette.testclient import TestClient

    with (
        patch(
            "deerflow.agents.lead_agent.agent.create_chat_model",
            new=_build_fake_create_chat_model(agent_name),
        ),
        TestClient(isolated_app) as client,
    ):
        # --- 1. Register & auto-login ---
        register = client.post(
            "/api/v1/auth/register",
            json={"email": "e2e-user@example.com", "password": "very-strong-password-123"},
        )
        assert register.status_code == 201, register.text
        registered = register.json()
        auth_uid = registered["id"]
        # The endpoint sets both access_token (auth) and csrf_token (CSRF Double
        # Submit Cookie) cookies; the TestClient cookie jar propagates them.
        assert client.cookies.get("access_token"), "register endpoint must set session cookie"
        csrf_token = client.cookies.get("csrf_token")
        assert csrf_token, "register endpoint must set csrf_token cookie"

        # --- 2. Create a thread (require_existing=True on /runs/stream means
        # we must call POST /api/threads first; the React frontend does the
        # same via the LangGraph SDK's threads.create) ---
        import uuid as _uuid

        thread_id = str(_uuid.uuid4())
        created = client.post(
            "/api/threads",
            json={"thread_id": thread_id, "metadata": {}},
            headers={"X-CSRF-Token": csrf_token},
        )
        assert created.status_code == 200, created.text

        # --- 3. POST /runs/stream with the bootstrap wire format ---
        # This is the EXACT shape the React frontend sends after PR #2784:
        #   thread.submit(input, {config, context}) ->
        #   POST /api/threads/{id}/runs/stream body =
        #     {assistant_id, input, config, context}
        body = {
            "assistant_id": "lead_agent",
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": (f"The new custom agent name is {agent_name}. Help me design its SOUL.md before saving it."),
                    }
                ]
            },
            "config": {"recursion_limit": 50},
            "context": {
                "agent_name": agent_name,
                "is_bootstrap": True,
                "mode": "flash",
                "thinking_enabled": False,
                "is_plan_mode": False,
                "subagent_enabled": False,
            },
            "stream_mode": ["values"],
        }
        # The /stream endpoint returns SSE; we drain it so the server-side
        # background task (run_agent) gets to completion before we look at disk.
        with client.stream(
            "POST",
            f"/api/threads/{thread_id}/runs/stream",
            json=body,
            headers={"X-CSRF-Token": csrf_token},
        ) as resp:
            assert resp.status_code == 200, resp.read().decode()
            transcript = _drain_stream(resp)

        # Sanity: the stream should have produced at least one event
        assert "event:" in transcript, f"no SSE events in response: {transcript[:500]!r}"

        # --- 4. Verify filesystem outcome ---
        expected_dir = isolated_deer_flow_home / "users" / auth_uid / "agents" / agent_name
        default_dir = isolated_deer_flow_home / "users" / "default" / "agents" / agent_name

        # The setup_agent tool runs inside the background asyncio task spawned
        # by start_run; SSE-drain typically waits for it, but we add a bounded
        # poll to be robust against scheduler jitter.
        assert _wait_for_file(expected_dir / "SOUL.md", timeout=15.0), (
            "SOUL.md did not appear under users/<auth_uid>/agents/. "
            f"Expected: {expected_dir / 'SOUL.md'}. "
            f"tmp tree: {sorted(str(p.relative_to(isolated_deer_flow_home)) for p in isolated_deer_flow_home.rglob('SOUL.md'))}. "
            f"SSE transcript tail: {transcript[-1000:]!r}"
        )

        soul_text = (expected_dir / "SOUL.md").read_text()
        assert agent_name in soul_text, f"unexpected SOUL content: {soul_text!r}"

        # The smoking-gun assertion: the agent must NOT have landed in default/
        assert not default_dir.exists(), f"REGRESSION: agent landed under users/default/{agent_name} instead of the authenticated user. Default-dir contents: {list(default_dir.rglob('*')) if default_dir.exists() else 'n/a'}"
