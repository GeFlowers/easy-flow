"定义 test_client_e2e 模块提供的职责与可复用接口。\n\nEnd-to-end tests for DeerFlowClient.\n\nMiddle tier of the test pyramid:\n- Top:    test_client_live.py  — real LLM, needs API key\n- Middle: test_client_e2e.py   — real LLM + real modules  ← THIS FILE\n- Bottom: test_client.py       — unit tests, mock everything\n\nCore principle: use the real LLM from config.yaml, let config, middleware\nchain, tool registration, file I/O, and event serialization all run for real.\nOnly DEER_FLOW_HOME is redirected to tmp_path for filesystem isolation.\n\nTests that call the LLM are marked ``requires_llm`` and skipped in CI.\nFile-management tests (upload/list/delete) don't need LLM and run everywhere.\n"

import json
import os
import uuid
import zipfile
from pathlib import Path

import pytest
from dotenv import load_dotenv

from deerflow.client import DeerFlowClient, StreamEvent
from deerflow.config.app_config import AppConfig

# Load .env from project root (for OPENAI_API_KEY etc.)
load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env"))

# ---------------------------------------------------------------------------
# Markers
# ---------------------------------------------------------------------------

requires_llm = pytest.mark.skipif(
    os.getenv("CI", "").lower() in ("true", "1") or not os.getenv("OPENAI_API_KEY"),
    reason="Requires LLM API key — skipped in CI or when OPENAI_API_KEY is unset",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_e2e_config() -> AppConfig:
    '执行 _make_e2e_config 的明确职责，并返回与调用约定一致的结果。\n\nBuild a minimal AppConfig using real LLM credentials from environment.\n\n    All LLM connection details come from environment variables so that both\n    internal CI and external contributors can run the tests:\n\n    - ``E2E_MODEL_NAME``  (default: ``volcengine-ark``)\n    - ``E2E_MODEL_USE``   (default: ``langchain_openai:ChatOpenAI``)\n    - ``E2E_MODEL_ID``    (default: ``ep-20251211175242-llcmh``)\n    - ``E2E_BASE_URL``    (default: ``https://ark-cn-beijing.bytedance.net/api/v3``)\n    - ``OPENAI_API_KEY``  (required for LLM tests)\n\n    Note: We use model_validate with a raw dict (not AppConfig(models=[ModelConfig(...)]))\n    because passing already-validated Pydantic instances triggers a pydantic-core\n    shortcut that returns stale cached data when another AppConfig was previously\n    loaded from disk in the same process. Dict-based validation is always correct.\n    '
    return AppConfig.model_validate(
        {
            "models": [
                {
                    "name": os.getenv("E2E_MODEL_NAME", "volcengine-ark"),
                    "display_name": "E2E Test Model",
                    "use": os.getenv("E2E_MODEL_USE", "langchain_openai:ChatOpenAI"),
                    "model": os.getenv("E2E_MODEL_ID", "ep-20251211175242-llcmh"),
                    "base_url": os.getenv("E2E_BASE_URL", "https://ark-cn-beijing.bytedance.net/api/v3"),
                    "api_key": os.getenv("OPENAI_API_KEY", ""),
                    "max_tokens": 512,
                    "temperature": 0.7,
                    "supports_thinking": False,
                    "supports_reasoning_effort": False,
                    "supports_vision": False,
                }
            ],
            "sandbox": {
                "use": "deerflow.sandbox.local:LocalSandboxProvider",
                "allow_host_bash": True,
            },
        }
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def e2e_env(tmp_path, monkeypatch):
    '执行 e2e_env 的明确职责，并返回与调用约定一致的结果。\n\nIsolated filesystem environment for E2E tests.\n\n    - DEER_FLOW_HOME → tmp_path (all thread data lands in a temp dir)\n    - DEER_FLOW_PROJECT_ROOT → repository root (shared skills/config assets\n      still resolve correctly when tests run from backend/)\n    - Singletons reset so they pick up the new env\n    - Title/memory/summarization disabled to avoid extra LLM calls\n    - AppConfig built programmatically (avoids config.yaml param-name issues)\n    '
    # 1. Filesystem isolation
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setenv(
        "DEER_FLOW_PROJECT_ROOT",
        str(Path(__file__).resolve().parents[2]),
    )
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    monkeypatch.setattr("deerflow.sandbox.sandbox_provider._default_sandbox_provider", None)

    # 2. Inject a clean AppConfig. We must reset _app_config to None BEFORE
    # calling _make_e2e_config() because AppConfig() constructor misbehaves when
    # a disk config is already cached: it returns the cached model list instead
    # of the provided one. Clearing first ensures the test config is correct.
    monkeypatch.setattr("deerflow.config.app_config._app_config", None)
    monkeypatch.setattr("deerflow.config.app_config._app_config_is_custom", False)
    config = _make_e2e_config()
    monkeypatch.setattr("deerflow.config.app_config._app_config", config)
    monkeypatch.setattr("deerflow.config.app_config._app_config_is_custom", True)
    monkeypatch.setattr("deerflow.client.get_app_config", lambda: config)

    # 3. Disable title generation (extra LLM call, non-deterministic)
    from deerflow.config.title_config import TitleConfig

    monkeypatch.setattr("deerflow.config.title_config._title_config", TitleConfig(enabled=False))

    # 4. Disable memory queueing (avoids background threads & file writes)
    from deerflow.config.memory_config import MemoryConfig

    monkeypatch.setattr(
        "deerflow.agents.middlewares.memory_middleware.get_memory_config",
        lambda: MemoryConfig(enabled=False),
    )

    # 5. Ensure summarization is off (default, but be explicit)
    from deerflow.config.summarization_config import SummarizationConfig

    monkeypatch.setattr("deerflow.config.summarization_config._summarization_config", SummarizationConfig(enabled=False))

    # 6. Exclude TitleMiddleware from the chain.
    #    It triggers an extra LLM call to generate a thread title, which adds
    #    non-determinism and cost to E2E tests (title generation is already
    #    disabled via TitleConfig above, but the middleware still participates
    #    in the chain and can interfere with event ordering).
    from deerflow.agents.lead_agent.agent import build_middlewares as _original_build_middlewares
    from deerflow.agents.middlewares.title_middleware import TitleMiddleware

    def _sync_safe_build_middlewares(*args, **kwargs):
        '执行 _sync_safe_build_middlewares 的明确职责，并返回与调用约定一致的结果'
        mws = _original_build_middlewares(*args, **kwargs)
        return [m for m in mws if not isinstance(m, TitleMiddleware)]

    monkeypatch.setattr("deerflow.client.build_middlewares", _sync_safe_build_middlewares)

    return {"tmp_path": tmp_path}


@pytest.fixture()
def client(e2e_env):
    '执行 client 的明确职责，并返回与调用约定一致的结果。\n\nA DeerFlowClient wired to the isolated e2e_env.'
    return DeerFlowClient(checkpointer=None, thinking_enabled=False)


# ---------------------------------------------------------------------------
# Step 2: Basic streaming (requires LLM)
# ---------------------------------------------------------------------------


class TestBasicChat:
    '组织 TestBasicChat 场景的行为与边界验证。\n\nBasic chat and streaming behavior with real LLM.'

    @requires_llm
    def test_basic_chat(self, client):
        '验证 basic、chat 场景下的预期行为、边界条件与结果。\n\nchat() returns a non-empty text response.'
        result = client.chat("Say exactly: pong")
        assert isinstance(result, str)
        assert len(result) > 0

    @requires_llm
    def test_stream_event_sequence(self, client):
        '验证 stream、event、sequence 场景下的预期行为、边界条件与结果。\n\nstream() yields events: messages-tuple, values, and end.'
        events = list(client.stream("Say hi"))

        types = [e.type for e in events]
        assert types[-1] == "end"
        assert "messages-tuple" in types
        assert "values" in types

    @requires_llm
    def test_stream_event_data_format(self, client):
        '验证 stream、event、data、format 场景下的预期行为、边界条件与结果。\n\nEach event type has the expected data structure.'
        events = list(client.stream("Say hello"))

        for event in events:
            assert isinstance(event, StreamEvent)
            assert isinstance(event.type, str)
            assert isinstance(event.data, dict)

            if event.type == "messages-tuple" and event.data.get("type") == "ai":
                assert "content" in event.data
                assert "id" in event.data
            elif event.type == "values":
                assert "messages" in event.data
                assert "artifacts" in event.data
            elif event.type == "end":
                # end event may contain usage stats after token tracking was added
                assert isinstance(event.data, dict)

    @requires_llm
    def test_multi_turn_stateless(self, client):
        '验证 multi、turn、stateless 场景下的预期行为、边界条件与结果。\n\nWithout checkpointer, two calls to the same thread_id are independent.'
        tid = str(uuid.uuid4())

        r1 = client.chat("Remember the number 42", thread_id=tid)
        # Reset so agent is recreated (simulates no cross-turn state)
        client.reset_agent()
        r2 = client.chat("What number did I say?", thread_id=tid)

        # Without a checkpointer the second call has no memory of the first.
        # We can't assert exact content, but both should be non-empty.
        assert isinstance(r1, str) and len(r1) > 0
        assert isinstance(r2, str) and len(r2) > 0


# ---------------------------------------------------------------------------
# Step 3: Tool call flow (requires LLM)
# ---------------------------------------------------------------------------


class TestToolCallFlow:
    '组织 TestToolCallFlow 场景的行为与边界验证。\n\nVerify the LLM actually invokes tools through the real agent pipeline.'

    @requires_llm
    def test_tool_call_produces_events(self, client):
        '验证 tool、call、produces、events 场景下的预期行为、边界条件与结果。\n\nWhen the LLM decides to use a tool, we see tool call + result events.'
        # Give a clear instruction that forces a tool call
        events = list(client.stream("Use the bash tool to run: echo hello_e2e_test"))

        types = [e.type for e in events]
        assert types[-1] == "end"

        # Should have at least one tool call event
        tool_call_events = [e for e in events if e.type == "messages-tuple" and e.data.get("tool_calls")]
        tool_result_events = [e for e in events if e.type == "messages-tuple" and e.data.get("type") == "tool"]
        assert len(tool_call_events) >= 1, "Expected at least one tool_call event"
        assert len(tool_result_events) >= 1, "Expected at least one tool result event"

    @requires_llm
    def test_tool_call_event_structure(self, client):
        '验证 tool、call、event、structure 场景下的预期行为、边界条件与结果。\n\nTool call events contain name, args, and id fields.'
        events = list(client.stream("Use the read_file tool to read /mnt/user-data/workspace/nonexistent.txt"))

        tc_events = [e for e in events if e.type == "messages-tuple" and e.data.get("tool_calls")]
        if tc_events:
            tc = tc_events[0].data["tool_calls"][0]
            assert "name" in tc
            assert "args" in tc
            assert "id" in tc


# ---------------------------------------------------------------------------
# Step 4: File upload integration (no LLM needed for most)
# ---------------------------------------------------------------------------


class TestFileUploadIntegration:
    '组织 TestFileUploadIntegration 场景的行为与边界验证。\n\nUpload, list, and delete files through the real client path.'

    def test_upload_files(self, e2e_env, tmp_path):
        '验证 upload、files 场景下的预期行为、边界条件与结果。\n\nupload_files() copies files and returns metadata.'
        test_file = tmp_path / "source" / "readme.txt"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("Hello world")

        c = DeerFlowClient(checkpointer=None, thinking_enabled=False)
        tid = str(uuid.uuid4())

        result = c.upload_files(tid, [test_file])
        assert result["success"] is True
        assert len(result["files"]) == 1
        assert result["files"][0]["filename"] == "readme.txt"

        # Physically exists
        from deerflow.config.paths import get_paths
        from deerflow.runtime.user_context import get_effective_user_id

        assert (get_paths().sandbox_uploads_dir(tid, user_id=get_effective_user_id()) / "readme.txt").exists()

    def test_upload_duplicate_rename(self, e2e_env, tmp_path):
        '验证 upload、duplicate、rename 场景下的预期行为、边界条件与结果。\n\nUploading two files with the same name auto-renames the second.'
        d1 = tmp_path / "dir1"
        d2 = tmp_path / "dir2"
        d1.mkdir()
        d2.mkdir()
        (d1 / "data.txt").write_text("content A")
        (d2 / "data.txt").write_text("content B")

        c = DeerFlowClient(checkpointer=None, thinking_enabled=False)
        tid = str(uuid.uuid4())

        result = c.upload_files(tid, [d1 / "data.txt", d2 / "data.txt"])
        assert result["success"] is True
        assert len(result["files"]) == 2

        filenames = {f["filename"] for f in result["files"]}
        assert "data.txt" in filenames
        assert "data_1.txt" in filenames

    def test_upload_list_and_delete(self, e2e_env, tmp_path):
        '验证 upload、list、and、delete 场景下的预期行为、边界条件与结果。\n\nUpload → list → delete → list lifecycle.'
        test_file = tmp_path / "lifecycle.txt"
        test_file.write_text("lifecycle test")

        c = DeerFlowClient(checkpointer=None, thinking_enabled=False)
        tid = str(uuid.uuid4())

        c.upload_files(tid, [test_file])

        listing = c.list_uploads(tid)
        assert listing["count"] == 1
        assert listing["files"][0]["filename"] == "lifecycle.txt"

        del_result = c.delete_upload(tid, "lifecycle.txt")
        assert del_result["success"] is True

        listing = c.list_uploads(tid)
        assert listing["count"] == 0

    @requires_llm
    def test_upload_then_chat(self, e2e_env, tmp_path):
        '验证 upload、then、chat 场景下的预期行为、边界条件与结果。\n\nUpload a file then ask the LLM about it — UploadsMiddleware injects file info.'
        test_file = tmp_path / "source" / "notes.txt"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("The secret code is 7749.")

        c = DeerFlowClient(checkpointer=None, thinking_enabled=False)
        tid = str(uuid.uuid4())

        c.upload_files(tid, [test_file])
        # Chat — the middleware should inject <uploaded_files> context
        response = c.chat("What files are available?", thread_id=tid)
        assert isinstance(response, str) and len(response) > 0


# ---------------------------------------------------------------------------
# Step 5: Lifecycle and configuration (no LLM needed)
# ---------------------------------------------------------------------------


class TestLifecycleAndConfig:
    '组织 TestLifecycleAndConfig 场景的行为与边界验证。\n\nAgent recreation and configuration behavior.'

    @requires_llm
    def test_agent_recreation_on_config_change(self, client):
        '验证 agent、recreation、on、config、change 场景下的预期行为、边界条件与结果。\n\nChanging thinking_enabled triggers agent recreation (different config key).'
        list(client.stream("hi"))
        key1 = client._agent_config_key

        # Stream with a different config override
        client.reset_agent()
        list(client.stream("hi", thinking_enabled=True))
        key2 = client._agent_config_key

        # thinking_enabled changed: False → True → keys differ
        assert key1 != key2

    def test_reset_agent_clears_state(self, e2e_env):
        '验证 reset、agent、clears、state 场景下的预期行为、边界条件与结果。\n\nreset_agent() sets the internal agent to None.'
        c = DeerFlowClient(checkpointer=None, thinking_enabled=False)
        # Before any call, agent is None
        assert c._agent is None

        c.reset_agent()
        assert c._agent is None
        assert c._agent_config_key is None

    def test_plan_mode_config_key(self, e2e_env):
        '验证 plan、mode、config、key 场景下的预期行为、边界条件与结果。\n\nplan_mode is part of the config key tuple.'
        c = DeerFlowClient(checkpointer=None, plan_mode=False)
        cfg1 = c._get_runnable_config("test-thread")
        key1 = (
            cfg1["configurable"]["model_name"],
            cfg1["configurable"]["thinking_enabled"],
            cfg1["configurable"]["is_plan_mode"],
            cfg1["configurable"]["subagent_enabled"],
        )

        c2 = DeerFlowClient(checkpointer=None, plan_mode=True)
        cfg2 = c2._get_runnable_config("test-thread")
        key2 = (
            cfg2["configurable"]["model_name"],
            cfg2["configurable"]["thinking_enabled"],
            cfg2["configurable"]["is_plan_mode"],
            cfg2["configurable"]["subagent_enabled"],
        )

        assert key1 != key2
        assert key1[2] is False
        assert key2[2] is True


# ---------------------------------------------------------------------------
# Step 6: Middleware chain verification (requires LLM)
# ---------------------------------------------------------------------------


class TestMiddlewareChain:
    '组织 TestMiddlewareChain 场景的行为与边界验证。\n\nVerify middleware side effects through real execution.'

    @requires_llm
    def test_thread_data_paths_in_state(self, client):
        '验证 thread、data、paths、in、state 场景下的预期行为、边界条件与结果。\n\nAfter streaming, thread directory paths are computed correctly.'
        tid = str(uuid.uuid4())
        events = list(client.stream("hi", thread_id=tid))

        # The values event should contain messages
        values_events = [e for e in events if e.type == "values"]
        assert len(values_events) >= 1

        # ThreadDataMiddleware should have set paths in the state.
        # We verify the paths singleton can resolve the thread dir.
        from deerflow.config.paths import get_paths

        thread_dir = get_paths().thread_dir(tid)
        assert str(thread_dir).endswith(tid)

    @requires_llm
    def test_stream_completes_without_middleware_errors(self, client):
        '验证 stream、completes、without、middleware、errors 场景下的预期行为、边界条件与结果。\n\nFull middleware chain (ThreadData, Uploads, Sandbox, DanglingToolCall,\n        Memory, Clarification) executes without errors.'
        events = list(client.stream("What is 1+1?"))

        types = [e.type for e in events]
        assert types[-1] == "end"
        # Should have at least one AI response
        ai_events = [e for e in events if e.type == "messages-tuple" and e.data.get("type") == "ai"]
        assert len(ai_events) >= 1


# ---------------------------------------------------------------------------
# Step 7: Error and boundary conditions
# ---------------------------------------------------------------------------


class TestErrorAndBoundary:
    '组织 TestErrorAndBoundary 场景的行为与边界验证。\n\nError propagation and edge cases.'

    def test_upload_nonexistent_file_raises(self, e2e_env):
        "验证 upload、nonexistent、file、raises 场景下的预期行为、边界条件与结果。\n\nUploading a file that doesn't exist raises FileNotFoundError."
        c = DeerFlowClient(checkpointer=None, thinking_enabled=False)
        with pytest.raises(FileNotFoundError):
            c.upload_files("test-thread", ["/nonexistent/file.txt"])

    def test_delete_nonexistent_upload_raises(self, e2e_env):
        "验证 delete、nonexistent、upload、raises 场景下的预期行为、边界条件与结果。\n\nDeleting a file that doesn't exist raises FileNotFoundError."
        c = DeerFlowClient(checkpointer=None, thinking_enabled=False)
        tid = str(uuid.uuid4())
        # Ensure the uploads dir exists first
        c.list_uploads(tid)
        with pytest.raises(FileNotFoundError):
            c.delete_upload(tid, "ghost.txt")

    def test_artifact_path_traversal_blocked(self, e2e_env):
        '验证 artifact、path、traversal、blocked 场景下的预期行为、边界条件与结果。\n\nget_artifact blocks path traversal attempts.'
        c = DeerFlowClient(checkpointer=None, thinking_enabled=False)
        with pytest.raises(ValueError):
            c.get_artifact("test-thread", "../../etc/passwd")

    def test_upload_directory_rejected(self, e2e_env, tmp_path):
        '验证 upload、directory、rejected 场景下的预期行为、边界条件与结果。\n\nUploading a directory (not a file) is rejected.'
        d = tmp_path / "a_directory"
        d.mkdir()
        c = DeerFlowClient(checkpointer=None, thinking_enabled=False)
        with pytest.raises(ValueError, match="not a file"):
            c.upload_files("test-thread", [d])

    @requires_llm
    def test_empty_message_still_gets_response(self, client):
        '验证 empty、message、still、gets、response 场景下的预期行为、边界条件与结果。\n\nEven an empty-ish message should produce a valid event stream.'
        events = list(client.stream(" "))
        types = [e.type for e in events]
        assert types[-1] == "end"


# ---------------------------------------------------------------------------
# Step 8: Artifact access (no LLM needed)
# ---------------------------------------------------------------------------


class TestArtifactAccess:
    '组织 TestArtifactAccess 场景的行为与边界验证。\n\nRead artifacts through get_artifact() with real filesystem.'

    def test_get_artifact_happy_path(self, e2e_env):
        '验证 get、artifact、happy、path 场景下的预期行为、边界条件与结果。\n\nWrite a file to outputs, then read it back via get_artifact().'
        from deerflow.config.paths import get_paths
        from deerflow.runtime.user_context import get_effective_user_id

        c = DeerFlowClient(checkpointer=None, thinking_enabled=False)
        tid = str(uuid.uuid4())

        # Create an output file in the thread's outputs directory
        outputs_dir = get_paths().sandbox_outputs_dir(tid, user_id=get_effective_user_id())
        outputs_dir.mkdir(parents=True, exist_ok=True)
        (outputs_dir / "result.txt").write_text("hello artifact")

        data, mime = c.get_artifact(tid, "mnt/user-data/outputs/result.txt")
        assert data == b"hello artifact"
        assert "text" in mime

    def test_get_artifact_nested_path(self, e2e_env):
        '验证 get、artifact、nested、path 场景下的预期行为、边界条件与结果。\n\nArtifacts in subdirectories are accessible.'
        from deerflow.config.paths import get_paths
        from deerflow.runtime.user_context import get_effective_user_id

        c = DeerFlowClient(checkpointer=None, thinking_enabled=False)
        tid = str(uuid.uuid4())

        outputs_dir = get_paths().sandbox_outputs_dir(tid, user_id=get_effective_user_id())
        sub = outputs_dir / "charts"
        sub.mkdir(parents=True, exist_ok=True)
        (sub / "data.json").write_text('{"x": 1}')

        data, mime = c.get_artifact(tid, "mnt/user-data/outputs/charts/data.json")
        assert b'"x"' in data
        assert "json" in mime

    def test_get_artifact_nonexistent_raises(self, e2e_env):
        '验证 get、artifact、nonexistent、raises 场景下的预期行为、边界条件与结果。\n\nReading a nonexistent artifact raises FileNotFoundError.'
        c = DeerFlowClient(checkpointer=None, thinking_enabled=False)
        with pytest.raises(FileNotFoundError):
            c.get_artifact("test-thread", "mnt/user-data/outputs/ghost.txt")

    def test_get_artifact_traversal_within_prefix_blocked(self, e2e_env):
        '验证 get、artifact、traversal、within、prefix、blocked 场景下的预期行为、边界条件与结果。\n\nPath traversal within the valid prefix is still blocked.'
        c = DeerFlowClient(checkpointer=None, thinking_enabled=False)
        with pytest.raises((PermissionError, ValueError, FileNotFoundError)):
            c.get_artifact("test-thread", "mnt/user-data/outputs/../../etc/passwd")


# ---------------------------------------------------------------------------
# Step 9: Skill installation (no LLM needed)
# ---------------------------------------------------------------------------


class TestSkillInstallation:
    '组织 TestSkillInstallation 场景的行为与边界验证。\n\ninstall_skill() with real ZIP handling and filesystem.'

    @pytest.fixture(autouse=True)
    def _allow_skill_security_scan(self, monkeypatch):
        '执行 _allow_skill_security_scan 的明确职责，并返回与调用约定一致的结果'
        async def _scan(*args, **kwargs):
            '执行 _scan 的明确职责，并返回与调用约定一致的结果'
            from deerflow.skills.security_scanner import ScanResult

            return ScanResult(decision="allow", reason="ok")

        monkeypatch.setattr("deerflow.skills.installer.scan_skill_content", _scan)

    @pytest.fixture(autouse=True)
    def _isolate_skills_dir(self, tmp_path, monkeypatch):
        '执行 _isolate_skills_dir 的明确职责，并返回与调用约定一致的结果。\n\nRedirect skill installation to a temp directory.'
        skills_root = tmp_path / "skills"
        (skills_root / "public").mkdir(parents=True)
        (skills_root / "custom").mkdir(parents=True)
        from deerflow.skills.storage.local_skill_storage import LocalSkillStorage

        local_storage = LocalSkillStorage(host_path=str(skills_root))
        monkeypatch.setattr(
            "deerflow.skills.storage._default_skill_storage",
            local_storage,
        )
        monkeypatch.setattr(
            "deerflow.client.get_or_new_user_skill_storage",
            lambda user_id, **kwargs: local_storage,
        )
        self._skills_root = skills_root

    @staticmethod
    def _make_skill_zip(tmp_path, skill_name="test-e2e-skill"):
        '执行 _make_skill_zip 的明确职责，并返回与调用约定一致的结果。\n\nCreate a minimal valid .skill archive.'
        skill_dir = tmp_path / "build" / skill_name
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(f"---\nname: {skill_name}\ndescription: E2E test skill\n---\n\nTest content.\n")
        archive_path = tmp_path / f"{skill_name}.skill"
        with zipfile.ZipFile(archive_path, "w") as zf:
            for file in skill_dir.rglob("*"):
                zf.write(file, file.relative_to(tmp_path / "build"))
        return archive_path

    def test_install_skill_success(self, e2e_env, tmp_path):
        '验证 install、skill、success 场景下的预期行为、边界条件与结果。\n\nA valid .skill archive installs to the custom skills directory.'
        archive = self._make_skill_zip(tmp_path)
        c = DeerFlowClient(checkpointer=None, thinking_enabled=False)

        result = c.install_skill(archive)
        assert result["success"] is True
        assert result["skill_name"] == "test-e2e-skill"
        assert (self._skills_root / "custom" / "test-e2e-skill" / "SKILL.md").exists()

    def test_install_skill_duplicate_rejected(self, e2e_env, tmp_path):
        '验证 install、skill、duplicate、rejected 场景下的预期行为、边界条件与结果。\n\nInstalling the same skill twice raises ValueError.'
        archive = self._make_skill_zip(tmp_path)
        c = DeerFlowClient(checkpointer=None, thinking_enabled=False)

        c.install_skill(archive)
        with pytest.raises(ValueError, match="already exists"):
            c.install_skill(archive)

    def test_install_skill_invalid_extension(self, e2e_env, tmp_path):
        '验证 install、skill、invalid、extension 场景下的预期行为、边界条件与结果。\n\nA file without .skill extension is rejected.'
        bad_file = tmp_path / "not_a_skill.zip"
        bad_file.write_bytes(b"PK\x03\x04")  # ZIP magic bytes
        c = DeerFlowClient(checkpointer=None, thinking_enabled=False)
        with pytest.raises(ValueError, match=".skill extension"):
            c.install_skill(bad_file)

    def test_install_skill_missing_frontmatter(self, e2e_env, tmp_path):
        '验证 install、skill、missing、frontmatter 场景下的预期行为、边界条件与结果。\n\nA .skill archive without valid SKILL.md frontmatter is rejected.'
        skill_dir = tmp_path / "build" / "bad-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("No frontmatter here.")

        archive = tmp_path / "bad-skill.skill"
        with zipfile.ZipFile(archive, "w") as zf:
            for file in skill_dir.rglob("*"):
                zf.write(file, file.relative_to(tmp_path / "build"))

        c = DeerFlowClient(checkpointer=None, thinking_enabled=False)
        with pytest.raises(ValueError, match="Invalid skill"):
            c.install_skill(archive)

    def test_install_skill_nonexistent_file(self, e2e_env):
        '验证 install、skill、nonexistent、file 场景下的预期行为、边界条件与结果。\n\nInstalling from a nonexistent path raises FileNotFoundError.'
        c = DeerFlowClient(checkpointer=None, thinking_enabled=False)
        with pytest.raises(FileNotFoundError):
            c.install_skill("/nonexistent/skill.skill")


# ---------------------------------------------------------------------------
# Step 10: Configuration management (no LLM needed)
# ---------------------------------------------------------------------------


class TestConfigManagement:
    '组织 TestConfigManagement 场景的行为与边界验证。\n\nConfig queries and updates through real code paths.'

    def test_list_models_returns_injected_config(self, e2e_env):
        '验证 list、models、returns、injected、config 场景下的预期行为、边界条件与结果。\n\nlist_models() returns the model from the injected AppConfig.'
        expected_model_name = os.getenv("E2E_MODEL_NAME", "volcengine-ark")
        c = DeerFlowClient(checkpointer=None, thinking_enabled=False)
        result = c.list_models()
        assert "models" in result
        assert len(result["models"]) == 1
        assert result["models"][0]["name"] == expected_model_name
        assert result["models"][0]["display_name"] == "E2E Test Model"

    def test_get_model_found(self, e2e_env):
        '验证 get、model、found 场景下的预期行为、边界条件与结果。\n\nget_model() returns the model when it exists.'
        expected_model_name = os.getenv("E2E_MODEL_NAME", "volcengine-ark")
        c = DeerFlowClient(checkpointer=None, thinking_enabled=False)
        model = c.get_model(expected_model_name)
        assert model is not None
        assert model["name"] == expected_model_name
        assert model["supports_thinking"] is False

    def test_get_model_not_found(self, e2e_env):
        '验证 get、model、not、found 场景下的预期行为、边界条件与结果。\n\nget_model() returns None for nonexistent model.'
        c = DeerFlowClient(checkpointer=None, thinking_enabled=False)
        assert c.get_model("nonexistent-model") is None

    def test_list_skills_returns_list(self, e2e_env):
        "验证 list、skills、returns、list 场景下的预期行为、边界条件与结果。\n\nlist_skills() returns a dict with 'skills' key from real directory scan."
        c = DeerFlowClient(checkpointer=None, thinking_enabled=False)
        result = c.list_skills()
        assert "skills" in result
        assert isinstance(result["skills"], list)
        # The real skills/ directory should have some public skills
        assert len(result["skills"]) > 0

    def test_get_skill_found(self, e2e_env):
        '验证 get、skill、found 场景下的预期行为、边界条件与结果。\n\nget_skill() returns skill info for a known public skill.'
        c = DeerFlowClient(checkpointer=None, thinking_enabled=False)
        # 'deep-research' is a built-in public skill
        skill = c.get_skill("deep-research")
        if skill is not None:
            assert skill["name"] == "deep-research"
            assert "description" in skill
            assert "enabled" in skill

    def test_get_skill_not_found(self, e2e_env):
        '验证 get、skill、not、found 场景下的预期行为、边界条件与结果。\n\nget_skill() returns None for nonexistent skill.'
        c = DeerFlowClient(checkpointer=None, thinking_enabled=False)
        assert c.get_skill("nonexistent-skill-xyz") is None

    def test_get_mcp_config_returns_dict(self, e2e_env):
        "验证 get、mcp、config、returns、dict 场景下的预期行为、边界条件与结果。\n\nget_mcp_config() returns a dict with 'mcp_servers' key."
        c = DeerFlowClient(checkpointer=None, thinking_enabled=False)
        result = c.get_mcp_config()
        assert "mcp_servers" in result
        assert isinstance(result["mcp_servers"], dict)

    def test_update_mcp_config_writes_and_invalidates(self, e2e_env, tmp_path, monkeypatch):
        '验证 update、mcp、config、writes、and、invalidates 场景下的预期行为、边界条件与结果。\n\nupdate_mcp_config() writes extensions_config.json and invalidates the agent.'
        # Set up a writable extensions_config.json
        config_file = tmp_path / "extensions_config.json"
        config_file.write_text(json.dumps({"mcpServers": {}, "skills": {}}))
        monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(config_file))

        # Force reload so the singleton picks up our test file
        from deerflow.config.extensions_config import reload_extensions_config

        reload_extensions_config()

        c = DeerFlowClient(checkpointer=None, thinking_enabled=False)
        # Simulate a cached agent
        c._agent = "fake-agent-placeholder"
        c._agent_config_key = ("a", "b", "c", "d")

        result = c.update_mcp_config({"test-server": {"enabled": True, "type": "stdio", "command": "echo"}})
        assert "mcp_servers" in result

        # Agent should be invalidated
        assert c._agent is None
        assert c._agent_config_key is None

        # File should be written
        written = json.loads(config_file.read_text())
        assert "test-server" in written["mcpServers"]

    def test_update_skill_writes_and_invalidates(self, e2e_env, tmp_path, monkeypatch):
        '验证 update、skill、writes、and、invalidates 场景下的预期行为、边界条件与结果。\n\nupdate_skill() writes extensions_config.json and invalidates the agent.'
        config_file = tmp_path / "extensions_config.json"
        config_file.write_text(json.dumps({"mcpServers": {}, "skills": {}}))
        monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(config_file))

        from deerflow.config.extensions_config import reload_extensions_config

        reload_extensions_config()

        c = DeerFlowClient(checkpointer=None, thinking_enabled=False)
        c._agent = "fake-agent-placeholder"
        c._agent_config_key = ("a", "b", "c", "d")

        # Use a real skill name from the public skills directory
        skills = c.list_skills()
        if not skills["skills"]:
            pytest.skip("No skills available for testing")
        skill_name = skills["skills"][0]["name"]

        result = c.update_skill(skill_name, enabled=False)
        assert result["name"] == skill_name
        assert result["enabled"] is False

        # Agent should be invalidated
        assert c._agent is None
        assert c._agent_config_key is None

    def test_update_skill_nonexistent_raises(self, e2e_env, tmp_path, monkeypatch):
        '验证 update、skill、nonexistent、raises 场景下的预期行为、边界条件与结果。\n\nupdate_skill() raises ValueError for nonexistent skill.'
        config_file = tmp_path / "extensions_config.json"
        config_file.write_text(json.dumps({"mcpServers": {}, "skills": {}}))
        monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(config_file))

        from deerflow.config.extensions_config import reload_extensions_config

        reload_extensions_config()

        c = DeerFlowClient(checkpointer=None, thinking_enabled=False)
        with pytest.raises(ValueError, match="not found"):
            c.update_skill("nonexistent-skill-xyz", enabled=True)


# ---------------------------------------------------------------------------
# Step 11: Memory access (no LLM needed)
# ---------------------------------------------------------------------------


class TestMemoryAccess:
    '组织 TestMemoryAccess 场景的行为与边界验证。\n\nMemory system queries through real code paths.'

    def test_get_memory_returns_dict(self, e2e_env):
        '验证 get、memory、returns、dict 场景下的预期行为、边界条件与结果。\n\nget_memory() returns a dict (may be empty initial state).'
        c = DeerFlowClient(checkpointer=None, thinking_enabled=False)
        result = c.get_memory()
        assert isinstance(result, dict)

    def test_reload_memory_returns_dict(self, e2e_env):
        '验证 reload、memory、returns、dict 场景下的预期行为、边界条件与结果。\n\nreload_memory() forces reload and returns a dict.'
        c = DeerFlowClient(checkpointer=None, thinking_enabled=False)
        result = c.reload_memory()
        assert isinstance(result, dict)

    def test_get_memory_config_fields(self, e2e_env):
        '验证 get、memory、config、fields 场景下的预期行为、边界条件与结果。\n\nget_memory_config() returns expected config fields.'
        c = DeerFlowClient(checkpointer=None, thinking_enabled=False)
        result = c.get_memory_config()
        assert "enabled" in result
        assert "injection_enabled" in result
        assert "manager_class" in result
        assert "backend_config" in result
        assert "mode" in result

    def test_get_memory_status_combines_config_and_data(self, e2e_env):
        "验证 get、memory、status、combines、config、and、data 场景下的预期行为、边界条件与结果。\n\nget_memory_status() returns both 'config' and 'data' keys."
        c = DeerFlowClient(checkpointer=None, thinking_enabled=False)
        result = c.get_memory_status()
        assert "config" in result
        assert "data" in result
        assert "enabled" in result["config"]
        assert "mode" in result["config"]
        assert isinstance(result["data"], dict)
