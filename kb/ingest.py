"""Index a folder of manuals, SOPs and correspondence. PHASE 2.

    python -m kb.ingest --source /data/sop --collection sop

Design notes so this does not drift while it is unbuilt:

  Extraction by type -- pdfplumber for born-digital PDFs, the OCR path in
  tools/vision.py for scanned ones, python-docx and openpyxl for Office,
  plain read for text.

  Chunking is structure-aware: split on headings and clause numbers first,
  fall back to 800-token windows with 100-token overlap. An SOP clause is
  a semantic unit, and splitting one mid-clause is how retrieval systems
  produce confident nonsense.

  Every chunk carries source path, page number, section heading and an
  ingest timestamp. Those four fields are what make a citation possible.
"""

from __future__ import annotations

import argparse
from pathlib import Path

CHUNK_TOKENS = 800
CHUNK_OVERLAP = 100


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--collection", default="default")
    args = parser.parse_args()

    if not args.source.is_dir():
        print(f"No such folder: {args.source}")
        return 1

    files = [p for p in args.source.rglob("*") if p.is_file()]
    print(f"Found {len(files)} files under {args.source}")
    print("Ingestion is not implemented yet (phase 2). Next steps:")
    print("  1. extract text by file type, keeping page numbers")
    print("  2. chunk on headings and clause numbers")
    print("  3. embed with inference.client.embed()")
    print("  4. upsert into the chroma collection with source metadata")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
