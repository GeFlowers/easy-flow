"""将幻灯片图片和演示计划合成为 PPTX，并附加可选的演讲者备注。"""

import json
import os
from io import BytesIO

from PIL import Image
from pptx import Presentation
from pptx.util import Inches


def generate_ppt(
    plan_file: str,
    slide_images: list[str],
    output_file: str,
) -> str:
    """根据 JSON 演示计划和有序图片生成 PPTX。

    ``plan_file`` 提供画幅和每页备注，``slide_images`` 必须按页序排列；函数将图片按
    原始比例居中裁切填满页面。图片缺失时返回错误文本，其他文件或库错误交由调用方处理。
    """
    # 读取演示计划。
    with open(plan_file, "r", encoding="utf-8") as f:
        plan = json.load(f)

    # 根据画幅确定页面尺寸。
    aspect_ratio = plan.get("aspect_ratio", "16:9")
    if aspect_ratio == "16:9":
        slide_width = Inches(13.333)
        slide_height = Inches(7.5)
    elif aspect_ratio == "4:3":
        slide_width = Inches(10)
        slide_height = Inches(7.5)
    else:
        # 未知画幅按 16:9 兼容处理。
        slide_width = Inches(13.333)
        slide_height = Inches(7.5)

    # 创建并设置目标尺寸的演示文稿。
    prs = Presentation()
    prs.slide_width = slide_width
    prs.slide_height = slide_height

    # 使用空白版式，以便整页铺放图片。
    blank_layout = prs.slide_layouts[6]  # 空白版式

    # 逐页加入图片。
    slides_info = plan.get("slides", [])

    for i, image_path in enumerate(slide_images):
        if not os.path.exists(image_path):
            return f"Error: Slide image not found: {image_path}"

        # 新建空白页。
        slide = prs.slides.add_slide(blank_layout)

        # 读取并处理图片。
        with Image.open(image_path) as img:
            # 含透明通道的 PNG 等格式先转换为 RGB，保证 JPEG 编码可用。
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")

            # 在保持比例的前提下计算覆盖整页的尺寸。
            img_width, img_height = img.size
            img_aspect = img_width / img_height
            slide_aspect = slide_width / slide_height

            # 转成 EMU 进行版式计算。
            slide_width_emu = int(slide_width)
            slide_height_emu = int(slide_height)

            if img_aspect > slide_aspect:
                # 图片更宽：以页面宽度为准并垂直居中。
                new_width_emu = slide_width_emu
                new_height_emu = int(slide_width_emu / img_aspect)
                left = Inches(0)
                top = Inches((slide_height_emu - new_height_emu) / 914400)
            else:
                # 图片更高：以页面高度为准并水平居中。
                new_height_emu = slide_height_emu
                new_width_emu = int(slide_height_emu * img_aspect)
                left = Inches((slide_width_emu - new_width_emu) / 914400)
                top = Inches(0)

            # 将处理后的图片保存到内存字节流。
            img_bytes = BytesIO()
            img.save(img_bytes, format="JPEG", quality=95)
            img_bytes.seek(0)

            # 将图片加入当前页。
            slide.shapes.add_picture(
                img_bytes, left, top, Inches(new_width_emu / 914400), Inches(new_height_emu / 914400)
            )

        # 若计划提供标题、要点等信息，则写入演讲者备注。
        if i < len(slides_info):
            slide_info = slides_info[i]
            notes = []

            if slide_info.get("title"):
                notes.append(f"Title: {slide_info['title']}")

            if slide_info.get("subtitle"):
                notes.append(f"Subtitle: {slide_info['subtitle']}")

            if slide_info.get("key_points"):
                notes.append("Key Points:")
                for point in slide_info["key_points"]:
                    notes.append(f"  • {point}")

            if notes:
                notes_slide = slide.notes_slide
                text_frame = notes_slide.notes_text_frame
                if text_frame is not None:
                    text_frame.text = "\n".join(notes)

    # 保存最终演示文稿。
    prs.save(output_file)

    return f"Successfully generated presentation with {len(slide_images)} slides to {output_file}"


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate PowerPoint presentation from slide images"
    )
    parser.add_argument(
        "--plan-file",
        required=True,
        help="Absolute path to JSON presentation plan file",
    )
    parser.add_argument(
        "--slide-images",
        nargs="+",
        required=True,
        help="Absolute paths to slide images in order (space-separated)",
    )
    parser.add_argument(
        "--output-file",
        required=True,
        help="Output path for generated PPTX file",
    )

    args = parser.parse_args()

    try:
        print(
            generate_ppt(
                args.plan_file,
                args.slide_images,
                args.output_file,
            )
        )
    except Exception as e:
        print(f"Error while generating presentation: {e}")
