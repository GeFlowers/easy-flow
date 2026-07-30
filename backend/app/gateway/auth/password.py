"""使用版本化格式处理密码哈希。

格式为 ``$dfv<N>$<bcrypt_hash>``。旧版 v1 直接对密码使用 bcrypt，存在
72 字节静默截断问题；当前 v2 先进行 SHA-256 和 Base64 处理，以确保完整
密码参与哈希。验证会自动识别版本，并将无前缀的旧哈希按 v1 兼容处理。
"""

import asyncio
import base64
import hashlib

import bcrypt

_CURRENT_VERSION = 2
_PREFIX_V2 = "$dfv2$"
_PREFIX_V1 = "$dfv1$"


def _pre_hash_v2(password: str) -> bytes:
    """对密码预先计算 SHA-256 哈希，以绕过 bcrypt 的 72 字节限制。"""
    return base64.b64encode(hashlib.sha256(password.encode("utf-8")).digest())


def hash_password(password: str) -> str:
    """以当前 v2 格式（SHA-256 加 bcrypt）计算密码哈希。"""
    raw = bcrypt.hashpw(_pre_hash_v2(password), bcrypt.gensalt()).decode("utf-8")
    return f"{_PREFIX_V2}{raw}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码，并自动识别哈希版本及兼容无前缀的旧 bcrypt 哈希。"""
    try:
        if hashed_password.startswith(_PREFIX_V2):
            bcrypt_hash = hashed_password[len(_PREFIX_V2) :]
            return bcrypt.checkpw(_pre_hash_v2(plain_password), bcrypt_hash.encode("utf-8"))

        if hashed_password.startswith(_PREFIX_V1):
            bcrypt_hash = hashed_password[len(_PREFIX_V1) :]
        else:
            bcrypt_hash = hashed_password

        return bcrypt.checkpw(plain_password.encode("utf-8"), bcrypt_hash.encode("utf-8"))
    except ValueError:
        # 密码库会为格式错误或损坏的哈希（如无效盐值）抛出异常。
        # 此处按失败关闭处理，不能让请求因异常崩溃。
        return False


def needs_rehash(hashed_password: str) -> bool:
    """当哈希使用旧版本并应在登录后升级时返回 ``True``。"""
    return not hashed_password.startswith(_PREFIX_V2)


async def hash_password_async(password: str) -> str:
    """在线程中执行 bcrypt 密码哈希，避免阻塞异步事件循环。"""
    return await asyncio.to_thread(hash_password, password)


async def verify_password_async(plain_password: str, hashed_password: str) -> bool:
    """在线程中验证密码哈希，避免阻塞异步事件循环。"""
    return await asyncio.to_thread(verify_password, plain_password, hashed_password)
