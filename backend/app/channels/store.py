'''持久化外部即时通讯会话到 DeerFlow 线程的映射。'''

from __future__ import annotations

import json
import logging
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ChannelStore:
    '''使用 JSON 文件维护即时通讯会话与 DeerFlow 线程之间的映射。

    磁盘数据结构如下::

        {
            "<channel_name>:<chat_id>": {
                "thread_id": "<uuid>",
                "user_id": "<platform_user>",
                "created_at": 1700000000.0,
                "updated_at": 1700000000.0
            },
            ...
        }

    每次修改都会原子重写单个文件，适合本地与低并发部署；高并发生产环境应替换为
    具备事务和跨进程并发控制的数据库实现。
    '''

    def __init__(self, path: str | Path | None = None) -> None:
        '''解析默认存储位置并加载已有映射。'''
        if path is None:
            from deerflow.config.paths import get_paths

            path = Path(get_paths().base_dir) / "channels" / "store.json"
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, dict[str, Any]] = self._load()
        self._lock = threading.Lock()

    # -- 持久化 ------------------------------------------------------------

    def _load(self) -> dict[str, dict[str, Any]]:
        '''读取映射文件，文件缺失或损坏时返回空映射。'''
        if self._path.exists():
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                logger.warning("Corrupt channel store at %s, starting fresh", self._path)
        return {}

    def _save(self) -> None:
        '''通过同目录临时文件替换目标文件，避免写入中断留下半份 JSON。'''
        fd = tempfile.NamedTemporaryFile(
            mode="w",
            dir=self._path.parent,
            suffix=".tmp",
            delete=False,
        )
        try:
            json.dump(self._data, fd, indent=2)
            fd.close()
            Path(fd.name).replace(self._path)
        except BaseException:
            fd.close()
            Path(fd.name).unlink(missing_ok=True)
            raise

    # -- 映射键 ------------------------------------------------------------

    @staticmethod
    def _key(channel_name: str, chat_id: str, topic_id: str | None = None) -> str:
        '''构造平台、会话及可选话题共同限定的稳定映射键。'''
        if topic_id:
            return f"{channel_name}:{chat_id}:{topic_id}"
        return f"{channel_name}:{chat_id}"

    # -- 公共接口 ----------------------------------------------------------

    def get_thread_id(self, channel_name: str, chat_id: str, topic_id: str | None = None) -> str | None:
        '''查询指定平台会话或话题所映射的 DeerFlow ``thread_id``。'''
        entry = self._data.get(self._key(channel_name, chat_id, topic_id))
        return entry["thread_id"] if entry else None

    def set_thread_id(
        self,
        channel_name: str,
        chat_id: str,
        thread_id: str,
        *,
        topic_id: str | None = None,
        user_id: str = "",
    ) -> None:
        '''创建或更新会话映射，并保留首次创建时间。'''
        with self._lock:
            key = self._key(channel_name, chat_id, topic_id)
            now = time.time()
            existing = self._data.get(key)
            self._data[key] = {
                "thread_id": thread_id,
                "user_id": user_id,
                "created_at": existing["created_at"] if existing else now,
                "updated_at": now,
            }
            self._save()

    def remove(self, channel_name: str, chat_id: str, topic_id: str | None = None) -> bool:
        '''删除指定映射，返回是否存在实际删除。

        提供 ``topic_id`` 时只删除该话题；省略时删除会话基础键及其全部话题键，
        用于彻底断开一个平台会话与 DeerFlow 历史的关联。
        '''
        with self._lock:
            # 显式 topic_id 代表精确删除，不能连带清理同一会话的其他话题。
            if topic_id is not None:
                key = self._key(channel_name, chat_id, topic_id)
                if key in self._data:
                    del self._data[key]
                    self._save()
                    return True
                return False

            # 未指定话题时同时清理基础映射及其派生话题映射。
            prefix = self._key(channel_name, chat_id)
            keys_to_delete = [k for k in self._data if k == prefix or k.startswith(prefix + ":")]
            if not keys_to_delete:
                return False

            for k in keys_to_delete:
                del self._data[k]
            self._save()
            return True

    def list_entries(self, channel_name: str | None = None) -> list[dict[str, Any]]:
        '''列出映射，并可按通道筛选，同时把复合键还原为结构化字段。'''
        results = []
        for key, entry in self._data.items():
            parts = key.split(":", 2)
            ch = parts[0]
            chat = parts[1] if len(parts) > 1 else ""
            topic = parts[2] if len(parts) > 2 else None
            if channel_name and ch != channel_name:
                continue
            item: dict[str, Any] = {"channel_name": ch, "chat_id": chat, **entry}
            if topic is not None:
                item["topic_id"] = topic
            results.append(item)
        return results
