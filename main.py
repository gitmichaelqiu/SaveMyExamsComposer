import os
from pathlib import Path
import re
from natsort import natsorted
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
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
    c = canvas.Canvas(str(pdf_path), pagesize=letter)
    width_pt, height_pt = letter

    print("")

    for i, png_path in enumerate(png_files, 1):
        print(f"Processing {i}/{len(png_files)}: {png_path.name}")
        try:
            img = Image.open(png_path)
            w, h = img.size

            y_target = find_you_answered_y(img)
            if y_target is None:
                print(f"  'You answered' not found, cropping skipped")
                cropped_img = img
            else:
                cropped_img = img.crop((0, 0, w, y_target))

            # temp png
            temp_png = folder / f"__temp_{png_path.stem}.png"
            cropped_img.save(temp_png, "PNG")

            # scale image
            img_width, img_height = cropped_img.size
            scale_w = width_pt / img_width
            scale_h = (height_pt * 0.9) / img_height # margin
            scale = min(scale_w, scale_h)
            draw_w = img_width * scale
            draw_h = img_height * scale
            x = (width_pt - draw_w) / 2
            y = (height_pt - draw_h) / 2

            c.drawImage(str(temp_png), x, y, width=draw_w, height=draw_h)
            c.showPage()  # New page

            temp_png.unlink()  # Delete temp

        except Exception as e:
            print(f"  ❌ Failed: {e}")
            continue

    c.save()
    print(f"✅ PDF Created: {pdf_path}")

if __name__ == "__main__":
    main()