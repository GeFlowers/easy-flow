'定义 test_deermem_self_contained 模块提供的职责与可复用接口。\n\nPhase-2 (self-contained DeerMem) tests.\n\nCovers: DI construction (owns storage/updater/queue/llm), zero-config defaults,\n``trace_id`` threading to the optional ``tracing_callback``, langfuse being\noptional, ``hide_from_ui`` default-skip + hook-keep, empty ``storage_class``\n(portable default), and portability -- ``backends/deermem/`` has exactly one\n``from deerflow`` line (the ABC contract) and can be vendored into another agent\nby copying the folder and repointing that one line.\n\nStorage is isolated via ``$DEERMEM_DATA_DIR`` -> ``tmp_path``; the LLM is a fake\ninjected onto the updater so no network is needed.\n'

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.memory.backends.deermem.deer_mem import DeerMem
from deerflow.agents.memory.backends.deermem.deermem.core.message_processing import (
    filter_messages_for_memory,
)
from deerflow.agents.memory.backends.deermem.deermem.core.storage import FileMemoryStorage
from deerflow.agents.memory.backends.deermem.deermem.core.updater import _trim_facts_to_max


@pytest.fixture
def deermem_data_dir(tmp_path, monkeypatch):
    '执行 deermem_data_dir 的明确职责，并返回与调用约定一致的结果。\n\nIsolate DeerMem storage under tmp_path via $DEERMEM_DATA_DIR.'
    d = tmp_path / "deermem_data"
    d.mkdir()
    monkeypatch.setenv("DEERMEM_DATA_DIR", str(d))
    yield d


class _FakeLLM:
    '封装 _FakeLLM 的状态、协作关系与公开操作。\n\nReturns a fixed memory-update JSON so no real LLM/network is needed.'

    def __init__(self, payload: str | None = None) -> None:
        '实现 __init__ 协议方法，保持对象交互语义一致'
        self._payload = payload or '{"user":{},"history":{},"newFacts":[],"factsToRemove":[]}'

    def invoke(self, prompt, config=None):
        '执行 invoke 的明确职责，并返回与调用约定一致的结果'
        return type("R", (), {"content": self._payload})()


def _deermem_with_fake_llm(backend_config=None, payload=None) -> DeerMem:
    '执行 _deermem_with_fake_llm 的明确职责，并返回与调用约定一致的结果'
    dm = DeerMem(backend_config=backend_config)
    fake = _FakeLLM(payload)
    dm._llm = fake
    dm._updater._llm = fake
    return dm


def test_di_construction_owns_dependencies():
    '验证 di、construction、owns、dependencies 场景下的预期行为、边界条件与结果'
    dm = DeerMem(backend_config={"max_facts": 50, "storage_path": "/tmp/x"})
    assert dm._config.max_facts == 50
    assert dm._storage is not None and dm._updater is not None and dm._queue is not None
    # 依赖项是有线的 (DI)，而不是全局的：
    assert dm._updater._storage is dm._storage
    assert dm._queue._updater is dm._updater


def test_zero_config_defaults_run_non_llm_ops(deermem_data_dir):
    '验证 zero、config、defaults、run、non、llm、ops 场景下的预期行为、边界条件与结果'
    dm = DeerMem(backend_config=None)  # zero config
    assert dm._llm is None  # no model -> no LLM
    dm.import_memory(
        {"version": "1.0", "lastUpdated": "", "user": {}, "history": {}, "facts": [{"id": "f", "content": "x", "category": "c", "confidence": 0.5, "createdAt": "", "source": "m"}]},
        user_id="u",
    )
    assert "x" in dm.get_context(user_id="u")
    assert dm.get_memory(user_id="u")["facts"][0]["content"] == "x"


def test_trace_id_threads_through_to_tracing_callback(deermem_data_dir):
    '验证 trace、id、threads、through、to、tracing、callback 场景下的预期行为、边界条件与结果'
    calls = []

    def tracer(cfg, *, thread_id, user_id, trace_id, model_name):
        '执行 tracer 的明确职责，并返回与调用约定一致的结果'
        calls.append((thread_id, trace_id, model_name))

    dm = _deermem_with_fake_llm({"tracing_callback": tracer, "model": {"provider": "openai", "model": "gpt-x", "api_key": "k", "base_url": "u"}})
    dm.add(
        thread_id="t1",
        messages=[HumanMessage(content="hi"), AIMessage(content="hello")],
        agent_name=None,
        user_id="u1",
        trace_id="trace-42",
    )
    dm._queue.flush()
    assert calls and calls[0] == ("t1", "trace-42", "gpt-x")


def test_tracing_callback_optional_no_langfuse(deermem_data_dir):
    '验证 tracing、callback、optional、no、langfuse 场景下的预期行为、边界条件与结果'
    dm = _deermem_with_fake_llm({"model": {"provider": "openai", "model": "gpt-x", "api_key": "k", "base_url": "u"}})
    assert dm._config.tracing_callback is None  # langfuse not hard-required
    dm.add(
        thread_id="t2",
        messages=[HumanMessage(content="hi"), AIMessage(content="hello")],
        agent_name=None,
        user_id="u2",
        trace_id="t-99",
    )
    dm._queue.flush()  # no callback, no error, update completes


def test_hide_from_ui_default_skip_hook_keeps():
    '验证 hide、from、ui、default、skip、hook、keeps 场景下的预期行为、边界条件与结果'
    hidden = HumanMessage(content="secret", additional_kwargs={"hide_from_ui": True})
    normal = HumanMessage(content="hi")
    ai = AIMessage(content="hello")
    # 默认（无钩子）-> hide_from_ui 已跳过
    assert hidden not in filter_messages_for_memory([hidden, normal, ai])
    # 钩子返回 True -> 隐藏保留
    assert hidden in filter_messages_for_memory([hidden, normal, ai], should_keep_hidden_message=lambda ak: True)


def test_storage_class_empty_uses_filememorystorage():
    # 空 storage_class (默认) -> 直接使用 FileMemoryStorage，无需 importlib (可移植，零噪音)
    '验证 storage、class、empty、uses、filememorystorage 场景下的预期行为、边界条件与结果'
    dm = DeerMem(backend_config=None)
    assert dm._config.storage_class == ""
    assert isinstance(dm._storage, FileMemoryStorage)


def test_portability_only_abc_contract_imports_deerflow():
    '验证 portability、only、abc、contract、imports、deerflow 场景下的预期行为、边界条件与结果。\n\nbackends/deermem/ has exactly ONE `from deerflow` line: the ABC contract in deer_mem.py.'
    import deerflow.agents.memory.backends.deermem as pkg

    root = Path(pkg.__file__).parent
    deerflow_imports = []
    for p in root.rglob("*.py"):
        for line in p.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s.startswith("from deerflow") or s.startswith("import deerflow"):
                deerflow_imports.append((p.relative_to(root).as_posix(), s))
    assert len(deerflow_imports) == 1, deerflow_imports
    assert deerflow_imports[0][0] == "deer_mem.py"
    assert "memory.manager import MemoryManager" in deerflow_imports[0][1]


# Minimal vendored host contract (what another agent would ship). DeerMem only
# 最小供应商主机合同（其他代理将运送的内容）。仅限鹿蜜
_VENDORED_MANAGER_PY = '''
"""Vendored host contract (minimal ABC) for the portability demo."""
from abc import ABC, abstractmethod
from typing import Any

class MemoryManager(ABC):
    def __init__(self, backend_config: dict | None = None) -> None:
        self._backend_config = backend_config
    @abstractmethod
    def add(self, thread_id, messages, *, agent_name=None, user_id=None, trace_id=None) -> None: ...
    @abstractmethod
    def add_nowait(self, thread_id, messages, *, agent_name=None, user_id=None) -> None: ...
    @abstractmethod
    def get_context(self, user_id, *, agent_name=None, thread_id=None) -> str: ...
    @abstractmethod
    def search(self, query, top_k=5, *, user_id=None, agent_name=None) -> list: ...
    @abstractmethod
    def get_memory(self, *, user_id=None, agent_name=None) -> dict: ...
    @abstractmethod
    def delete_memory(self, *, user_id=None, agent_name=None) -> None: ...
    @abstractmethod
    def clear_memory(self, *, user_id=None, agent_name=None) -> dict: ...
    @abstractmethod
    def import_memory(self, memory_data, *, user_id=None, agent_name=None) -> dict: ...
    @abstractmethod
    def export_memory(self, *, user_id=None, agent_name=None) -> dict: ...
'''


def test_portability_vendor_to_other_agent(tmp_path, monkeypatch):
    '验证 portability、vendor、to、other、agent 场景下的预期行为、边界条件与结果。\n\nCopy backends/deermem/ into a temp package, repoint the ONE ABC import to\n    a vendored manager, import, and run a round-trip -- proves copy + 1-line +\n    run portability (zero deerflow dependency at runtime).'
    import importlib
    import shutil

    import deerflow.agents.memory.backends.deermem as pkg

    src = Path(pkg.__file__).parent
    # 带有最小manager.py（合同）的供应主机包。
    host_pkg = tmp_path / "otheragent"
    host_pkg.mkdir()
    (host_pkg / "__init__.py").write_text("", encoding="utf-8")
    (host_pkg / "manager.py").write_text(_VENDORED_MANAGER_PY, encoding="utf-8")
    # 复制DeerMem后端文件夹。
    dst_pkg = tmp_path / "otheragent_deermem"
    shutil.copytree(src, dst_pkg)
    # 将单个 ABC 合同导入行重新指向供应商管理器。
    deer_mem_file = dst_pkg / "deer_mem.py"
    text = deer_mem_file.read_text(encoding="utf-8")
    assert "from deerflow.agents.memory.manager import MemoryManager" in text
    text = text.replace(
        "from deerflow.agents.memory.manager import MemoryManager",
        "from otheragent.manager import MemoryManager",
    )
    deer_mem_file.write_text(text, encoding="utf-8")

    monkeypatch.setenv("DEERMEM_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.syspath_prepend(str(tmp_path))
    try:
        mod = importlib.import_module("otheragent_deermem.deer_mem")
        assert hasattr(mod, "DeerMem")
        dm = mod.DeerMem(backend_config=None)  # zero config, self._llm=None
        dm.import_memory(
            {"version": "1.0", "lastUpdated": "", "user": {}, "history": {}, "facts": [{"id": "f", "content": "y", "category": "c", "confidence": 0.5, "createdAt": "", "source": "m"}]},
            user_id="ua",
        )
        assert "y" in dm.get_context(user_id="ua")
    finally:
        for k in [k for k in list(sys.modules) if k.startswith("otheragent_deermem") or k == "otheragent"]:
            sys.modules.pop(k, None)


def test_per_user_memory_path_matches_host_safe_user_id(deermem_data_dir):
    "验证 per、user、memory、path、matches、host、safe、user、id 场景下的预期行为、边界条件与结果。\n\nPin the per-user memory path across the abstraction.\n\n    DeerMem writes memory to ``{storage_path}/users/{safe_user_id}/memory.json``\n    where ``safe_user_id`` is byte-identical to the host's ``make_safe_user_id``.\n    The factory injects ``runtime_home()`` (= base_dir) as ``storage_path``, so\n    the on-disk path is ``{base_dir}/users/{uid}/memory.json`` -- identical to\n    pre-abstraction. This locks that equivalence so a future change to DeerMem's\n    path / safe_user_id logic can't silently orphan existing per-user memory\n    (risk:high, persistent state).\n    "
    from deerflow.config.paths import make_safe_user_id

    user_id = "test-user-123@example.com"
    # storage_path 镜像主机工厂注入的内容 (runtime_home / base_dir)
    dm = DeerMem(backend_config={"storage_path": str(deermem_data_dir)})
    dm.create_fact("User prefers concise answers", category="preference", user_id=user_id)

    expected_safe = make_safe_user_id(user_id)
    expected_file = deermem_data_dir / "users" / expected_safe / "memory.json"
    assert expected_file.is_file(), f"memory not at expected per-user path: {expected_file}"
    # DeerMem 使用与主机相同的 safe_user_id （不是其他编码）。
    user_dirs = [p.name for p in (deermem_data_dir / "users").iterdir() if p.is_dir()]
    assert user_dirs == [expected_safe], f"safe_user_id diverged from host: {user_dirs}"


def test_trim_facts_to_max_coerces_non_float_confidence():
    '验证 trim、facts、to、max、coerces、non、float、confidence 场景下的预期行为、边界条件与结果。\n\nNon-float stored confidence must not crash the max_facts trim sort.\n\n    Regression: the vendored copy used ``key=lambda f: f.get("confidence", 0)``\n    which raised TypeError comparing None/str against float once ``len > max_facts``\n    (legacy / imported facts with abnormal confidence). This is the #4034 intent\n    that the module-skipped test files never exercised against the vendored\n    updater; pinning it here so the rename can\'t silently drop the coercion again.\n    '
    facts = [
        {"id": "a", "confidence": None},
        {"id": "b", "confidence": "0.9"},  # numeric string
        {"id": "c", "confidence": 0.8},
        {"id": "d", "confidence": "high"},  # non-numeric
    ]
    # 无类型错误；强制排名：b("0.9"->0.9) > c(0.8) > a(无->0.5)=d("high"->0.5)。
    kept = _trim_facts_to_max(facts, max_facts=2)
    assert [f["id"] for f in kept] == ["b", "c"]
    # 低于上限 -> 返回不变（无排序，无崩溃）。
    assert _trim_facts_to_max(facts, max_facts=10) == facts


def test_create_fact_trims_to_max_and_signals_eviction(deermem_data_dir):
    '验证 create、fact、trims、to、max、and、signals、eviction 场景下的预期行为、边界条件与结果。\n\ncreate_fact enforces max_facts and signals eviction via None fact_id.\n\n    Regression: the vendored ``create_memory_fact`` only appended (no trim), so\n    manual / tool adds could grow memory past max_facts. Now it trims (highest\n    confidence wins) and returns ``None`` when the cap evicts the new fact, so\n    the tool reports "not stored" instead of a dangling id + false "added".\n    '
    # DeerMemConfig 强制 max_facts >= 10，因此用 10 个高可信事实填充上限。
    dm = DeerMem(backend_config={"max_facts": 10, "storage_path": str(deermem_data_dir)})
    for i in range(10):
        _, fid = dm.create_fact(f"high{i}", category="context", confidence=0.9, user_id="u1")
        assert fid is not None

    # 上限已满（10 个事实）；置信度较低的第 11 个将被逐出，而不是存储。
    memory_data, evicted_id = dm.create_fact("low_evicted", category="context", confidence=0.1, user_id="u1")
    assert evicted_id is None
    assert "low_evicted" not in {f["content"] for f in memory_data["facts"]}
    assert len(memory_data["facts"]) == 10


def test_search_survives_non_float_confidence(deermem_data_dir):
    '验证 search、survives、non、float、confidence 场景下的预期行为、边界条件与结果。\n\nDeerMem.search ranks by _coerce_source_confidence, so non-float stored\n    confidence (null / string / non-numeric, reachable via import / legacy) must\n    not crash the sort. Re-adds the regression guard deleted with the monolithic\n    test_search_memory_facts_sort_survives_non_float_stored_confidence.'
    dm = DeerMem(backend_config={"storage_path": str(deermem_data_dir)})
    # create_fact validates confidence to float, so seed non-float via import
    # create_fact 验证浮动的置信度，因此通过导入种子非浮动
    dm.import_memory(
        {
            "user": {},
            "history": {},
            "facts": [
                {"id": "a", "content": "alpha matching query", "confidence": None},
                {"id": "b", "content": "bravo matching query", "confidence": "0.9"},
                {"id": "c", "content": "charlie matching query", "confidence": "high"},
            ],
        },
        user_id="u1",
    )
    results = dm.search("query", top_k=10, user_id="u1")
    # No TypeError; all three match "query"; ranked by coerced confidence desc:
    # 无类型错误；所有三个都匹配“查询”；按强制置信度排序：
    assert [r["id"] for r in results] == ["b", "a", "c"]


def test_is_human_clarification_response_matches_host_read():
    "验证 is、human、clarification、response、matches、host、read 场景下的预期行为、边界条件与结果。\n\nThe standalone mirror must agree with the host's read_human_input_response\n    so hidden-message filtering doesn't diverge between production (host hook) and\n    standalone / test (mirror default). Pins drift (#5)."

    from deerflow.agents.human_input import read_human_input_response
    from deerflow.agents.memory.backends.deermem.deermem.core.message_processing import _is_human_clarification_response

    def payload(**overrides):
        '执行 payload 的明确职责，并返回与调用约定一致的结果'
        base = {"version": 1, "kind": "human_input_response", "source": "s", "request_id": "r", "value": "v", "response_kind": "text"}
        base.update(overrides)
        return {"human_input_response": base}

    cases = [
        {},
        {"human_input_response": {}},
        payload(),  # valid text response
        payload(response_kind="option", option_id="o1"),  # valid option response
        payload(response_kind="option"),  # option without option_id -> not valid
        payload(value=""),  # empty value -> not valid
        payload(source=""),  # empty source -> not valid
        payload(version=2),  # wrong version -> not valid
        payload(kind="other"),  # wrong kind -> not valid
        {"human_input_response": "not a mapping"},
        {"other_key": 1},  # no human_input_response key
    ]
    for ak in cases:
        host_keeps = read_human_input_response(ak) is not None
        mirror_keeps = _is_human_clarification_response(ak)
        assert host_keeps == mirror_keeps, f"divergence on {ak!r}: host={host_keeps} mirror={mirror_keeps}"


def test_build_llm_returns_none_when_no_model_configured():
    '验证 build、llm、returns、none、when、no、model、configured 场景下的预期行为、边界条件与结果。\n\nZero-config (no model_config, or model_config with no model) -> None.\n    Non-LLM ops still work; an update raises at runtime.'
    from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemModelConfig
    from deerflow.agents.memory.backends.deermem.deermem.core.llm import build_llm

    assert build_llm(None) is None
    assert build_llm(DeerMemModelConfig()) is None  # model=None default


def test_build_llm_degrades_to_none_on_init_failure(caplog):
    '验证 build、llm、degrades、to、none、on、init、failure 场景下的预期行为、边界条件与结果。\n\nbuild_llm degrades to None (with a WARNING) when init_chat_model fails,\n    mirroring _host_default_llm -- so a misconfigured explicit ``model`` does\n    NOT crash app startup. Memory CRUD/read/search still work; extraction is\n    disabled; an update raises at runtime with the underlying error logged.'
    from unittest.mock import patch

    from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemModelConfig
    from deerflow.agents.memory.backends.deermem.deermem.core.llm import build_llm

    model_config = DeerMemModelConfig(provider="openai", model="bogus-model", api_key="k")
    llm_logger = "deerflow.agents.memory.backends.deermem.deermem.core.llm"

    with patch("langchain.chat_models.init_chat_model", side_effect=RuntimeError("boom")):
        with caplog.at_level("WARNING", logger=llm_logger):
            result = build_llm(model_config)

    assert result is None
    assert any("build_llm failed" in r.message for r in caplog.records)


def test_from_backend_config_warns_on_unknown_keys(caplog):
    "验证 from、backend、config、warns、on、unknown、keys 场景下的预期行为、边界条件与结果。\n\nUnknown backend_config keys log a WARNING so a typo (e.g. ``storage_pat``\n    missing the ``h``) does not silently fall back to the default and write\n    memory to an unintended location. Mirrors the host layer's\n    load_memory_config_from_dict warning."
    from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig

    cfg_logger = "deerflow.agents.memory.backends.deermem.deermem.config"
    with caplog.at_level("WARNING", logger=cfg_logger):
        cfg = DeerMemConfig.from_backend_config({"storage_path": "/tmp/x", "storage_pat": "/tmp/y"})

    # 已解析已知密钥；未知键被忽略但警告
    assert cfg.storage_path == "/tmp/x"
    assert any("Unknown backend_config keys" in r.message for r in caplog.records)
    assert any("storage_pat" in r.message for r in caplog.records)


def test_from_backend_config_silent_on_known_keys(caplog):
    '验证 from、backend、config、silent、on、known、keys 场景下的预期行为、边界条件与结果。\n\nNo warning when every key is known (regression guard for the typo warning).'
    from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig

    cfg_logger = "deerflow.agents.memory.backends.deermem.deermem.config"
    with caplog.at_level("WARNING", logger=cfg_logger):
        DeerMemConfig.from_backend_config({"storage_path": "/tmp/x", "max_facts": 20})
    assert not any("Unknown backend_config keys" in r.message for r in caplog.records)


def test_from_backend_config_null_values_fall_back_to_defaults():
    '验证 from、backend、config、null、values、fall、back、to、defaults 场景下的预期行为、边界条件与结果。\n\nExplicit YAML ``null`` values must behave like omitted keys, not crash.\n\n    ``config.example.yaml`` ships ``backend_config.model:`` as a bare key with\n    commented children, which YAML parses to ``None`` (and ``make\n    config-upgrade`` writes it out as an explicit ``model: null``). Non-Optional\n    fields like ``model: DeerMemModelConfig`` reject an explicit ``None`` even\n    though the omitted key would use the field default — so the shipped example\n    config crashed every run with a DeerMemConfig ValidationError.'
    from deerflow.agents.memory.backends.deermem.deermem.config import (
        DeerMemConfig,
        DeerMemModelConfig,
    )

    cfg = DeerMemConfig.from_backend_config({"model": None, "debounce_seconds": None, "storage_path": "/tmp/x"})

    # 没有条目回退到字段默认值；实际值仍然解析
    assert isinstance(cfg.model, DeerMemModelConfig)
    assert cfg.model.model is None  # default = no extraction LLM configured
    assert cfg.debounce_seconds == DeerMemConfig().debounce_seconds
    assert cfg.storage_path == "/tmp/x"


def test_from_backend_config_null_values_do_not_warn_as_unknown(caplog):
    '验证 from、backend、config、null、values、do、not、warn、as、unknown 场景下的预期行为、边界条件与结果。\n\nDropped ``None`` entries are known keys — they must not trip the\n    unknown-key typo warning.'
    from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig

    cfg_logger = "deerflow.agents.memory.backends.deermem.deermem.config"
    with caplog.at_level("WARNING", logger=cfg_logger):
        DeerMemConfig.from_backend_config({"model": None})
    assert not any("Unknown backend_config keys" in r.message for r in caplog.records)
