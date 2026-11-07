'''管理网页发起的微信扫码登录，并仅向二维码创建者公开登录进度。'''

from __future__ import annotations

import asyncio
import base64
import logging
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from io import BytesIO
from typing import Any

import qrcode
from qrcode.image.svg import SvgPathImage

from server.channels.message_bus import MessageBus
from server.channels.providers.wechat import WechatChannel

logger = logging.getLogger(__name__)


@dataclass
class _LoginSession:
    '''保存一次限时扫码的所有者、适配器和后台任务，认证凭据不进入接口响应。'''

    owner: str
    login_id: str
    channel: WechatChannel
    expires_at: int
    task: asyncio.Task | None = None
    status: str = "starting"
    error: str | None = None
    qr_content: str | None = None
    qr_image: str | None = None


class WechatLoginFlow:
    '''在全局机器人配置范围内串行处理扫码，避免多个管理员互相覆盖登录。'''

    def __init__(self) -> None:
        '''初始化单个登录会话及保护登录提交与取消操作的异步锁。'''
        self._session: _LoginSession | None = None
        self._lock = asyncio.Lock()

    async def start(self, owner: str, save_credentials: Callable[[dict[str, Any]], Awaitable[None]]) -> dict[str, Any]:
        '''开始或刷新当前管理员的二维码，其他管理员的进行中会话不会被替换。'''
        async with self._lock:
            previous = self._session
            if previous and previous.task and not previous.task.done():
                if previous.owner != owner:
                    raise PermissionError("另一位管理员正在连接微信，请稍后再试。")
                previous.task.cancel()
                await asyncio.gather(previous.task, return_exceptions=True)
            channel = WechatChannel(bus=MessageBus(), config={})
            session = _LoginSession(owner, secrets.token_urlsafe(24), channel, int(time.time()) + 180)
            self._session = session
            session.task = asyncio.create_task(self._run(session, save_credentials))
            return self.snapshot(owner, session.login_id)

    async def _run(self, session: _LoginSession, save_credentials: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        '''等待微信确认并提交凭据，失败时保留可展示状态，结束后关闭临时网络客户端。'''
        try:
            auth = await asyncio.wait_for(session.channel.login_with_qrcode(), timeout=195)
            if not auth.get("bot_token"):
                raise ValueError("微信确认结果缺少机器人令牌")
            # 提交期间持锁，让断开操作发生在提交之后，防止迟到的登录任务重新连接。
            async with self._lock:
                await save_credentials(auth)
                session.status = "confirmed"
        except asyncio.CancelledError:
            session.status = "canceled"
            raise
        except (TimeoutError, asyncio.TimeoutError):
            session.status = "expired"
            session.error = "二维码已过期，请刷新后重新扫码。"
        except Exception as exc:
            status = session.channel.get_qrcode_login_status()["status"]
            session.status = "expired" if status in {"expired", "timeout", "invalid"} else "failed"
            session.error = "微信登录未完成，请刷新二维码重试；若持续失败，请检查网络及微信接入权限。"
            logger.warning("微信扫码或通道启动失败（%s），请检查网络和通道日志", type(exc).__name__)
        finally:
            await session.channel.stop()

    def snapshot(self, owner: str, login_id: str) -> dict[str, Any]:
        '''返回当前所有者的脱敏状态，并在本机生成二维码图像。'''
        session = self._session
        if session is None or session.owner != owner or session.login_id != login_id:
            raise KeyError("登录会话不存在")
        public = session.channel.get_qrcode_login_status()
        status = session.status
        if status == "starting":
            # 微信确认后还需要保存凭据和启动通道，提交完成前不向页面报告成功。
            status = public["status"] if public["status"] in {"pending", "scanned"} else "starting"
        content = public.get("qrcode_content")
        if status in {"pending", "scanned"} and isinstance(content, str) and content != session.qr_content:
            output = BytesIO()
            qrcode.make(content, image_factory=SvgPathImage, box_size=6, border=4).save(output)
            session.qr_content = content
            session.qr_image = "data:image/svg+xml;base64," + base64.b64encode(output.getvalue()).decode("ascii")
        return {
            "login_id": session.login_id,
            "status": status,
            "qr_image": session.qr_image if status in {"pending", "scanned"} else None,
            "expires_at": session.expires_at,
            "error": session.error,
        }

    async def cancel(self, owner: str, login_id: str) -> None:
        '''取消指定所有者未完成的扫码；已保存成功的微信连接保持运行。'''
        self.snapshot(owner, login_id)
        async with self._lock:
            session = self._session
            if session and session.login_id == login_id and session.owner == owner and session.task and not session.task.done():
                session.task.cancel()
                await asyncio.gather(session.task, return_exceptions=True)
                if session.status != "confirmed":
                    session.status = "canceled"

    async def close(self) -> None:
        '''在应用退出或主动断开通道时回收尚未完成的登录任务。'''
        async with self._lock:
            session = self._session
            if session and session.task and not session.task.done():
                session.task.cancel()
                await asyncio.gather(session.task, return_exceptions=True)
                if session.status != "confirmed":
                    session.status = "canceled"
