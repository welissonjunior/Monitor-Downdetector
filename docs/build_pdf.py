#!/usr/bin/env python3
"""Gera docs/MANUAL_INSTALACAO.pdf a partir de docs/manual-instalacao.html.

Layout idêntico ao padrão SG/JR.TEC.BR (capa escura, páginas de 1121px, A4 sem margem).

Uso:
    python docs/build_pdf.py

Saída: docs/MANUAL_INSTALACAO.pdf (via Chrome headless)
"""
from __future__ import annotations
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
HTML = HERE / "manual-instalacao.html"
PDF = HERE / "MANUAL_INSTALACAO.pdf"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


def main() -> int:
    if not HTML.exists():
        sys.exit(f"Fonte não encontrada: {HTML}")
    subprocess.run(
        [CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
         "--user-data-dir=" + str(pathlib.Path(tempfile.gettempdir()) / "chrome-headless-pdf"),
         "--no-first-run", "--disable-extensions",
         f"--print-to-pdf={PDF}", "file:///" + str(HTML).replace("\\", "/")],
        check=True, capture_output=True, timeout=180,
    )
    print(f"ok {PDF} ({PDF.stat().st_size/1024:.0f} kB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
