from pathlib import Path

import pypdf

PDF_PATH = Path(__file__).parent / "data" / "raw" / "GregMat Vocab.pdf"

reader = pypdf.PdfReader(PDF_PATH)
print(f"Pages: {len(reader.pages)}")
print("\n" + "="*80)
print("FIRST PAGE CONTENT:")
print("="*80)
print(reader.pages[0].extract_text())
print("\n" + "="*80)
print("SECOND PAGE CONTENT:")
print("="*80)
print(reader.pages[1].extract_text())
