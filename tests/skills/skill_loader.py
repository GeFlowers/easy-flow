"""提供公共技能生成脚本的动态加载器和 HTTP 响应测试替身。"""
import importlib.util
import sys
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[2]


def load(skill_name: str):
    """按技能名称动态加载对应的生成脚本模块。"""
    path = REPO_ROOT / "skills" / "public" / skill_name / "scripts" / "generate.py"
    mod_name = skill_name.replace("-", "_") + "_generate"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module  # 提前注册模块，确保脚本执行时可以解析自身模块名。
    spec.loader.exec_module(module)
    return module


class FakeResp:
    """模拟 requests.Response 的测试替身。"""

    def __init__(self, json_data=None, content=b"", status_code=200):
        """初始化 JSON 数据、二进制响应体和 HTTP 状态码。"""
        self._json = json_data if json_data is not None else {}
        self.content = content
        self.status_code = status_code

    def raise_for_status(self):
        """在状态码表示请求失败时抛出 HTTPError。"""
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        """返回预设的 JSON 响应数据。"""
        return self._json
