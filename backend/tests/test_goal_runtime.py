"""验证当前测试场景在真实调用中的结果、异常与状态边界。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from deerflow.runtime import goal


def test_build_goal_state_defaults_to_claude_stop_hook_cap():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    state = goal.build_goal_state("Finish the tests")

    assert state["objective"] == "Finish the tests"
    assert state["status"] == "active"
    assert state["continuation_count"] == 0
    assert state["max_continuations"] == 8
    assert state["no_progress_count"] == 0
    assert state["max_no_progress_continuations"] == 2
    assert state["created_at"]


def test_parse_goal_evaluation_extracts_json_object_from_fenced_response():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    parsed = goal.parse_goal_evaluation_response('```json\n{"satisfied": true, "reason": "All requested tests pass.", "evidence_summary": "pytest passed"}\n```')

    assert parsed["satisfied"] is True
    assert parsed["blocker"] == "none"
    assert parsed["reason"] == "All requested tests pass."
    assert parsed["evidence_summary"] == "pytest passed"


def test_parse_goal_evaluation_strips_think_blocks():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    parsed = goal.parse_goal_evaluation_response('<think>maybe {"satisfied": false}</think>\n{"satisfied": false, "reason": "Missing verification."}')

    assert parsed["satisfied"] is False
    assert parsed["blocker"] == "missing_evidence"
    assert parsed["reason"] == "Missing verification."


def test_parse_goal_evaluation_preserves_typed_blocker():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    parsed = goal.parse_goal_evaluation_response('{"satisfied": false, "blocker": "needs_user_input", "reason": "The user must choose a deployment target."}')

    assert parsed["satisfied"] is False
    assert parsed["blocker"] == "needs_user_input"


def test_format_visible_conversation_excludes_hidden_and_system_messages():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    messages = [
        SystemMessage(content="internal"),
        HumanMessage(content="visible user"),
        HumanMessage(content="hidden control", additional_kwargs={"hide_from_ui": True}),
        AIMessage(content="visible assistant"),
    ]

    formatted = goal.format_visible_conversation(messages)

    assert "visible user" in formatted
    assert "visible assistant" in formatted
    assert "hidden control" not in formatted
    assert "internal" not in formatted


def test_should_continue_goal_respects_completion_and_cap():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    active = goal.build_goal_state("Finish", max_continuations=2)
    unmet = goal.GoalEvaluation(satisfied=False, blocker="goal_not_met_yet", reason="not yet")
    met = goal.GoalEvaluation(satisfied=True, blocker="none", reason="done")
    missing_evidence = goal.GoalEvaluation(satisfied=False, blocker="missing_evidence", reason="weak transcript")

    assert goal.should_continue_goal(active, unmet) is True
    assert goal.should_continue_goal({**active, "continuation_count": 2}, unmet) is False
    assert goal.should_continue_goal(active, met) is False
    assert goal.should_continue_goal(active, missing_evidence) is False


def test_should_continue_goal_respects_no_progress_cap():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    active = goal.build_goal_state("Finish")
    unmet = goal.GoalEvaluation(satisfied=False, blocker="goal_not_met_yet", reason="same evidence")

    assert goal.should_continue_goal(active, unmet, no_progress_count=0) is True
    assert goal.should_continue_goal(active, unmet, no_progress_count=active["max_no_progress_continuations"]) is False


def test_make_goal_continuation_message_is_hidden_from_ui():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    state = goal.build_goal_state("Finish the implementation")
    evaluation = goal.GoalEvaluation(satisfied=False, blocker="goal_not_met_yet", reason="Tests have not run")

    message = goal.make_goal_continuation_message(state, evaluation)

    assert message.additional_kwargs["hide_from_ui"] is True
    assert "Finish the implementation" in message.content
    assert "Tests have not run" in message.content


def test_evaluate_goal_completion_uses_non_thinking_model(monkeypatch):
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    fake_model = MagicMock()
    fake_model.ainvoke = AsyncMock(return_value=SimpleNamespace(content='{"satisfied": true, "reason": "Done", "evidence_summary": "Done"}'))
    captured = {}

    def fake_create_chat_model(**kwargs):
        """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
        captured.update(kwargs)
        return fake_model

    monkeypatch.setattr(goal, "create_chat_model", fake_create_chat_model)
    state = goal.build_goal_state("Finish")

    result = asyncio.run(
        goal.evaluate_goal_completion(
            state,
            [
                HumanMessage(content="Please finish this."),
                AIMessage(content="Done."),
            ],
            app_config=object(),
        )
    )

    assert result["satisfied"] is True
    assert result["blocker"] == "none"
    assert captured["thinking_enabled"] is False
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    assert captured["attach_tracing"] is True
    fake_model.ainvoke.assert_awaited_once()
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    # 说明当前测试分支所验证的真实行为与边界。
    assert fake_model.ainvoke.await_args.kwargs["config"] == {"run_name": "goal_evaluator"}


def test_evaluate_goal_completion_injects_langfuse_metadata(monkeypatch):
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    from deerflow.config.tracing_config import reset_tracing_config

    for name in ("LANGFUSE_TRACING", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LANGFUSE_TRACING", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    reset_tracing_config()

    fake_model = MagicMock()
    fake_model.ainvoke = AsyncMock(return_value=SimpleNamespace(content='{"satisfied": true, "reason": "Done", "evidence_summary": "Done"}'))
    state = goal.build_goal_state("Finish")

    try:
        result = asyncio.run(
            goal.evaluate_goal_completion(
                state,
                [
                    HumanMessage(content="Please finish this."),
                    AIMessage(content="Done."),
                ],
                model=fake_model,
                model_name="gpt-4o",
                app_config=object(),
                thread_id="thread-xyz",
                user_id="alice",
                deerflow_trace_id="gateway-trace-1",
            )
        )
    finally:
        reset_tracing_config()

    assert result["satisfied"] is True
    fake_model.ainvoke.assert_awaited_once()
    config = fake_model.ainvoke.await_args.kwargs["config"]
    assert config["run_name"] == "goal_evaluator"
    metadata = config.get("metadata") or {}
    assert metadata.get("langfuse_session_id") == "thread-xyz", "goal evaluator trace must group under the thread's session"
    assert metadata.get("langfuse_user_id") == "alice"
    assert metadata.get("langfuse_trace_name") == "goal_evaluator"
    assert metadata.get("deerflow_trace_id") == "gateway-trace-1"
    tags = metadata.get("langfuse_tags") or []
    assert "model:gpt-4o" in tags


def test_evaluate_goal_completion_uses_injected_model(monkeypatch):
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    fake_model = MagicMock()
    fake_model.ainvoke = AsyncMock(return_value=SimpleNamespace(content='{"satisfied": true, "reason": "Done", "evidence_summary": "Done"}'))
    create_chat_model = MagicMock()
    monkeypatch.setattr(goal, "create_chat_model", create_chat_model)
    state = goal.build_goal_state("Finish")

    result = asyncio.run(
        goal.evaluate_goal_completion(
            state,
            [
                HumanMessage(content="Please finish this."),
                AIMessage(content="Done."),
            ],
            model=fake_model,
            app_config=object(),
        )
    )

    assert result["satisfied"] is True
    create_chat_model.assert_not_called()
    fake_model.ainvoke.assert_awaited_once()


def test_evaluate_goal_completion_fails_closed_without_assistant_evidence(monkeypatch):
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    fake_model = MagicMock()
    fake_model.ainvoke = AsyncMock()
    monkeypatch.setattr(goal, "create_chat_model", lambda **_kwargs: fake_model)
    state = goal.build_goal_state("Finish")

    result = asyncio.run(goal.evaluate_goal_completion(state, [HumanMessage(content="please do it")], app_config=object()))

    assert result["satisfied"] is False
    assert result["blocker"] == "missing_evidence"
    fake_model.ainvoke.assert_not_called()


def test_attach_goal_evaluation_records_blocker_progress_and_stand_down_reason():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    state = goal.build_goal_state("Finish")
    evaluation = goal.GoalEvaluation(
        satisfied=False,
        blocker="external_wait",
        reason="Waiting for deployment",
        evidence_summary="Deploy is pending",
    )

    updated = goal.attach_goal_evaluation(
        state,
        evaluation,
        run_id="run-1",
        no_progress_count=1,
        stand_down_reason="blocked:external_wait",
    )

    assert updated["no_progress_count"] == 1
    assert updated["last_evaluation"]["blocker"] == "external_wait"
    assert updated["last_evaluation"]["evidence_summary"] == "Deploy is pending"
    assert updated["last_evaluation"]["stand_down_reason"] == "blocked:external_wait"
    assert updated["last_evaluation"]["progress_key"]


def test_latest_visible_assistant_signature_tracks_last_ai_evidence():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    base = [HumanMessage(content="go"), AIMessage(content="answer one")]
    sig1 = goal.latest_visible_assistant_signature(base)
    # 说明当前测试分支所验证的真实行为与边界。
    sig1_again = goal.latest_visible_assistant_signature([HumanMessage(content="different prompt"), AIMessage(content="answer one")])
    # 说明当前测试分支所验证的真实行为与边界。
    sig2 = goal.latest_visible_assistant_signature([HumanMessage(content="go"), AIMessage(content="answer two")])

    assert sig1 and sig1 == sig1_again
    assert sig1 != sig2
    # 说明当前测试分支所验证的真实行为与边界。
    hidden = AIMessage(content="hidden", additional_kwargs={"hide_from_ui": True})
    assert goal.latest_visible_assistant_signature([HumanMessage(content="only human"), hidden]) == ""


def test_no_progress_count_keys_on_evidence_not_volatile_free_text():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    evidence = "I made a start, but I am not done."
    first = goal.GoalEvaluation(satisfied=False, blocker="goal_not_met_yet", reason="The same work remains.", evidence_summary="No new verification evidence.")
    prior = goal.attach_goal_evaluation(goal.build_goal_state("Finish"), first, run_id="r1", no_progress_count=0, evidence_signature=evidence)

    reworded = goal.GoalEvaluation(satisfied=False, blocker="goal_not_met_yet", reason="Still the same outstanding work, phrased differently.", evidence_summary="Evidence remains thin; nothing new verified.")
    assert goal.compute_no_progress_count(prior, reworded, evidence_signature=evidence) == 1


def test_no_progress_count_resets_when_evidence_advances():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    first = goal.GoalEvaluation(satisfied=False, blocker="goal_not_met_yet", reason="x", evidence_summary="y")
    prior = goal.attach_goal_evaluation(goal.build_goal_state("Finish"), first, run_id="r1", no_progress_count=1, evidence_signature="step 1 done")

    # 说明当前测试分支所验证的真实行为与边界。
    assert goal.compute_no_progress_count(prior, first, evidence_signature="step 2 done") == 0


def test_parse_goal_command_status_for_empty_and_whitespace():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    assert goal.parse_goal_command("") == goal.GoalCommand("status")
    assert goal.parse_goal_command("   ") == goal.GoalCommand("status")


def test_parse_goal_command_clear_aliases_case_insensitive():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    for alias in ("clear", "reset", "off", "CLEAR", "  Reset  ", "Off"):
        assert goal.parse_goal_command(alias) == goal.GoalCommand("clear")


def test_parse_goal_command_set_trims_and_preserves_objective():
    """验证当前测试场景在真实调用中的结果、异常与状态边界。"""
    assert goal.parse_goal_command("  finish the work  ") == goal.GoalCommand("set", "finish the work")
    # 说明当前测试分支所验证的真实行为与边界。
    assert goal.parse_goal_command("clear the build cache") == goal.GoalCommand("set", "clear the build cache")
