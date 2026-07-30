"""\u672c\u6a21\u5757\u8986\u76d6\u76f8\u5173\u6d4b\u8bd5\uff0c\u56fa\u5b9a\u516c\u5f00\u884c\u4e3a\u3001\u5931\u8d25\u5904\u7406\u4e0e\u72b6\u6001\u8fb9\u754c\u3002"""
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECK_SCRIPT_PATH = REPO_ROOT / "scripts" / "check.py"


spec = importlib.util.spec_from_file_location("deerflow_check_script", CHECK_SCRIPT_PATH)
assert spec is not None
assert spec.loader is not None
check_script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_script)


def test_find_pnpm_command_prefers_resolved_executable(monkeypatch):
    """\u9a8c\u8bc1\u5f53\u524d\u573a\u666f\u7684\u540c\u6b65\u8c03\u7528\uff1a\u4f7f\u7528\u53d7\u63a7\u8f93\u5165\u4e0e\u4f9d\u8d56\u66ff\u8eab\uff0c\u901a\u8fc71\u9879\u65ad\u8a00\u56fa\u5b9a\u8fd4\u56de\u3001\u72b6\u6001\u6216\u526f\u4f5c\u7528\u8fb9\u754c\u3002"""
    def fake_which(name: str) -> str | None:
        """\u6a21\u62df\u672c\u7528\u4f8b\u6240\u9700\u7684\u5916\u90e8\u4ea4\u4e92\uff0c\u4e3a\u8c03\u7528\u65b9\u63d0\u4f9b\u53d7\u63a7\u8fd4\u56de\u3001\u5f02\u5e38\u6216\u8c03\u7528\u8bb0\u5f55\u3002"""
        if name == "pnpm":
            return r"C:\Users\tester\AppData\Roaming\npm\pnpm.CMD"
        if name == "pnpm.cmd":
            return r"C:\Users\tester\AppData\Roaming\npm\pnpm.cmd"
        return None

    monkeypatch.setattr(check_script.shutil, "which", fake_which)

    assert check_script.find_pnpm_command() == [r"C:\Users\tester\AppData\Roaming\npm\pnpm.CMD"]


def test_find_pnpm_command_falls_back_to_corepack(monkeypatch):
    """\u9a8c\u8bc1\u5f53\u524d\u573a\u666f\u7684\u540c\u6b65\u8c03\u7528\uff1a\u4f7f\u7528\u53d7\u63a7\u8f93\u5165\u4e0e\u4f9d\u8d56\u66ff\u8eab\uff0c\u901a\u8fc71\u9879\u65ad\u8a00\u56fa\u5b9a\u8fd4\u56de\u3001\u72b6\u6001\u6216\u526f\u4f5c\u7528\u8fb9\u754c\u3002"""
    def fake_which(name: str) -> str | None:
        """\u6a21\u62df\u672c\u7528\u4f8b\u6240\u9700\u7684\u5916\u90e8\u4ea4\u4e92\uff0c\u4e3a\u8c03\u7528\u65b9\u63d0\u4f9b\u53d7\u63a7\u8fd4\u56de\u3001\u5f02\u5e38\u6216\u8c03\u7528\u8bb0\u5f55\u3002"""
        if name == "corepack":
            return r"C:\Program Files\nodejs\corepack.exe"
        return None

    monkeypatch.setattr(check_script.shutil, "which", fake_which)

    assert check_script.find_pnpm_command() == [
        r"C:\Program Files\nodejs\corepack.exe",
        "pnpm",
    ]


def test_find_pnpm_command_falls_back_to_corepack_cmd(monkeypatch):
    """\u9a8c\u8bc1\u5f53\u524d\u573a\u666f\u7684\u540c\u6b65\u8c03\u7528\uff1a\u4f7f\u7528\u53d7\u63a7\u8f93\u5165\u4e0e\u4f9d\u8d56\u66ff\u8eab\uff0c\u901a\u8fc71\u9879\u65ad\u8a00\u56fa\u5b9a\u8fd4\u56de\u3001\u72b6\u6001\u6216\u526f\u4f5c\u7528\u8fb9\u754c\u3002"""
    def fake_which(name: str) -> str | None:
        """\u6a21\u62df\u672c\u7528\u4f8b\u6240\u9700\u7684\u5916\u90e8\u4ea4\u4e92\uff0c\u4e3a\u8c03\u7528\u65b9\u63d0\u4f9b\u53d7\u63a7\u8fd4\u56de\u3001\u5f02\u5e38\u6216\u8c03\u7528\u8bb0\u5f55\u3002"""
        if name == "corepack":
            return None
        if name == "corepack.cmd":
            return r"C:\Program Files\nodejs\corepack.cmd"
        return None

    monkeypatch.setattr(check_script.shutil, "which", fake_which)

    assert check_script.find_pnpm_command() == [
        r"C:\Program Files\nodejs\corepack.cmd",
        "pnpm",
    ]
