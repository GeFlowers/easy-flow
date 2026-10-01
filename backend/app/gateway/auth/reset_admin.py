'''重置管理员密码的命令行工具。

新密码写入权限为 0600 的 ``.deer-flow/admin_initial_credentials.txt``，
而不输出明文，避免 CI 或日志聚合器收集该密钥。
'''

from __future__ import annotations

import argparse
import asyncio
import secrets
import sys

from sqlalchemy import select

from app.gateway.auth.credential_file import write_initial_credentials
from app.gateway.auth.password import hash_password
from app.gateway.auth.repositories.sql import SQLUserRepository
from deerflow.persistence.user.model import UserRow


async def _run(email: str | None) -> int:
    '''执行管理员密码重置，并以进程退出码表示处理结果。'''
    from deerflow.config import get_app_config
    from deerflow.persistence.engine import (
        close_engine,
        get_session_factory,
        init_engine_from_config,
    )

    config = get_app_config()
    await init_engine_from_config(config.database)
    try:
        sf = get_session_factory()
        if sf is None:
            print("Error: persistence engine not available (check config.database).", file=sys.stderr)
            return 1

        repo = SQLUserRepository(sf)

        if email:
            user = await repo.get_user_by_email(email)
        else:
            # 直接查询首个管理员；仓储未提供此专用查询，且不应仅为该命令行工具增加接口。
            async with sf() as session:
                stmt = select(UserRow).where(UserRow.system_role == "admin").limit(1)
                row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                user = None
            else:
                user = await repo.get_user_by_id(row.id)

        if user is None:
            if email:
                print(f"Error: user '{email}' not found.", file=sys.stderr)
            else:
                print("Error: no admin user found.", file=sys.stderr)
            return 1

        new_password = secrets.token_urlsafe(16)
        user.password_hash = hash_password(new_password)
        user.token_version += 1
        user.needs_setup = True
        await repo.update_user(user)

        cred_path = write_initial_credentials(user.email, new_password, label="reset")
        print(f"Password reset for: {user.email}")
        print(f"Credentials written to: {cred_path} (mode 0600)")
        print("Next login will require setup (new email + password).")
        return 0
    finally:
        await close_engine()


def main() -> None:
    '''解析命令行参数、运行异步重置流程并退出。'''
    parser = argparse.ArgumentParser(description="Reset admin password")
    parser.add_argument("--email", help="Admin email (default: first admin found)")
    args = parser.parse_args()

    exit_code = asyncio.run(_run(args.email))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
