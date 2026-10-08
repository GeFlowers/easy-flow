'''提供 BoxLite 微型虚拟机沙箱及其创建和管理实现。

通过 `BoxLite <https://github.com/boxlite-ai/boxlite>`_ 实现 DeerFlow 的
:class:`Sandbox` / :class:`SandboxProvider` 接口。BoxLite 无需守护进程，
可原生运行容器镜像；在 Linux 上使用 libkrun/KVM，在 macOS 上使用
Hypervisor.framework。每个沙箱均为硬件隔离的虚拟机，拥有独立内核，
可直接运行容器镜像，无需修改。参见 https://github.com/bytedance/deer-flow/issues/3936。

完整实现了 ``execute_command`` 以及 ``read_file`` / ``write_file`` /
``update_file`` / ``download_file`` / ``list_dir`` / ``glob`` / ``grep``；
文件操作通过虚拟机内的命令执行。

配置示例（``config.yaml``）::

    sandbox:
      use: deerflow.community.boxlite:BoxliteProvider
      image: python:3.12-slim      # 可直接运行任意容器镜像
      memory_mib: 1024             # 每个虚拟机的内存上限，可选
      cpus: 2                      # 每个虚拟机的虚拟处理器数，可选
      replicas: 3                  # 每个网关进程中活动和预热虚拟机的总数上限
      idle_timeout: 600            # 预热虚拟机关闭前的空闲秒数；0 表示禁用
      environment:                 # 注入每条命令的环境变量
        PYTHONUNBUFFERED: "1"

选择此提供方前，请先安装可选运行时::

    pip install "deer-flow[boxlite]"

宿主机要求：BoxLite 会启动微型虚拟机，因此 Linux 宿主机需要内核虚拟化支持；
DeerFlow 自身运行于云虚拟机时需要启用嵌套虚拟化。macOS 使用 Hypervisor.framework。
'''

from .box import BoxliteBox
from .provider import BoxliteProvider

__all__ = [
    "BoxliteBox",
    "BoxliteProvider",
]
