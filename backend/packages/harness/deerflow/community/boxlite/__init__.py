'定义 __init__ 模块提供的职责与可复用接口。\n\nBoxLite micro-VM backend for DeerFlow sandboxes.\n\nIntegrates `BoxLite <https://github.com/boxlite-ai/boxlite>`_ — a daemonless,\nOCI-native micro-VM runtime (libkrun/KVM on Linux, Hypervisor.framework on\nmacOS) — behind DeerFlow\'s :class:`Sandbox` / :class:`SandboxProvider` contract.\nEach sandbox is a hardware-isolated VM with its own kernel that runs any OCI\nimage unchanged. See https://github.com/bytedance/deer-flow/issues/3936.\n\nThe full contract is implemented: ``execute_command`` plus ``read_file`` /\n``write_file`` / ``update_file`` / ``download_file`` / ``list_dir`` / ``glob`` /\n``grep`` (file ops run as shell commands inside the box).\n\nConfiguration example (``config.yaml``)::\n\n    sandbox:\n      use: deerflow.community.boxlite:BoxliteProvider\n      image: python:3.12-slim      # any OCI image; runs unchanged\n      memory_mib: 1024             # per-box memory cap (optional)\n      cpus: 2                      # per-box vCPUs (optional)\n      replicas: 3                  # active + warm VM cap per gateway process\n      idle_timeout: 600            # warm VM idle seconds before stop; 0 disables\n      environment:                 # injected into every command\n        PYTHONUNBUFFERED: "1"\n\nInstall the optional runtime before selecting this provider::\n\n    pip install "deerflow-harness[boxlite]"\n\nHost requirement: BoxLite boots micro-VMs, so a Linux host needs KVM (nested\nvirtualization when DeerFlow itself runs inside a cloud VM); macOS uses\nHypervisor.framework.\n'

from .box import BoxliteBox
from .provider import BoxliteProvider

__all__ = [
    "BoxliteBox",
    "BoxliteProvider",
]
