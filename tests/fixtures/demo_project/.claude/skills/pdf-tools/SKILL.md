---
name: pdf-tools
description: Extract text and tables from PDF files, fill forms, merge documents
---

# PDF tools

Use pdfplumber for text extraction. For scanned documents fall back to OCR via pytesseract with a confidence threshold of 0.8. Tables should be extracted with the lattice strategy first, then stream strategy if lattice finds nothing. Always preserve the original reading order of the document when emitting extracted text. Forms are filled with pypdf's update_page_form_field_values; flatten the form after filling unless the user asks to keep it editable. When merging documents keep bookmarks from every source file and re-number pages sequentially.
