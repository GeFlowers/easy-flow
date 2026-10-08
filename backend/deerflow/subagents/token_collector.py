'''从子代理模型回调中收集令牌用量，并按真实模型记录给主运行账本。'''

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler


class SubagentTokenCollector(BaseCallbackHandler):
    '''保存子代理调用方名称、已计费运行标识和收集到的用量记录。'''

    def __init__(self, caller: str):
        '''初始化回调记录，并保留调用者标签用于区分不同子代理来源。'''
        super().__init__()
        self.caller = caller
        self._records: list[dict[str, int | str | None]] = []
        self._counted_run_ids: set[str] = set()

    def on_llm_end(
        self,
        response: Any,
        *,
        run_id: Any,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        '''读取模型响应中的输入、输出和缓存令牌数，每个模型运行只登记一次。'''
        rid = str(run_id)
        if rid in self._counted_run_ids:
            return

        for generation in response.generations:
            for gen in generation:
                if not hasattr(gen, "message"):
                    continue
                usage = getattr(gen.message, "usage_metadata", None)
                usage_dict = dict(usage) if usage else {}
                input_tk = usage_dict.get("input_tokens", 0) or 0
                output_tk = usage_dict.get("output_tokens", 0) or 0
                total_tk = usage_dict.get("total_tokens", 0) or 0
                if total_tk <= 0:
                    total_tk = input_tk + output_tk
                if total_tk <= 0:
                    continue
                # 缓存命中令牌用于按实际计费口径统计模型成本。
                details = usage_dict.get("input_token_details") or {}
                cache_read_tk = 0
                if isinstance(details, Mapping):
                    try:
                        cache_read_tk = max(int(details.get("cache_read") or 0), 0)
                    except (TypeError, ValueError):
                        cache_read_tk = 0
                # 记录实际生成响应的模型，避免把子代理用量错误计入主代理模型。
                response_metadata = getattr(gen.message, "response_metadata", None) or {}
                model_name: str | None = None
                if isinstance(response_metadata, Mapping):
                    model_name = response_metadata.get("model_name") or response_metadata.get("model")
                self._counted_run_ids.add(rid)
                record: dict[str, int | str | None] = {
                    "source_run_id": rid,
                    "caller": self.caller,
                    "model_name": model_name,
                    "input_tokens": input_tk,
                    "output_tokens": output_tk,
                    "total_tokens": total_tk,
                }
                # 仅在供应商报告缓存命中时写入该字段，与账本的稀疏字段约定一致。
                if cache_read_tk > 0:
                    record["cache_read_tokens"] = cache_read_tk
                self._records.append(record)
                return

    def snapshot_records(self) -> list[dict[str, int | str | None]]:
        '''返回用量记录列表的副本，避免调用方修改回调内部状态。'''
        return list(self._records)
