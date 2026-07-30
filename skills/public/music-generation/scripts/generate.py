"""生成音乐：调用 MiniMax 音乐接口，将十六进制 MP3 数据写入指定输出路径。

提示 JSON 决定歌词、纯音乐或歌词优化模式；请求与 ``base_resp`` 错误、空音频、无效
十六进制数据和写入错误均向调用方传播。仅缺少 MiniMax 密钥时返回可读状态字符串。
"""

import argparse
import json
import os

import requests

MINIMAX_DEFAULT_HOST = "https://api.minimaxi.com"


def _check_base_resp(payload: dict) -> None:
    """校验 MiniMax ``base_resp`` 是否表示成功，非零状态时抛出含服务端信息的异常。"""
    base = payload.get("base_resp") or {}
    if base.get("status_code", 0) != 0:
        raise Exception(f"MiniMax error {base.get('status_code')}: {base.get('status_msg')}")


def generate_music(prompt_file: str, output_file: str) -> str:
    """通过 MiniMax ``/v1/music_generation`` 依据 JSON 规格生成 MP3。

    从 UTF-8 JSON 读取 ``prompt``，并按 ``lyrics``、``is_instrumental`` 的优先级设置
    请求：有歌词直接提交，否则纯音乐，最后使用歌词优化。成功响应的十六进制音频会在
    创建输出父目录后写入 ``output_file``；格式、API、解码和文件系统错误均向调用方传播。
    """
    with open(prompt_file, "r", encoding="utf-8") as f:
        spec = json.load(f)

    api_key = os.getenv("MINIMAX_API_KEY")
    if not api_key:
        return "MINIMAX_API_KEY is not set"

    prompt = (spec.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("`prompt` is required in the music spec")
    lyrics = spec.get("lyrics") or None  # treat empty string the same as absent
    is_instrumental = bool(spec.get("is_instrumental", False))

    body = {
        "model": os.getenv("MINIMAX_MUSIC_MODEL", "music-2.6-free"),
        "prompt": prompt,
        "output_format": "hex",
        "audio_setting": {"sample_rate": 44100, "bitrate": 256000, "format": "mp3"},
    }
    if lyrics:
        body["lyrics"] = lyrics
    elif is_instrumental:
        body["is_instrumental"] = True
    else:
        body["lyrics_optimizer"] = True

    host = os.getenv("MINIMAX_API_HOST", MINIMAX_DEFAULT_HOST).rstrip("/")
    response = requests.post(
        f"{host}/v1/music_generation",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=body,
        timeout=300,
    )
    response.raise_for_status()
    payload = response.json()
    _check_base_resp(payload)
    audio_hex = (payload.get("data") or {}).get("audio")
    if not audio_hex:
        raise Exception("MiniMax returned no audio data")

    output_dir = os.path.dirname(output_file)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    with open(output_file, "wb") as f:
        f.write(bytes.fromhex(audio_hex))
    return f"Successfully generated music to {output_file}"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate music using MiniMax API")
    parser.add_argument("--prompt-file", required=True,
                        help="Absolute path to JSON spec file {title, prompt, lyrics?, is_instrumental?}")
    parser.add_argument("--output-file", required=True, help="Output path for generated MP3")
    args = parser.parse_args()

    try:
        print(generate_music(args.prompt_file, args.output_file))
    except Exception as e:
        print(f"Error while generating music: {e}")
