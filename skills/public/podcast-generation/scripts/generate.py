'''生成播客：选择火山引擎或 MiniMax TTS、重试合成、合并音频并可写出 Markdown 逐字稿。

服务商由显式环境变量、完整火山引擎凭据和 MiniMax 凭据依次决定。每行文本在服务商
控制的线程池中合成，瞬时请求错误会退避重试；任何一行失败即停止输出完整播客，以避免
产生不完整文件。音频和逐字稿的父目录会按需创建，文件、JSON、网络与响应格式错误会
在相应边界返回 ``None``、记录日志或向调用方抛出。
'''

import argparse
import base64
import json
import logging
import os
import random
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Literal, Optional

import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MINIMAX_DEFAULT_HOST = "https://api.minimaxi.com"
# 遇到 MiniMax 的这些 base_resp 状态码时可重试：未知错误、超时、每分钟请求数限制、每分钟令牌数限制。
MINIMAX_RETRYABLE_CODES = {1000, 1001, 1002, 1039}
DEFAULT_TTS_MAX_RETRIES = 4
DEFAULT_MAX_WORKERS = 4
DEFAULT_MINIMAX_MAX_WORKERS = 1


class ScriptLine:
    '''表示一段待合成的播客台词，保存说话人性别标记和原始段落文本。'''

    def __init__(self, speaker: Literal["male", "female"] = "male", paragraph: str = ""):
        '''以默认男性说话人和空段落创建台词对象，不验证调用方传入的字段值。'''
        self.speaker = speaker
        self.paragraph = paragraph


class Script:
    '''表示播客脚本，包含语言标记和按原始顺序排列的台词列表。'''

    def __init__(self, locale: Literal["en", "zh"] = "en", lines: Optional[list[ScriptLine]] = None):
        '''创建脚本；未传入台词列表时使用新的空列表，避免共享可变默认值。'''
        self.locale = locale
        self.lines = lines or []

    @classmethod
    def from_dict(cls, data: dict) -> "Script":
        '''从 JSON 反序列化字典构造脚本，缺失字段回退为英文、男性和空段落。

        本方法不校验字段类型或可选值，畸形结构产生的访问错误将向调用方传播。
        '''
        script = cls(locale=data.get("locale", "en"))
        for line in data.get("lines", []):
            script.lines.append(
                ScriptLine(speaker=line.get("speaker", "male"),
                           paragraph=line.get("paragraph", ""))
            )
        return script


def _resolve_provider(override_env: str, existing_provider: str, has_existing_creds: bool) -> str:
    '''按显式环境变量、既有服务商凭据、MiniMax 凭据的优先级选择 TTS 服务商。

    环境变量值会去空格并转小写；无可用凭据时抛出说明火山引擎和 MiniMax 凭据要求的
    ``ValueError``，不在此处校验服务商名称是否合法。
    '''
    override = os.getenv(override_env)
    if override:
        return override.strip().lower()
    if has_existing_creds:
        return existing_provider
    if os.getenv("MINIMAX_API_KEY"):
        return "minimax"
    raise ValueError(
        f"No credentials found. Set VOLCENGINE_TTS_APPID + VOLCENGINE_TTS_ACCESS_TOKEN "
        f"for {existing_provider}, or MINIMAX_API_KEY for minimax "
        f"(optionally force with {override_env})."
    )


def _resolve_tts_provider() -> str:
    '''解析播客 TTS 服务商，并只允许 ``volcengine`` 或 ``minimax``。

    火山引擎必须同时具备应用 ID 与访问令牌才算可用；未知服务商抛出 ``ValueError``。
    '''
    has_volc = bool(
        os.getenv("VOLCENGINE_TTS_APPID") and os.getenv("VOLCENGINE_TTS_ACCESS_TOKEN")
    )
    provider = _resolve_provider("PODCAST_GENERATION_PROVIDER", "volcengine", has_volc)
    if provider not in ("volcengine", "minimax"):
        raise ValueError(
            f"Unknown podcast provider: {provider!r} (use 'volcengine' or 'minimax')"
        )
    return provider


def _default_max_retries() -> int:
    '''读取 MiniMax TTS 最大重试次数；环境变量不是整数时回退默认值。'''
    try:
        return int(os.getenv("MINIMAX_TTS_MAX_RETRIES", str(DEFAULT_TTS_MAX_RETRIES)))
    except ValueError:
        return DEFAULT_TTS_MAX_RETRIES


def _default_max_workers(provider: str) -> int:
    '''返回服务商拥有的并发数：MiniMax 保持较低以避免限流，火山引擎使用既有默认值。

    并发数刻意不提供给调用方配置；未识别的服务商也按火山引擎默认值处理。
    '''
    if provider == "minimax":
        return DEFAULT_MINIMAX_MAX_WORKERS
    return DEFAULT_MAX_WORKERS


def _parse_retry_after(response) -> Optional[float]:
    '''解析响应头中的 ``Retry-After`` 秒数；缺失或不可转换时返回 ``None``。'''
    headers = getattr(response, "headers", None) or {}
    value = headers.get("Retry-After")
    try:
        return float(value) if value else None
    except (TypeError, ValueError):
        return None


def _backoff_sleep(attempt: int, retry_after: Optional[float]) -> None:
    '''按服务端 ``Retry-After`` 或指数退避加随机抖动后休眠。

    随机抖动使同时被限流的并发工作线程错开重试，避免形成惊群式重试风暴。
    '''
    base = retry_after if retry_after else min(2 ** attempt, 30)
    time.sleep(base + random.uniform(0, 1))


def text_to_speech_volcengine(
    text: str, voice_type: str, max_retries: Optional[int] = None
) -> Optional[bytes]:
    '''调用火山引擎 TTS 将文本转换为 Base64 解码后的 MP3 字节。

    对网络异常及 HTTP 429/5xx 按指数退避重试，尊重 ``Retry-After``；其他 HTTP、业务
    协议、空音频或耗尽重试均记录日志并返回 ``None``，不向并行工作线程抛出请求异常。
    '''
    app_id = os.getenv("VOLCENGINE_TTS_APPID")
    access_token = os.getenv("VOLCENGINE_TTS_ACCESS_TOKEN")
    cluster = os.getenv("VOLCENGINE_TTS_CLUSTER", "volcano_tts")
    if max_retries is None:
        max_retries = _default_max_retries()
    url = "https://openspeech.bytedance.com/api/v1/tts"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer;{access_token}"}
    payload = {
        "app": {"appid": app_id, "token": "access_token", "cluster": cluster},
        "user": {"uid": "podcast-generator"},
        "audio": {"voice_type": voice_type, "encoding": "mp3", "speed_ratio": 1.2},
        "request": {"reqid": str(uuid.uuid4()), "text": text,
                    "text_type": "plain", "operation": "query"},
    }
    for attempt in range(max_retries + 1):
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=60)
        except Exception as e:
            logger.error(f"TTS error: {e}")
            if attempt < max_retries:
                _backoff_sleep(attempt, None)
                continue
            return None
        if response.status_code == 429 or response.status_code >= 500:
            logger.warning(
                f"Volcengine TTS transient HTTP {response.status_code} "
                f"(attempt {attempt + 1}/{max_retries + 1})"
            )
            if attempt < max_retries:
                _backoff_sleep(attempt, _parse_retry_after(response))
                continue
            return None
        if response.status_code != 200:
            logger.error(f"TTS API error: {response.status_code} - {response.text}")
            return None
        result = response.json()
        if result.get("code") != 3000:
            logger.error(f"TTS error: {result.get('message')} (code: {result.get('code')})")
            return None
        audio_data = result.get("data")
        if audio_data:
            return base64.b64decode(audio_data)
        return None
    return None


def text_to_speech_minimax(
    text: str, voice_id: str, max_retries: Optional[int] = None
) -> Optional[bytes]:
    '''调用 MiniMax ``t2a_v2`` 将文本转换为十六进制解码后的 MP3 字节。

    对网络异常、HTTP 429/5xx 和可重试 ``base_resp``（限流、超时）进行指数退避重试；
    鉴权、余额和输入等永久错误不重试。业务失败、空音频或耗尽重试记录日志并返回
    ``None``，而环境变量缺失不会在本函数预先校验。
    '''
    api_key = os.getenv("MINIMAX_API_KEY")
    host = os.getenv("MINIMAX_API_HOST", MINIMAX_DEFAULT_HOST).rstrip("/")
    if max_retries is None:
        max_retries = _default_max_retries()
    payload = {
        "model": os.getenv("MINIMAX_TTS_MODEL", "speech-2.6-hd"),
        "text": text,
        "voice_setting": {"voice_id": voice_id, "speed": 1.0, "vol": 1.0, "pitch": 0},
        "audio_setting": {"sample_rate": 32000, "bitrate": 128000, "format": "mp3", "channel": 1},
        "output_format": "hex",
    }
    for attempt in range(max_retries + 1):
        try:
            response = requests.post(
                f"{host}/v1/t2a_v2",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=60,
            )
        except Exception as e:
            logger.error(f"MiniMax TTS error: {e}")
            if attempt < max_retries:
                _backoff_sleep(attempt, None)
                continue
            return None
        if response.status_code == 429 or response.status_code >= 500:
            logger.warning(
                f"MiniMax TTS rate-limited HTTP {response.status_code} "
                f"(attempt {attempt + 1}/{max_retries + 1})"
            )
            if attempt < max_retries:
                _backoff_sleep(attempt, _parse_retry_after(response))
                continue
            return None
        if response.status_code != 200:
            logger.error(f"MiniMax TTS error: {response.status_code} - {response.text}")
            return None
        result = response.json()
        base = result.get("base_resp") or {}
        code = base.get("status_code", 0)
        if code in MINIMAX_RETRYABLE_CODES:
            logger.warning(
                f"MiniMax TTS retryable error {code}: {base.get('status_msg')} "
                f"(attempt {attempt + 1}/{max_retries + 1})"
            )
            if attempt < max_retries:
                _backoff_sleep(attempt, None)
                continue
            return None
        if code != 0:
            logger.error(f"MiniMax TTS error {code}: {base.get('status_msg')}")
            return None
        audio_hex = (result.get("data") or {}).get("audio")
        if audio_hex:
            return bytes.fromhex(audio_hex)
        return None
    return None


def _process_line(args: tuple[int, ScriptLine, int, str]) -> tuple[int, Optional[bytes]]:
    '''按服务商与说话人选择音色，合成单行台词并返回 ``(索引, 音频字节或 None)``。

    MiniMax 音色可由环境变量覆盖，火山引擎使用固定男女音色；合成失败仅记录警告，
    由上层统一判定是否中止整个播客。
    '''
    i, line, total, provider = args
    logger.info(f"Processing line {i + 1}/{total} ({line.speaker}) via {provider}")
    if provider == "minimax":
        if line.speaker == "male":
            voice = os.getenv("MINIMAX_TTS_VOICE_MALE", "male-qn-qingse")
        else:
            voice = os.getenv("MINIMAX_TTS_VOICE_FEMALE", "female-tianmei")
        audio = text_to_speech_minimax(line.paragraph, voice)
    else:
        if line.speaker == "male":
            voice = "zh_male_yangguangqingnian_moon_bigtts"
        else:
            voice = "zh_female_sajiaonvyou_moon_bigtts"
        audio = text_to_speech_volcengine(line.paragraph, voice)
    if not audio:
        logger.warning(f"Failed to generate audio for line {i + 1}")
    return (i, audio)


def tts_node(script: Script) -> list[bytes]:
    '''在服务商控制的线程池中将脚本台词合成为保持原始顺序的音频片段。

    MiniMax 低并发、火山引擎既有默认并发，调用方不能覆盖；空脚本、缺失所选凭据或
    任一行在重试后仍合成失败时抛出 ``ValueError``，绝不静默产出不完整播客。
    '''
    total = len(script.lines)
    if total == 0:
        raise ValueError("Script contains no lines to process")

    provider = _resolve_tts_provider()
    max_workers = _default_max_workers(provider)
    if provider == "volcengine" and not (
        os.getenv("VOLCENGINE_TTS_APPID") and os.getenv("VOLCENGINE_TTS_ACCESS_TOKEN")
    ):
        raise ValueError(
            "Volcengine TTS selected but VOLCENGINE_TTS_APPID / "
            "VOLCENGINE_TTS_ACCESS_TOKEN are not set"
        )
    if provider == "minimax" and not os.getenv("MINIMAX_API_KEY"):
        raise ValueError("MiniMax TTS selected but MINIMAX_API_KEY is not set")
    logger.info(f"Converting script to audio using {max_workers} workers (provider={provider})...")
    tasks = [(i, line, total, provider) for i, line in enumerate(script.lines)]

    results: dict[int, Optional[bytes]] = {}
    failed_indices: list[int] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_process_line, task): task[0] for task in tasks}
        for future in as_completed(futures):
            idx, audio = future.result()
            results[idx] = audio
            if not audio:
                failed_indices.append(idx)

    if failed_indices:
        raise ValueError(
            f"TTS failed for {len(failed_indices)}/{total} lines after retries: "
            f"line numbers {sorted(i + 1 for i in failed_indices)}. "
            f"This is usually transient API rate limiting — wait a moment and retry."
        )

    audio_chunks = [results[i] for i in range(total)]
    logger.info(f"Generated {len(audio_chunks)}/{total} audio chunks successfully")
    return audio_chunks


def mix_audio(audio_chunks: list[bytes]) -> bytes:
    '''按顺序拼接 MP3 音频片段并返回字节串，不做重编码或格式混音。

    空列表或拼接后为空时抛出 ``ValueError``，以避免将无效输出写入播客路径。
    '''
    if not audio_chunks:
        raise ValueError("No audio chunks to mix - TTS generation may have failed")
    output = b"".join(audio_chunks)
    if len(output) == 0:
        raise ValueError("Mixed audio is empty - TTS generation may have failed")
    logger.info(f"Audio mixing complete: {len(output)} bytes")
    return output


def generate_markdown(script: Script, title: str = "Podcast Script") -> str:
    '''将脚本按说话人名称渲染为 Markdown 逐字稿，并保留台词顺序和段落分隔。'''
    lines = [f"# {title}", ""]
    for line in script.lines:
        speaker_name = "**Host (Male)**" if line.speaker == "male" else "**Host (Female)**"
        lines.append(f"{speaker_name}: {line.paragraph}")
        lines.append("")
    return "\n".join(lines)


def generate_podcast(script_file: str, output_file: str,
                     transcript_file: Optional[str] = None) -> str:
    '''从 UTF-8 JSON 脚本生成播客 MP3，并可选写入 Markdown 逐字稿。

    脚本必须包含 ``lines``；若请求逐字稿，先创建其父目录并写入，再合成全部台词、拼接
    音频并创建 ``output_file`` 的父目录。JSON、脚本结构、TTS、音频、网络与文件系统
    异常均向调用方传播，只有底层单行 TTS 失败被转换为统一的 ``ValueError``。
    '''
    with open(script_file, "r", encoding="utf-8") as f:
        script_json = json.load(f)
    if "lines" not in script_json:
        raise ValueError(
            f"Invalid script format: missing 'lines' key. Got keys: {list(script_json.keys())}"
        )
    script = Script.from_dict(script_json)
    logger.info(f"Loaded script with {len(script.lines)} lines")

    if transcript_file:
        title = script_json.get("title", "Podcast Script")
        markdown_content = generate_markdown(script, title)
        transcript_dir = os.path.dirname(transcript_file)
        if transcript_dir:
            os.makedirs(transcript_dir, exist_ok=True)
        with open(transcript_file, "w", encoding="utf-8") as f:
            f.write(markdown_content)
        logger.info(f"Generated transcript to {transcript_file}")

    audio_chunks = tts_node(script)
    if not audio_chunks:
        raise Exception("Failed to generate any audio")
    output_audio = mix_audio(audio_chunks)

    output_dir = os.path.dirname(output_file)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    with open(output_file, "wb") as f:
        f.write(output_audio)

    result = f"Successfully generated podcast to {output_file}"
    if transcript_file:
        result += f" and transcript to {transcript_file}"
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate podcast from script JSON file")
    parser.add_argument("--script-file", required=True, help="Absolute path to script JSON file")
    parser.add_argument("--output-file", required=True, help="Output path for generated podcast MP3")
    parser.add_argument("--transcript-file", required=False,
                        help="Output path for transcript markdown file (optional)")
    args = parser.parse_args()

    try:
        result = generate_podcast(args.script_file, args.output_file,
                                  args.transcript_file)
        print(result)
    except Exception as e:
        import traceback
        print(f"Error generating podcast: {e}")
        traceback.print_exc()
