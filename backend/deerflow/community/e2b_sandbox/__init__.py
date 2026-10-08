'''提供基于 E2B 云沙箱的 DeerFlow 沙箱实现。

本包在 `e2b` / `e2b_code_interpreter` 云沙箱客户端之上实现 DeerFlow 的
:class:`Sandbox` / :class:`SandboxProvider` 接口。

配置示例（``config.yaml``）::

    sandbox:
      use: deerflow.community.e2b_sandbox:E2BSandboxProvider
      api_key: $E2B_API_KEY            # 未配置时读取 E2B_API_KEY 环境变量
      template: code-interpreter-v1     # 模板标识，默认使用 e2b 代码解释器模板
      domain: e2b.dev                  # 可选服务域名，例如自托管服务
      idle_timeout: 600                # 传给 e2b 的 ``set_timeout``，单位为秒
      replicas: 3                      # 并发沙箱上限，超限时按最近最少使用原则淘汰
      mounts:                          # 启动时一次性上传宿主机文件到沙箱
        - host_path: /path/on/host
          container_path: /path/in/sandbox
          read_only: false
      environment:                      # 创建时作为 e2b 的 ``envs`` 传入
        OPENAI_API_KEY: $OPENAI_API_KEY
'''

from .e2b_sandbox import E2BSandbox
from .e2b_sandbox_provider import E2BSandboxProvider

__all__ = [
    "E2BSandbox",
    "E2BSandboxProvider",
]
