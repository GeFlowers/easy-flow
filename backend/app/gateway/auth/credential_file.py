'''将初始管理员凭据写入受限文件，避免记录到日志。

明文密钥写入标准输出或标准错误会被生产日志系统收集并扩散。本辅助函数
将凭据写入仅进程用户可读的 0600 文件，并仅返回文件路径供调用方记录。
'''

from __future__ import annotations

import os
from pathlib import Path

from deerflow.config.paths import get_paths

_CREDENTIAL_FILENAME = "admin_initial_credentials.txt"


def write_initial_credentials(email: str, password: str, *, label: str = "initial") -> Path:
    '''将管理员邮箱和密码写入 ``{base_dir}/admin_initial_credentials.txt``。

    文件通过 ``os.open`` 以 0600 权限原子创建，避免写入与改权限之间的窗口
    使密码被其他用户读取。``label`` 在文件头区分初始创建和密码重置事件。

    返回凭据文件的绝对 :class:`Path`。
    '''
    target = get_paths().base_dir / _CREDENTIAL_FILENAME
    target.parent.mkdir(parents=True, exist_ok=True)

    content = (
        f"# DeerFlow admin {label} credentials\n# This file is generated on first boot or password reset.\n# Change the password after login via Settings -> Account,\n# then delete this file.\n#\nemail: {email}\npassword: {password}\n"
    )

    # 以 0600 权限原子创建或截断；采用截断现有文件的方式，
    # 以便重置密码流程可直接改写已有文件，无需先删除再创建。
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(content)

    return target.resolve()
