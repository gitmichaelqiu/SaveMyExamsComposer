import os
from pathlib import Path
import re
import time
from datetime import datetime
from natsort import natsorted
import pytesseract
from PIL import Image, ImageEnhance, ImageFilter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from PyPDF2 import PdfWriter, PdfReader

# ——— CONFIG ———
EXCLUDE_FILES = {"00_Result.png", "00_Result"}

# Ensure PyPDF2 is installed
try:
    from PyPDF2 import PdfWriter, PdfReader
except ImportError:
    raise ImportError("Please run: pip install PyPDF2")

# ——— UTILS ———
def find_you_answered_y(img: Image.Image, lang="eng") -> int | None:
    gray = img.convert("L")
    enhancer = ImageEnhance.Contrast(gray)
    enhanced = enhancer.enhance(2.0)
    thresh = enhanced.point(lambda p: p > 128 and 255)

    config = r'--oem 3 --psm 6 -c tessedit_char_whitelist=abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ .,'
    data = pytesseract.image_to_data(thresh, output_type=pytesseract.Output.DICT, lang=lang, config=config)

    target_phrase = "You answered"
    for i in range(len(data["text"])):
        text = data["text"][i].strip()
        if not text:
            continue
        if target_phrase.lower() in text.lower():
            y_orig = int(data["top"][i] * (img.height / thresh.height))
            print(f"  🟢 OCR matched '{text}' @ y={y_orig}")
            return y_orig

    for i in range(len(data["text"])):
        text = data["text"][i].strip()
        if not text:
            continue
        if "You" in text or "answered" in text:
            y_orig = int(data["top"][i] * (img.height / thresh.height))
            print(f"  🟢 Fuzzy matched '{text}' @ y={y_orig}")
            return y_orig

    return None


def natural_sort_key(name: str):
    stem = Path(name).stem
    match = re.match(r"(\d+)(?:_([a-zA-Z]))?", stem)
    if not match:
        return (float('inf'), '')
    num = int(match.group(1))
    suffix = match.group(2) or ''
    return (num, suffix)


def create_title_page(pdf_path: Path, folder_name: str, n_images: int):
    """生成带标题的第一页 PDF"""
    c = canvas.Canvas(str(pdf_path), pagesize=A4)
    width, height = A4
    c.setFont("Helvetica-Bold", 24)
    c.drawCentredString(width / 2, height - 150, "Answer Sheet")
    c.setFont("Helvetica", 16)
    c.drawCentredString(width / 2, height - 200, f"Folder: {folder_name}")
    c.drawCentredString(width / 2, height - 230, f"Total Images: {n_images}")
    c.setFont("Helvetica", 12)
    c.setFillColor(colors.gray)
    c.drawCentredString(width / 2, 80, f"Generated at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    c.showPage()
    c.save()


def draw_image_on_canvas(c, img: Image.Image, width_pt, height_pt, MARGIN, CURRENT_Y):
    """✅ 高清版：保持比例 + 高 DPI + 高质量缩放 + 无损保存"""
    # === 高清参数 ===
    TARGET_DPI = 150  # 推荐 150~300；200 平衡清晰度 & 文件大小
    pt_to_inch = 1 / 72.0
    max_width_inch = (width_pt - 2 * MARGIN) * pt_to_inch
    max_height_inch = (height_pt - 2 * MARGIN - 20) * pt_to_inch

    # 计算目标像素尺寸（高 DPI）
    max_width_px = int(max_width_inch * TARGET_DPI)
    max_height_px = int(max_height_inch * TARGET_DPI)

    # 按比例缩放（高质量）
    img_ratio = img.width / img.height
    target_ratio = max_width_px / max_height_px

    if img.width > max_width_px or img.height > max_height_px:
        if img_ratio > target_ratio:
            new_w = max_width_px
            new_h = int(new_w / img_ratio)
        else:
            new_h = max_height_px
            new_w = int(new_h * img_ratio)
        # ✅ 使用 LANCZOS（抗锯齿最佳）
        resized_img = img.resize((new_w, new_h), Image.LANCZOS)
    else:
        resized_img = img.copy()  # 不缩放也 copy 避免影响原图

    # 检查换页
    img_height_pt = resized_img.height / TARGET_DPI * 72  # px → inch → pt
    if CURRENT_Y - img_height_pt < 0:
        c.showPage()
        CURRENT_Y = height_pt - 2 * MARGIN

    # 居中位置（pt）
    img_width_pt = resized_img.width / TARGET_DPI * 72
    x = (width_pt - img_width_pt) / 2
    y = CURRENT_Y - img_height_pt

    # === 关键：高清保存 PNG ===
    temp_png = Path("__temp_draw.png")
    resized_img.save(
        temp_png,
        "PNG",
        dpi=(TARGET_DPI, TARGET_DPI),
        optimize=False,          # 关闭优化（避免压缩）
        compress_level=0,        # 无损压缩
        # pnginfo 可加元数据（可选）
    )

    # ✅ 高清绘制：显式启用 preserveAspectRatio + anchor='c'
    c.drawImage(
        str(temp_png),
        x, y,
        width=img_width_pt,
        height=img_height_pt,
        preserveAspectRatio=True,   # 强制保持比例（双重保险）
        anchor='c'                  # 居中锚点（更稳）
    )
    temp_png.unlink(missing_ok=True)

    return CURRENT_Y - img_height_pt - 10

def process_folder(folder: Path, main_writer: PdfWriter, answer_writer: PdfWriter):
    """处理一个文件夹：生成主 PDF 和答案 PDF，并合并进总 writer"""
    png_files = [
        f for f in folder.glob("*.png")
        if f.is_file() and f.name not in EXCLUDE_FILES
    ]
    if not png_files:
        print(f"⚠️  No PNG in {folder.name}, skipped.")
        return

    png_files.sort(key=lambda f: natural_sort_key(f.name))
    print(f"\n✅ Folder '{folder.name}': {len(png_files)} images")

    # ——— Step 1: 生成标题页 PDF（主 & 答案）———
    title_main_pdf = folder / "__title_main.pdf"
    title_answer_pdf = folder / "__title_answer.pdf"

    # 主标题页
    c = canvas.Canvas(str(title_main_pdf), pagesize=A4)
    width, height = A4
    c.setFont("Helvetica-Bold", 24)
    c.drawCentredString(width / 2, height - 150, "Workout Sheet")
    c.setFont("Helvetica", 16)
    c.drawCentredString(width / 2, height - 200, f"Folder: {folder.name}")
    c.drawCentredString(width / 2, height - 230, f"Total Images: {len(png_files)}")
    c.setFont("Helvetica", 12)
    c.setFillColor(colors.gray)
    c.drawCentredString(width / 2, 80, f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    c.showPage()
    c.save()

    # 答案标题页
    c = canvas.Canvas(str(title_answer_pdf), pagesize=A4)
    c.setFont("Helvetica-Bold", 24)
    c.drawCentredString(width / 2, height - 150, "Answer Key")
    c.setFont("Helvetica", 16)
    c.drawCentredString(width / 2, height - 200, f"Folder: {folder.name}")
    c.drawCentredString(width / 2, height - 230, f"Total Images: {len(png_files)}")
    c.setFont("Helvetica", 12)
    c.setFillColor(colors.gray)
    c.drawCentredString(width / 2, 80, f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    c.showPage()
    c.save()

    # ——— Step 2: 生成图片页 PDF（主 & 答案）———
    img_main_pdf = folder / "__img_main.pdf"
    img_answer_pdf = folder / "__img_answer.pdf"

    # 主图片 PDF（问题部分）
    c = canvas.Canvas(str(img_main_pdf), pagesize=A4)
    width_pt, height_pt = A4
    MARGIN = 20
    CURRENT_Y = height_pt - 2 * MARGIN
    for png_path in png_files:
        try:
            img = Image.open(png_path)
            w, h = img.size
            y_target = find_you_answered_y(img)
            if y_target is None:
                y_target = int(h * 0.45)
            y_target = max(1, min(y_target, h - 1))
            cropped = img.crop((0, 0, w, y_target))
            CURRENT_Y = draw_image_on_canvas(c, cropped, width_pt, height_pt, MARGIN, CURRENT_Y)
        except Exception as e:
            print(f"  ❌ Main image {png_path.name} failed: {e}")
    c.save()

    # 答案图片 PDF
    c = canvas.Canvas(str(img_answer_pdf), pagesize=A4)
    CURRENT_Y = height_pt - 2 * MARGIN
    for png_path in png_files:
        try:
            img = Image.open(png_path)
            w, h = img.size
            y_target = find_you_answered_y(img)
            if y_target is None:
                y_target = int(h * 0.45)
            y_target = max(1, min(y_target, h - 1))
            answer_img = img.crop((0, y_target, w, h))
            if answer_img.height > 5:  # avoid empty crops
                CURRENT_Y = draw_image_on_canvas(c, answer_img, width_pt, height_pt, MARGIN, CURRENT_Y)
        except Exception as e:
            print(f"  ❌ Answer image {png_path.name} failed: {e}")
    c.save()

    # ——— Step 3: 合并 [标题页 + 图片页] → 加入总 writer ———
    for temp_pdf_path, target_writer in [
        (title_main_pdf, main_writer),
        (img_main_pdf, main_writer),
        (title_answer_pdf, answer_writer),
        (img_answer_pdf, answer_writer),
    ]:
        if temp_pdf_path.exists():
            reader = PdfReader(temp_pdf_path)
            for page in reader.pages:
                target_writer.add_page(page)
            temp_pdf_path.unlink()

    print(f"  ✅ Folder '{folder.name}' added to PDFs.")


def merge_pdfs(writer: PdfWriter, output_path: Path):
    with open(output_path, "wb") as f:
        writer.write(f)


def main():
    print("📥 Enter folder paths (one per line). Type 'q' to finish.")
    folders = []
    while True:
        inp = input("📁 Folder path (or 'q' to quit): ").strip()
        if inp.lower() == 'q':
            break
        path = Path(inp).expanduser().resolve()
        if path.is_dir():
            folders.append(path)
        else:
            print(f"❌ Invalid: {path}")

    if not folders:
        print("⚠️  No folders provided. Exit.")
        return

    # Writers for final merged PDFs
    main_writer = PdfWriter()
    answer_writer = PdfWriter()

    print(f"\n🚀 Processing {len(folders)} folders...\n")
    for folder in folders:
        process_folder(folder, main_writer, answer_writer)

    # Generate timestamp: YYMMDD_HHMM (2-digit year, month, day, hour, minute)
    timestamp = datetime.now().strftime("%y%m%d_%H%M")
    output_dir = folders[0].parent if folders else Path.cwd()

    main_pdf_path = output_dir / f"{timestamp}_SME.pdf"
    answer_pdf_path = output_dir / f"{timestamp}_SME_answer.pdf"

    print("\n💾 Saving final PDFs...")
    merge_pdfs(main_writer, main_pdf_path)
    merge_pdfs(answer_writer, answer_pdf_path)

    print(f"✅ Done!")
    print(f"📄 Main PDF:   {main_pdf_path}")
    print(f"✏️  Answer PDF: {answer_pdf_path}")


if __name__ == "__main__":
    main()