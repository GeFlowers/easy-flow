'未说明'
import importlib.util
import sys
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[2]


def load(skill_name: str):
    """处理加载相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
    path = REPO_ROOT / "skills" / "public" / skill_name / "scripts" / "generate.py"
    mod_name = skill_name.replace("-", "_") + "_generate"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module  # standard pattern; lets the module resolve itself
    spec.loader.exec_module(module)
    return module


class FakeResp:
    '未说明'

    def __init__(self, json_data=None, content=b"", status_code=200):
        '未说明'
        self._json = json_data if json_data is not None else {}
        self.content = content
        self.status_code = status_code

    def raise_for_status(self):
        '未说明'
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        """处理JSON相关的测试辅助逻辑，保持输入输出可预测且不引入生产副作用。"""
        return self._json
