'''管理所有智能体共用的指令文件。'''

import os
import tempfile
import threading

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from deerflow.config.agents_config import AGENTS_FILENAME
from deerflow.config.paths import get_paths


router = APIRouter(prefix="/api", tags=["global-instructions"])
_write_lock = threading.Lock()


class InstructionsContent(BaseModel):
    content: str


class InstructionsUpdate(InstructionsContent):
    original_content: str


def _read_content() -> str:
    path = get_paths().base_dir / AGENTS_FILENAME
    return path.read_text(encoding="utf-8") if path.is_file() else ""


@router.get("/global-instructions", response_model=InstructionsContent)
async def get_global_instructions() -> InstructionsContent:
    return InstructionsContent(content=_read_content())


@router.put("/global-instructions", response_model=InstructionsContent)
async def update_global_instructions(body: InstructionsUpdate) -> InstructionsContent:

    path = get_paths().base_dir / AGENTS_FILENAME
    with _write_lock:
        if _read_content() != body.original_content:
            raise HTTPException(status_code=409, detail="指示已被其他操作修改，请重新加载后再保存。")
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="", dir=path.parent, delete=False) as file:
                temp_path = file.name
                file.write(body.content)
            os.replace(temp_path, path)
        finally:
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)
    return InstructionsContent(content=body.content)
