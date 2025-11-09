import os
from pathlib import Path
import re
from natsort import natsorted
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
import pytesseract
from PIL import Image, ImageEnhance, ImageFilter

EXCLUDE_FILES = ['00_Result.png', '00_Result']

def find_you_answered_y(img: Image.Image, lang="eng") -> int | None:
    """Locate y coordinate of the line 'You answered'"""
    # Preprocessing for better result
    gray = img.convert("L")
    enhancer = ImageEnhance.Contrast(gray)
    enhanced = enhancer.enhance(2.0)
    thresh = enhanced.point(lambda p: p > 128 and 255)

    # Tesseract parameters
    config = r'--oem 3 --psm 6 -c tessedit_char_whitelist=abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ .,'

    # Get OCR data with coordinates
    data = pytesseract.image_to_data(thresh, output_type=pytesseract.Output.DICT, lang=lang, config=config)

    # Search "You answered" (allow partial march)
    target_phrase = "You answered"
    for i in range(len(data["text"])):
        text = data["text"][i].strip()
        if not text:
            continue

        # Insensitive match
        if target_phrase.lower() in text.lower():
            y_orig = int(data["top"][i] * (img.height / thresh.height))
            height_orig = int(data["height"][i] * (img.height / thresh.height))
            print(f"  🟢 OCR matched '{text}' @ y={y_orig}")
            return y_orig

    # If not found, check you/answered separately
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

def main():
    folder = input("Input PNG folder path: ").strip()
    folder = Path(folder).expanduser().resolve()
    if not folder.is_dir():
        print("❌ Invalid path")
        return

    png_files = [f for f in folder.glob("*.png")
                 if f.is_file()
                 and f.name not in EXCLUDE_FILES]
    if not png_files:
        print("❌  No PNG found")
        return

    png_files.sort(key=lambda f: natural_sort_key(f.name))
    print(f"\n✅ {len(png_files)} PNG found; sorted:")
    for f in png_files:
        print(f"  - {f.name}")

    # Create pdf
    pdf_path = folder / "output.pdf"
    c = canvas.Canvas(str(pdf_path), pagesize=A4)
    width_pt, height_pt = A4

    MARGIN = 20
    AVAILABLE_HEIGHT = height_pt - 2 * MARGIN  # Available height
    CURRENT_Y = AVAILABLE_HEIGHT

    for i, png_path in enumerate(png_files, 1):
        print(f"Process {i}/{len(png_files)}: {png_path.name}")
        try:
            img = Image.open(png_path)
            w, h = img.size

            # OCR
            y_target = find_you_answered_y(img)
            if y_target is None:
                print("  🔄 OCR cannot determine 'You answered'")
                y_target = int(h * 0.45)
            if y_target <= 0 or y_target >= h:
                cropped_img = img
            else:
                cropped_img = img.crop((0, 0, w, y_target))

            # Scale
            max_width = width_pt - 2 * MARGIN
            scale = max_width / cropped_img.width
            draw_w = cropped_img.width * scale
            draw_h = cropped_img.height * scale

            # Check if new page is required
            if CURRENT_Y - draw_h < 0:
                c.showPage()
                CURRENT_Y = AVAILABLE_HEIGHT  # Reset Y

            # Draw pic
            x = (width_pt - draw_w) / 2
            y = CURRENT_Y - draw_h 

            temp_png = folder / f"__temp_{png_path.stem}.png"
            cropped_img.save(temp_png, "PNG")
            c.drawImage(str(temp_png), x, y, width=draw_w, height=draw_h)
            temp_png.unlink()

            CURRENT_Y -= draw_h + 10  # 10pt margin

        except Exception as e:
            print(f"  ❌ Processing failed: {e}")
            continue

    c.save()
    print(f"✅ PDF Created: {pdf_path}")

if __name__ == "__main__":
    main()