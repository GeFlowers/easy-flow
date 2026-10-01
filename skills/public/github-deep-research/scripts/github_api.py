#!/usr/bin/env python3
'''深度研究技能使用的代码托管平台接口客户端。

该模块通过 ``requests`` 发起 HTTP 请求；依赖不可用时使用兼容接口的 ``urllib``
回退实现。它只负责读取仓库元数据、文件和统计信息，不承担部署、配置写入或技能扫描。
'''

import os
import json
import sys
from typing import Any, Dict, List, Optional

try:
    import requests
except ImportError:
    # 未安装 requests 时改用标准库 urllib。
    import urllib.error
    import urllib.request

    class RequestsFallback:
        '''使用 ``urllib`` 提供本模块所需的最小 ``requests`` 兼容接口。'''

        class Response:
            '''封装 HTTP 响应字节、状态码和解码后的文本内容。'''

            def __init__(self, data: bytes, status: int):
                '''保存响应字节并预先生成替换非法字符后的 UTF-8 文本。'''
                self._data = data
                self.status_code = status
                self.text = data.decode("utf-8", errors="replace")

            def json(self):
                '''将响应字节解析为 JSON 并返回对应的 Python 对象。'''
                return json.loads(self._data)

            def raise_for_status(self):
                '''在 HTTP 状态码表示失败时抛出异常。'''
                if self.status_code >= 400:
                    raise Exception(f"HTTP {self.status_code}")

        @staticmethod
        def get(url: str, headers: dict = None, params: dict = None, timeout: int = 30):
            '''使用 ``urllib`` 执行 GET 请求，并返回兼容的响应包装对象。'''
            if params:
                query = "&".join(f"{k}={v}" for k, v in params.items())
                url = f"{url}?{query}"

            req = urllib.request.Request(url, headers=headers or {})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return RequestsFallback.Response(resp.read(), resp.status)
            except urllib.error.HTTPError as e:
                return RequestsFallback.Response(e.read(), e.code)

    requests = RequestsFallback()


class GitHubAPI:
    '''供仓库研究使用的只读代码托管平台 REST 接口客户端。'''

    BASE_URL = "https://api.github.com"

    def __init__(self, token: Optional[str] = None):
        '''初始化请求头，并可选地加入用于提高限额的个人访问令牌。

        令牌可由调用方从环境配置传入；本客户端不会读取、保存或修改部署配置。
        '''
        self.headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Deep-Research-Bot/1.0",
        }
        if token:
            self.headers["Authorization"] = f"token {token}"

    def _get(
        self, endpoint: str, params: Optional[Dict] = None, accept: Optional[str] = None
    ) -> Any:
        '''向指定接口端点发送 GET 请求，并按 ``accept`` 返回文本或 JSON。'''
        url = f"{self.BASE_URL}{endpoint}"
        headers = self.headers.copy()
        if accept:
            headers["Accept"] = accept

        resp = requests.get(url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()

        if "application/vnd.github.raw" in (accept or ""):
            return resp.text
        return resp.json()

    def get_repo_info(self, owner: str, repo: str) -> Dict:
        '''获取仓库的基础元数据。'''
        return self._get(f"/repos/{owner}/{repo}")

    def get_readme(self, owner: str, repo: str) -> str:
        '''获取仓库 README 的原始 Markdown；不存在时返回说明文本。'''
        try:
            return self._get(
                f"/repos/{owner}/{repo}/readme", accept="application/vnd.github.raw"
            )
        except Exception as e:
            return f"[README not found: {e}]"

    def get_tree(
        self, owner: str, repo: str, branch: str = "main", recursive: bool = True
    ) -> Dict:
        '''获取指定分支的目录树，必要时从 ``main`` 回退到 ``master``。'''
        params = {"recursive": "1"} if recursive else {}
        try:
            return self._get(f"/repos/{owner}/{repo}/git/trees/{branch}", params)
        except Exception:
            # main 分支读取失败时，再尝试 master 分支。
            if branch == "main":
                return self._get(f"/repos/{owner}/{repo}/git/trees/master", params)
            raise

    def get_file_content(self, owner: str, repo: str, path: str) -> str:
        '''获取指定仓库文件的原始内容；未找到时返回说明文本。'''
        try:
            return self._get(
                f"/repos/{owner}/{repo}/contents/{path}",
                accept="application/vnd.github.raw",
            )
        except Exception as e:
            return f"[File not found: {e}]"

    def get_languages(self, owner: str, repo: str) -> Dict[str, int]:
        '''获取仓库语言及各语言对应的代码字节数。'''
        return self._get(f"/repos/{owner}/{repo}/languages")

    def get_contributors(self, owner: str, repo: str, limit: int = 30) -> List[Dict]:
        '''获取贡献者列表，并将单页数量限制在 API 上限以内。'''
        return self._get(
            f"/repos/{owner}/{repo}/contributors", params={"per_page": min(limit, 100)}
        )

    def get_recent_commits(
        self, owner: str, repo: str, limit: int = 50, since: Optional[str] = None
    ) -> List[Dict]:
        '''获取近期提交，可按 ISO 日期筛选并限制返回数量。'''
        params = {"per_page": min(limit, 100)}
        if since:
            params["since"] = since
        return self._get(f"/repos/{owner}/{repo}/commits", params)

    def get_issues(
        self,
        owner: str,
        repo: str,
        state: str = "all",
        limit: int = 30,
        labels: Optional[str] = None,
    ) -> List[Dict]:
        '''按状态和逗号分隔的标签筛选仓库议题。'''
        params = {"state": state, "per_page": min(limit, 100)}
        if labels:
            params["labels"] = labels
        return self._get(f"/repos/{owner}/{repo}/issues", params)

    def get_pull_requests(
        self, owner: str, repo: str, state: str = "all", limit: int = 30
    ) -> List[Dict]:
        '''获取仓库拉取请求列表。'''
        return self._get(
            f"/repos/{owner}/{repo}/pulls",
            params={"state": state, "per_page": min(limit, 100)},
        )

    def get_releases(self, owner: str, repo: str, limit: int = 10) -> List[Dict]:
        '''获取仓库发布版本列表。'''
        return self._get(
            f"/repos/{owner}/{repo}/releases", params={"per_page": min(limit, 100)}
        )

    def get_tags(self, owner: str, repo: str, limit: int = 20) -> List[Dict]:
        '''获取仓库标签列表。'''
        return self._get(
            f"/repos/{owner}/{repo}/tags", params={"per_page": min(limit, 100)}
        )

    def search_issues(self, owner: str, repo: str, query: str, limit: int = 30) -> Dict:
        '''在仓库内搜索议题和拉取请求。'''
        q = f"repo:{owner}/{repo} {query}"
        return self._get("/search/issues", params={"q": q, "per_page": min(limit, 100)})

    def get_commit_activity(self, owner: str, repo: str) -> List[Dict]:
        '''获取最近一年的按周提交活跃度。'''
        return self._get(f"/repos/{owner}/{repo}/stats/commit_activity")

    def get_code_frequency(self, owner: str, repo: str) -> List[List[int]]:
        '''获取按周统计的代码新增和删除数量。'''
        return self._get(f"/repos/{owner}/{repo}/stats/code_frequency")

    def format_tree(self, tree_data: Dict, max_depth: int = 3) -> str:
        '''将目录树响应格式化为不超过指定深度的文本结构。'''
        if "tree" not in tree_data:
            return "[Unable to parse tree]"

        lines = []
        for item in tree_data["tree"]:
            path = item["path"]
            depth = path.count("/")
            if depth < max_depth:
                indent = "  " * depth
                name = path.split("/")[-1]
                if item["type"] == "tree":
                    lines.append(f"{indent}{name}/")
                else:
                    lines.append(f"{indent}{name}")

        return "\n".join(lines[:100])

    def summarize_repo(self, owner: str, repo: str) -> Dict:
        '''汇总仓库信息、语言、贡献者、活动、议题和最新发布版本。'''
        info = self.get_repo_info(owner, repo)

        summary = {
            "name": info.get("full_name"),
            "description": info.get("description"),
            "url": info.get("html_url"),
            "stars": info.get("stargazers_count"),
            "forks": info.get("forks_count"),
            "open_issues": info.get("open_issues_count"),
            "language": info.get("language"),
            "license": info.get("license", {}).get("spdx_id")
            if info.get("license")
            else None,
            "created_at": info.get("created_at"),
            "updated_at": info.get("updated_at"),
            "pushed_at": info.get("pushed_at"),
            "default_branch": info.get("default_branch"),
            "topics": info.get("topics", []),
        }

        # 添加仓库使用的编程语言信息。
        try:
            summary["languages"] = self.get_languages(owner, repo)
        except Exception:
            summary["languages"] = {}

        # 添加贡献者数量。
        try:
            contributors = self.get_contributors(owner, repo, limit=1)
            # GitHub 会通过 Link 响应头提供总数，此处使用近似值。
            summary["contributor_count"] = len(
                self.get_contributors(owner, repo, limit=100)
            )
        except Exception:
            summary["contributor_count"] = "N/A"

        # 添加最近一次发布信息。
        try:
            releases = self.get_releases(owner, repo, limit=1)
            if releases:
                summary["latest_release"] = {
                    "tag": releases[0].get("tag_name"),
                    "name": releases[0].get("name"),
                    "date": releases[0].get("published_at"),
                }
        except Exception:
            summary["latest_release"] = None

        return summary


def main():
    '''提供用于手动验证仓库读取功能的命令行入口。'''
    if len(sys.argv) < 3:
        print("Usage: python github_api.py <owner> <repo> [command]")
        print("Commands: info, readme, tree, languages, contributors,")
        print("          commits, issues, prs, releases, summary")
        sys.exit(1)

    owner, repo = sys.argv[1], sys.argv[2]
    command = sys.argv[3] if len(sys.argv) > 3 else "summary"

    token = os.getenv("GITHUB_TOKEN")
    api = GitHubAPI(token=token)

    commands = {
        "info": lambda: api.get_repo_info(owner, repo),
        "readme": lambda: api.get_readme(owner, repo),
        "tree": lambda: api.format_tree(api.get_tree(owner, repo)),
        "languages": lambda: api.get_languages(owner, repo),
        "contributors": lambda: api.get_contributors(owner, repo),
        "commits": lambda: api.get_recent_commits(owner, repo),
        "issues": lambda: api.get_issues(owner, repo),
        "prs": lambda: api.get_pull_requests(owner, repo),
        "releases": lambda: api.get_releases(owner, repo),
        "summary": lambda: api.summarize_repo(owner, repo),
    }

    if command not in commands:
        print(f"Unknown command: {command}")
        sys.exit(1)

    try:
        result = commands[command]()
        if isinstance(result, str):
            print(result)
        else:
            print(json.dumps(result, indent=2, default=str))
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
