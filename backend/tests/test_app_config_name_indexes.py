"""覆盖本模块的可回归测试，固定关键输入、失败分支与资源生命周期，避免后续改动破坏既有契约。"""

from deerflow.config.app_config import AppConfig


def _build(model_names=(), tool_names=(), group_names=()):
    """为“构建”测试场景提供受控辅助行为，精确限定模拟返回、异常传播或资源状态。"""
    return AppConfig.model_validate(
        {
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
            "models": [{"name": n, "use": "pkg:Cls", "model": n} for n in model_names],
            "tools": [{"name": n, "group": "default", "use": "pkg:fn"} for n in tool_names],
            "tool_groups": [{"name": n} for n in group_names],
        }
    )


def test_get_config_returns_matching_entry():
    """验证“获取配置返回该项条目”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    cfg = _build(model_names=["m1", "m2"], tool_names=["t1", "t2"], group_names=["g1"])
    assert cfg.get_model_config("m2").name == "m2"
    assert cfg.get_tool_config("t1").name == "t1"
    assert cfg.get_tool_group_config("g1").name == "g1"


def test_get_config_returns_none_for_missing():
    """验证“获取配置返回空值该项缺失”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    cfg = _build(model_names=["m1"], tool_names=["t1"], group_names=["g1"])
    assert cfg.get_model_config("nope") is None
    assert cfg.get_tool_config("nope") is None
    assert cfg.get_tool_group_config("nope") is None


def test_get_config_first_match_wins_on_duplicate_names():
    # 两个模型共享一个名称；索引必须返回第一个，匹配
    # 上一个下一个(...) 扫描。
    """验证“获取配置首个匹配该项该项重复该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    cfg = AppConfig.model_validate(
        {
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
            "models": [
                {"name": "dup", "use": "pkg:A", "model": "first"},
                {"name": "dup", "use": "pkg:B", "model": "second"},
            ],
        }
    )
    assert cfg.get_model_config("dup").model == "first"


def test_index_matches_linear_scan_reference():
    """验证“索引该项线性扫描该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    cfg = _build(model_names=["a", "b", "c"], tool_names=["x", "y"], group_names=["g"])
    for n in ["a", "b", "c", "missing"]:
        assert cfg.get_model_config(n) == next((m for m in cfg.models if m.name == n), None)
    for n in ["x", "y", "missing"]:
        assert cfg.get_tool_config(n) == next((t for t in cfg.tools if t.name == n), None)
    for n in ["g", "missing"]:
        assert cfg.get_tool_group_config(n) == next((grp for grp in cfg.tool_groups if grp.name == n), None)


def test_empty_config_lookups_return_none():
    """验证“空值配置该项返回空值”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    cfg = _build()
    assert cfg.get_model_config("anything") is None
    assert cfg.get_tool_config("anything") is None
    assert cfg.get_tool_group_config("anything") is None
