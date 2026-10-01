'''生成视频：选择 Gemini 或 MiniMax，轮询异步任务并下载至指定输出路径。

MiniMax 先取得任务与文件标识再检索临时下载地址；Gemini 轮询长时 operation 并用
Gemini 密钥下载首个样本。HTTP、服务端协议、轮询失败及写入错误向调用方传播，
而缺少所选服务商密钥时返回可读的状态字符串。
'''

import base64
import os
import time

import requests

MINIMAX_DEFAULT_HOST = "https://api.minimaxi.com"


def _resolve_provider(override_env: str, existing_provider: str, has_existing_creds: bool) -> str:
    '''按显式环境变量、既有服务商凭据、MiniMax 凭据的优先级选择视频后端。

    显式值会去空格并转小写；前两种凭据不可用时仅在存在 ``MINIMAX_API_KEY`` 时回退，
    否则抛出说明凭据要求的 ``ValueError``。
    '''
    override = os.getenv(override_env)
    if override:
        return override.strip().lower()
    if has_existing_creds:
        return existing_provider
    if os.getenv("MINIMAX_API_KEY"):
        return "minimax"
    raise ValueError(
        f"No credentials found. Set GEMINI_API_KEY for {existing_provider}, "
        f"or MINIMAX_API_KEY for minimax (optionally force with {override_env})."
    )


def _minimax_host() -> str:
    '''返回规范化的 MiniMax API 根地址，支持通过环境变量切换私有端点。'''
    return os.getenv("MINIMAX_API_HOST", MINIMAX_DEFAULT_HOST).rstrip("/")


def _ensure_output_dir(output_file: str) -> None:
    '''创建输出文件父目录，保证嵌套输出路径可写。'''
    output_dir = os.path.dirname(output_file)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)


def _check_base_resp(payload: dict) -> None:
    '''校验 MiniMax 响应的 ``base_resp``，并把协议错误转换为异常。'''
    base = payload.get("base_resp") or {}
    if base.get("status_code", 0) != 0:
        raise Exception(f"MiniMax error {base.get('status_code')}: {base.get('status_msg')}")


def _guess_mime(image_path: str) -> str:
    '''按参考图扩展名生成数据 URL 的 MIME 类型，未知格式回退 JPEG。'''
    ext = os.path.splitext(image_path)[1].lower()
    return {
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
    }.get(ext, "image/jpeg")


def _to_data_url(image_path: str) -> str:
    '''将本地首帧图像读取并编码为可直接提交给 MiniMax 的 Base64 数据 URL。'''
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return f"data:{_guess_mime(image_path)};base64,{b64}"


def _poll_video_task(host: str, auth: str, task_id: str,
                     max_attempts: int = 120, interval: int = 3) -> str:
    '''按固定间隔轮询 MiniMax 视频任务，直至成功、失败或超过最大次数。

    成功时返回 ``file_id``；任务失败时抛出含任务标识和服务端信息的异常，未达终态但
    ``base_resp`` 出错时立即抛出，耗尽轮询次数后抛出超时异常。
    '''
    for _ in range(max_attempts):
        response = requests.get(
            f"{host}/v1/query/video_generation",
            headers={"Authorization": auth},
            params={"task_id": task_id},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        status = payload.get("status")
        if status == "Success":
            return payload["file_id"]
        if status == "Fail":
            base = payload.get("base_resp") or {}
            raise Exception(
                f"MiniMax video task {task_id} failed: "
                f"{base.get('status_code')} {base.get('status_msg')}"
            )
        # 查询接口可能在未给出终态时返回认证或任务 ID 错误，须先向调用方暴露该错误。
        _check_base_resp(payload)
        time.sleep(interval)
    raise Exception(f"MiniMax video task {task_id} timed out after {max_attempts} polls")


def _retrieve_file_url(host: str, auth: str, file_id: str) -> str:
    '''通过 MiniMax 文件检索接口将文件 ID 解析为临时下载 URL，并校验协议错误。

    HTTP、``base_resp`` 或响应字段缺失错误均向调用方传播。
    '''
    response = requests.get(
        f"{host}/v1/files/retrieve",
        headers={"Authorization": auth},
        params={"file_id": file_id},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    _check_base_resp(payload)
    return payload["file"]["download_url"]


def _download(url: str, output_file: str) -> None:
    '''下载 MiniMax 提供的二进制文件并写入输出路径。

    下载使用无鉴权请求，成功后创建父目录；HTTP 或文件系统错误会向调用方传播。
    '''
    response = requests.get(url, timeout=300)
    response.raise_for_status()
    _ensure_output_dir(output_file)
    with open(output_file, "wb") as f:
        f.write(response.content)


def _generate_video_minimax(
    prompt: str, reference_images: list[str], output_file: str
) -> str:
    '''提交 MiniMax 视频任务、轮询文件 ID、检索下载地址并保存成品视频。

    只使用第一张参考图作为首帧，且按扩展名转换为数据 URL。缺少 MiniMax 密钥时返回
    状态字符串；提交、轮询、检索、下载及写入阶段的异常均向调用方传播。
    '''
    api_key = os.getenv("MINIMAX_API_KEY")
    if not api_key:
        return "MINIMAX_API_KEY is not set"
    host = _minimax_host()
    auth = f"Bearer {api_key}"
    body = {"model": os.getenv("MINIMAX_VIDEO_MODEL", "MiniMax-Hailuo-2.3"), "prompt": prompt}
    if reference_images:
        body["first_frame_image"] = _to_data_url(reference_images[0])
    response = requests.post(
        f"{host}/v1/video_generation",
        headers={"Authorization": auth, "Content-Type": "application/json"},
        json=body,
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    _check_base_resp(payload)
    task_id = payload["task_id"]
    file_id = _poll_video_task(host, auth, task_id)
    download_url = _retrieve_file_url(host, auth, file_id)
    _download(download_url, output_file)
    return f"The video has been generated successfully to {output_file}"


def download(url: str, output_file: str) -> None:
    '''使用 Gemini API 密钥下载生成视频并写入输出路径。

    缺少密钥抛出 ``ValueError``；HTTP 失败、目录创建失败和写入失败均向调用方传播。
    '''
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set")
    response = requests.get(url, headers={"x-goog-api-key": api_key}, timeout=300)
    response.raise_for_status()
    _ensure_output_dir(output_file)
    with open(output_file, "wb") as f:
        f.write(response.content)


def _generate_video_gemini(
    prompt: str, reference_images: list[str], output_file: str
) -> str:
    '''提交 Gemini Veo 长时任务，轮询 operation 完成后下载第一段生成视频。

    所有参考图均以 JPEG MIME 的 Base64 数据提交；轮询没有次数上限且每三秒一次。
    缺少密钥时返回状态字符串，HTTP、响应结构、下载和写入错误均向调用方传播。
    '''
    reference_payload = []
    request_json = {"instances": [{"prompt": prompt}]}
    for reference_image in reference_images:
        with open(reference_image, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("utf-8")
        reference_payload.append(
            {"image": {"mimeType": "image/jpeg", "bytesBase64Encoded": image_b64},
             "referenceType": "asset"}
        )
    if reference_payload:
        request_json["instances"][0]["referenceImages"] = reference_payload
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return "GEMINI_API_KEY is not set"
    response = requests.post(
        "https://generativelanguage.googleapis.com/v1beta/models/veo-3.1-generate-preview:predictLongRunning",
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
        json=request_json,
        timeout=60,
    )
    response.raise_for_status()
    data = response.json()
    operation_name = data["name"]
    while True:
        response = requests.get(
            f"https://generativelanguage.googleapis.com/v1beta/{operation_name}",
            headers={"x-goog-api-key": api_key},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        if data.get("done", False):
            sample = data["response"]["generateVideoResponse"]["generatedSamples"][0]
            download(sample["video"]["uri"], output_file)
            break
        time.sleep(3)
    return f"The video has been generated successfully to {output_file}"


def generate_video(
    prompt_file: str,
    reference_images: list[str],
    output_file: str,
    aspect_ratio: str = "16:9",
) -> str:
    '''读取 UTF-8 提示文件，选择视频服务商并将结果写入 ``output_file``。

    接受 ``gemini``、``google`` 和 ``minimax``；``aspect_ratio`` 为既有接口参数，当前
    两条下游路径都不向请求体写入该值。未知服务商、文件读取和下游异常均向调用方传播。
    '''
    with open(prompt_file, "r", encoding="utf-8") as f:
        prompt = f.read()
    provider = _resolve_provider(
        "VIDEO_GENERATION_PROVIDER", "gemini", bool(os.getenv("GEMINI_API_KEY"))
    )
    if provider == "minimax":
        # MiniMax 以分辨率和时长控制输出，不支持 ``aspect_ratio``，故此参数在该分支无效。
        return _generate_video_minimax(prompt, reference_images, output_file)
    if provider in ("gemini", "google"):
        return _generate_video_gemini(prompt, reference_images, output_file)
    raise ValueError(f"Unknown video provider: {provider!r} (use 'gemini' or 'minimax')")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate videos using Gemini or MiniMax API")
    parser.add_argument("--prompt-file", required=True, help="Absolute path to JSON prompt file")
    parser.add_argument("--reference-images", nargs="*", default=[],
                        help="Absolute paths to reference images (space-separated)")
    parser.add_argument("--output-file", required=True, help="Output path for generated video")
    parser.add_argument("--aspect-ratio", required=False, default="16:9",
                        help="Aspect ratio of the generated video (Gemini only)")
    args = parser.parse_args()

    try:
        print(generate_video(args.prompt_file, args.reference_images,
                             args.output_file, args.aspect_ratio))
    except Exception as e:
        print(f"Error while generating video: {e}")
