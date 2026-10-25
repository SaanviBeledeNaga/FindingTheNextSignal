"""Isolated, killable PDF text extraction. Documents are data, never code."""
import json
from pathlib import Path
import sys

from .ingest import read_pages


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    print(json.dumps(read_pages(Path(sys.argv[1]), fast=True), ensure_ascii=True))
