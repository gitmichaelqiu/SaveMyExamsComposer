import os
from pathlib import Path
import re
from datetime import datetime
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
import pytesseract
from PIL import Image, ImageEnhance

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
    """Custom sort key for names like '1_a', '1_b', '2', '10'."""
    stem = Path(name).stem
    match = re.match(r"(\d+)(?:_([a-zA-Z]))?", stem)
    if not match:
        return (float('inf'), '')
    num = int(match.group(1))
    suffix = match.group(2) or ''
    return (num, suffix)

def add_title_page(c: canvas.Canvas, title: str):
    """Adds a centered title page to the canvas."""
    width_pt, height_pt = A4
    c.setFont("Helvetica-Bold", 24)
    c.drawCentredString(width_pt / 2, height_pt / 2, title)
    c.showPage()

def add_image_page(c: canvas.Canvas, img_to_draw: Image.Image | None, label: str, index: int):
    """
    Adds the PIL image to the canvas, scaled to fit, with an index label.
    If img_to_draw is None, it adds a placeholder page.
    """
    width_pt, height_pt = A4
    
    # Draw the index label
    c.setFont("Helvetica", 10)
    c.drawString(0.5 * inch, height_pt - 0.5 * inch, f"{label}: {index}")

    if img_to_draw is None:
        c.setFont("Helvetica", 12)
        c.drawCentredString(width_pt / 2, height_pt / 2, "No corresponding content found.")
        c.showPage()
        return

    try:
        # Scale image to fit page with some margin
        img_width, img_height = img_to_draw.size
        
        # Use 90% of page height and full width for scaling
        scale_w = width_pt / img_width
        scale_h = (height_pt * 0.9) / img_height
        scale = min(scale_w, scale_h)
        
        draw_w = img_width * scale
        draw_h = img_height * scale
        
        # Center the image
        x = (width_pt - draw_w) / 2
        y = (height_pt - draw_h) / 2 # Centered vertically
        
        # Use ImageReader to draw PIL Image directly
        c.drawImage(ImageReader(img_to_draw), x, y, width=draw_w, height=draw_h)
        
    except Exception as e:
        print(f"    ❌ Failed to draw image: {e}")
        c.drawCentredString(width_pt / 2, height_pt / 2, f"Error drawing image for index {index}.")
        
    c.showPage() # Finalize the page

def main():
    # 1. Collect multiple folder paths
    folder_paths = []
    print("Enter paths to PNG folders. Press Enter on an empty line to finish.")
    while True:
        path_str = input(f"Folder {len(folder_paths) + 1} path: ").strip()
        if not path_str:
            break
        
        folder = Path(path_str).expanduser().resolve()
        if folder.is_dir():
            folder_paths.append(folder)
            print(f"  Added: {folder}")
        else:
            print("  ❌ Invalid path, folder not found.")
            
    if not folder_paths:
        print("No folders provided. Exiting.")
        return

    # 2. Set up output PDF files
    timestamp = datetime.now().strftime("%y%m%d_%H%M")
    
    # Save PDFs in the parent directory of the *first* folder
    save_dir = folder_paths[0].parent
    
    pdf_name_q = f"{timestamp}_SME_Questions.pdf"
    pdf_name_a = f"{timestamp}_SME_Answers.pdf"
    
    pdf_path_q = save_dir / pdf_name_q
    pdf_path_a = save_dir / pdf_name_a

    c_questions = canvas.Canvas(str(pdf_path_q), pagesize=A4)
    c_answers = canvas.Canvas(str(pdf_path_a), pagesize=A4)

    print(f"\nSaving Question PDF to: {pdf_path_q}")
    print(f"Saving Answer PDF to:   {pdf_path_a}")
    
    question_index = 1

    # 3. Process each folder
    for folder in folder_paths:
        print(f"\n--- Processing folder: {folder.name} ---")

        # Add title pages for this folder
        add_title_page(c_questions, folder.name)
        add_title_page(c_answers, folder.name)

        # Find and sort PNG files
        png_files = [f for f in folder.glob("*.png")
                     if f.is_file()
                     and f.name not in EXCLUDE_FILES]
        
        if not png_files:
            print("  ❌ No PNGs found in this folder. Skipping.")
            continue
            
        png_files.sort(key=lambda f: natural_sort_key(f.name))
        
        print(f"  ✅ {len(png_files)} PNGs found and sorted.")

        # 4. Process each image in the folder
        for i, png_path in enumerate(png_files, 1):
            print(f"  Processing {i}/{len(png_files)}: {png_path.name}")
            try:
                img = Image.open(png_path)
                w, h = img.size

                question_img = None
                answer_img = None

                y_target = find_you_answered_y(img)
                
                if y_target is None:
                    print("    'You answered' not found, using full image as question.")
                    question_img = img
                    answer_img = None # No answer part, will create blank answer page
                else:
                    # Crop image into question and answer
                    question_img = img.crop((0, 0, w, y_target))
                    answer_img = img.crop((0, y_target, w, h))

                # Add pages to both PDFs with the same index
                add_image_page(c_questions, question_img, "Question", question_index)
                add_image_page(c_answers, answer_img, "Answer", question_index)
                
                question_index += 1 # Increment global index

            except Exception as e:
                print(f"    ❌ Failed to process {png_path.name}: {e}")
                continue

    # 5. Save the final PDFs
    c_questions.save()
    c_answers.save()
    print("\n---")
    print(f"✅ Question PDF Created: {pdf_path_q}")
    print(f"✅ Answer PDF Created:   {pdf_path_a}")
    print("---")

if __name__ == "__main__":
    main()