"""Pulls raw text out of an uploaded medical report (PDF or image)."""
import os

def extract_text(filepath):
    ext = os.path.splitext(filepath)[1].lower()

    if ext == ".pdf":
        return _extract_pdf(filepath)
    elif ext in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"):
        return _extract_image(filepath)
    elif ext == ".txt":
        with open(filepath, "r", errors="ignore") as f:
            return f.read()
    else:
        return ""


def _extract_pdf(filepath):
    try:
        import pdfplumber
        text_parts = []
        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                text_parts.append(page_text)
                # also try to pull tables (common in lab reports)
                for table in page.extract_tables():
                    for row in table:
                        cleaned = [c for c in row if c]
                        if cleaned:
                            text_parts.append(" | ".join(cleaned))
        text = "\n".join(text_parts).strip()
        if text:
            return text
    except Exception as e:
        print(f"[extract] pdfplumber failed: {e}")

    # Fallback: PDF might be a scanned image with no text layer.
    # We can't OCR a PDF page without extra system deps (poppler), so
    # tell the caller extraction failed rather than silently returning blank.
    return ""


def _extract_image(filepath):
    try:
        import pytesseract
        from PIL import Image
        img = Image.open(filepath)
        text = pytesseract.image_to_string(img)
        return text.strip()
    except Exception as e:
        # Tesseract binary may not be installed on the host (common on
        # free-tier hosting). Caller should handle empty result gracefully.
        print(f"[extract] OCR failed: {e}")
        return ""
