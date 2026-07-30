'定义 __init__ 模块提供的职责与可复用接口。\n\nE2B cloud sandbox provider for DeerFlow.\n\nThis package implements DeerFlow\'s :class:`Sandbox` / :class:`SandboxProvider`\ncontract on top of the `e2b` / `e2b_code_interpreter` cloud sandbox SDK.\n\nConfiguration example (``config.yaml``)::\n\n    sandbox:\n      use: deerflow.community.e2b_sandbox:E2BSandboxProvider\n      # E2B specific options (read via SandboxConfig\'s ``extra="allow"``):\n      api_key: $E2B_API_KEY            # falls back to E2B_API_KEY env var\n      template: code-interpreter-v1     # e2b template id; defaults to e2b code-interpreter\n      domain: e2b.dev                  # optional e2b domain (e.g. self-hosted)\n      idle_timeout: 600                # forwarded to e2b ``set_timeout`` (seconds)\n      replicas: 3                      # max concurrent sandboxes (LRU eviction beyond)\n      mounts:                          # one-shot upload of host files into the sandbox\n        - host_path: /path/on/host\n          container_path: /path/in/sandbox\n          read_only: false\n      environment:                      # forwarded as e2b ``envs`` on create\n        OPENAI_API_KEY: $OPENAI_API_KEY\n'

from .e2b_sandbox import E2BSandbox
from .e2b_sandbox_provider import E2BSandboxProvider

__all__ = [
    "E2BSandbox",
    "E2BSandboxProvider",
]
