'''生成图像：选择 Gemini 或 MiniMax，处理参考图 MIME 编码并写入指定输出路径。'''

import base64
import json
import os

import requests

MINIMAX_DEFAULT_HOST = "https://api.minimaxi.com"
# MiniMax image-01 的提示词上限为 1500 字符；超限仅返回笼统的参数错误，因此在调用前检查。
MINIMAX_PROMPT_MAX_CHARS = 1500


def validate_image(image_path: str) -> bool:
    '''使用 Pillow 双重打开并校验参考图像。

    首次打开只验证文件完整性，第二次加载确认像素可读；路径不存在、格式不支持或
    图像损坏时记录警告并返回 ``False``，以便 Gemini 分支跳过该参考图而不中断批处理。
    '''
    from PIL import Image

    try:
        with Image.open(image_path) as image:
            image.verify()
        with Image.open(image_path) as image:
            image.load()
        return True
    except Exception as exc:
        print(f"Warning: Image '{image_path}' is invalid or corrupted: {exc}")
        return False


def _resolve_provider(override_env: str, existing_provider: str, has_existing_creds: bool) -> str:
    '''按显式环境变量、既有服务商凭据、MiniMax 凭据的优先级选择服务商。

    环境变量的值会去空格并转为小写；前两种凭据都不可用时仅在存在
    ``MINIMAX_API_KEY`` 时回退 MiniMax，否则抛出说明所需密钥的 ``ValueError``。
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
    '''返回去除尾部斜杠后的 MiniMax API 根地址，允许环境变量覆盖默认端点。'''
    return os.getenv("MINIMAX_API_HOST", MINIMAX_DEFAULT_HOST).rstrip("/")


def _check_base_resp(payload: dict) -> None:
    '''检查 MiniMax ``base_resp`` 协议字段；非零状态转换为包含服务端信息的异常。'''
    base = payload.get("base_resp") or {}
    if base.get("status_code", 0) != 0:
        raise Exception(
            f"MiniMax error {base.get('status_code')}: {base.get('status_msg')}"
        )


def _guess_mime(image_path: str) -> str:
    '''依据扩展名推断数据 URL 的图像 MIME 类型，未知格式以 JPEG 兼容值处理。'''
    ext = os.path.splitext(image_path)[1].lower()
    return {
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
    }.get(ext, "image/jpeg")


def _to_data_url(image_path: str) -> str:
    '''读取本地图像并编码为 MiniMax ``subject_reference`` 所需的 Base64 数据 URL。

    文件读取错误直接向调用方传播；MIME 类型由扩展名推断，不检查图像的实际内容。
    '''
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return f"data:{_guess_mime(image_path)};base64,{b64}"


def _ensure_output_dir(output_file: str) -> None:
    '''创建输出文件的父目录，避免调用方提供嵌套路径时写入失败。'''
    output_dir = os.path.dirname(output_file)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)


def _minimax_prompt(raw: str) -> str:
    '''提取 MiniMax image-01 所需的单段提示词。

    共享提示文件可为含 ``prompt``、``style`` 等字段的 JSON，也可为纯文本；仅在
    JSON 的 ``prompt`` 为非空字符串时取该字段，否则保留原文交给服务端优化器。
    '''
    text = raw.strip()
    try:
        data = json.loads(text)
    except (ValueError, json.JSONDecodeError):
        return text
    if isinstance(data, dict):
        core = data.get("prompt")
        if isinstance(core, str) and core.strip():
            return core.strip()
    return text


def _generate_image_minimax(
    prompt: str, reference_images: list[str], output_file: str, aspect_ratio: str
) -> str:
    '''调用 MiniMax 图像接口，并将首张 Base64 结果写入输出路径。

    提示词会提取 JSON 中的 ``prompt`` 字段并受 image-01 字符上限约束；参考图以
    推断 MIME 的数据 URL 作为角色主体提交。缺少密钥或提示词过长返回状态字符串，
    HTTP 失败、``base_resp`` 错误、空结果和文件写入错误均向调用方传播。
    '''
    api_key = os.getenv("MINIMAX_API_KEY")
    if not api_key:
        return "MINIMAX_API_KEY is not set"
    prompt = _minimax_prompt(prompt)
    if len(prompt) > MINIMAX_PROMPT_MAX_CHARS:
        return (
            f"Prompt is {len(prompt)} characters but MiniMax image-01 accepts at most "
            f"{MINIMAX_PROMPT_MAX_CHARS}. Shorten the prompt to stay within the limit; "
            f"reference images plus a tighter description usually recover the detail."
        )
    body = {
        "model": os.getenv("MINIMAX_IMAGE_MODEL", "image-01"),
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "response_format": "base64",
        "n": 1,
        "prompt_optimizer": True,
    }
    if reference_images:
        # MiniMax 将参考图直接作为角色主体提交；不预校验，非法文件由其 API 返回具体错误。
        body["subject_reference"] = [
            {"type": "character", "image_file": _to_data_url(p)} for p in reference_images
        ]
    response = requests.post(
        f"{_minimax_host()}/v1/image_generation",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=body,
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    _check_base_resp(payload)
    images = (payload.get("data") or {}).get("image_base64") or []
    if not images:
        raise Exception("MiniMax returned no image data")
    _ensure_output_dir(output_file)
    with open(output_file, "wb") as f:
        f.write(base64.b64decode(images[0]))
    return f"Successfully generated image to {output_file}"


def _generate_image_gemini(
    prompt: str, reference_images: list[str], output_file: str, aspect_ratio: str
) -> str:
    '''调用 Gemini 图像接口，跳过损坏的参考图并把唯一返回图像写入输出路径。

    有效参考图一律以 JPEG MIME 内嵌；缺少 Gemini 密钥时返回状态字符串。HTTP 错误、
    响应结构异常、不是恰好一张内嵌图像以及解码或写入错误均向调用方传播。
    '''
    parts = []
    valid_reference_images = []
    for ref_img in reference_images:
        if validate_image(ref_img):
            valid_reference_images.append(ref_img)
        else:
            print(f"Skipping invalid reference image: {ref_img}")
    if len(valid_reference_images) < len(reference_images):
        skipped = len(reference_images) - len(valid_reference_images)
        print(f"Note: {skipped} reference image(s) were skipped due to validation failure.")

    for reference_image in valid_reference_images:
        with open(reference_image, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("utf-8")
        parts.append({"inlineData": {"mimeType": "image/jpeg", "data": image_b64}})

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return "GEMINI_API_KEY is not set"
    response = requests.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-3-pro-image-preview:generateContent",
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
        json={
            "generationConfig": {"imageConfig": {"aspectRatio": aspect_ratio}},
            "contents": [{"parts": [*parts, {"text": prompt}]}],
        },
    )
    response.raise_for_status()
    data = response.json()
    response_parts: list[dict] = data["candidates"][0]["content"]["parts"]
    image_parts = [part for part in response_parts if part.get("inlineData", False)]
    if len(image_parts) == 1:
        base64_image = image_parts[0]["inlineData"]["data"]
        _ensure_output_dir(output_file)
        with open(output_file, "wb") as f:
            f.write(base64.b64decode(base64_image))
        return f"Successfully generated image to {output_file}"
    raise Exception("Failed to generate image")


def generate_image(
    prompt_file: str,
    reference_images: list[str],
    output_file: str,
    aspect_ratio: str = "16:9",
) -> str:
    '''读取 UTF-8 提示文件，选择图像服务商并将生成结果写入 ``output_file``。

    仅接受 ``gemini``、``google`` 和 ``minimax``；画幅参数传给两个服务商，参考图由
    各自分支编码。提示文件读取、未知服务商及下游 API 或文件系统异常均不在此吞没。
    '''
    with open(prompt_file, "r", encoding="utf-8") as f:
        prompt = f.read()
    provider = _resolve_provider(
        "IMAGE_GENERATION_PROVIDER", "gemini", bool(os.getenv("GEMINI_API_KEY"))
    )
    if provider == "minimax":
        return _generate_image_minimax(prompt, reference_images, output_file, aspect_ratio)
    if provider in ("gemini", "google"):
        return _generate_image_gemini(prompt, reference_images, output_file, aspect_ratio)
    raise ValueError(f"Unknown image provider: {provider!r} (use 'gemini' or 'minimax')")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate images using Gemini or MiniMax API")
    parser.add_argument("--prompt-file", required=True, help="Absolute path to JSON prompt file")
    parser.add_argument("--reference-images", nargs="*", default=[],
                        help="Absolute paths to reference images (space-separated)")
    parser.add_argument("--output-file", required=True, help="Output path for generated image")
    parser.add_argument("--aspect-ratio", required=False, default="16:9",
                        help="Aspect ratio of the generated image")
    args = parser.parse_args()

    try:
        print(generate_image(args.prompt_file, args.reference_images,
                             args.output_file, args.aspect_ratio))
    except Exception as e:
        print(f"Error while generating image: {e}")
