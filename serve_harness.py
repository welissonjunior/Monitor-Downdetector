#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Servidor local do harness Downdetector.

Serve os arquivos do projeto em http://127.0.0.1:8791/ e mapeia
/public/img/downdetector/<arquivo>.png -> logos/<arquivo>.png
(mesmo caminho em que o Grafana real hospeda os ícones — assim o harness
mostra os logos igual à TV, em vez de cair no fallback de iniciais).

Uso:
    python serve_harness.py            # porta 8791
    python serve_harness.py 9000       # outra porta

Abra:
    http://127.0.0.1:8791/harness_wallboard.html?scn=3
    http://127.0.0.1:8791/harness_user.html?scn=3
"""

import sys
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOGO_PREFIX = "/public/img/downdetector/"


class HarnessHandler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        clean = path.split("?")[0].split("#")[0]
        if clean.startswith(LOGO_PREFIX):
            name = clean[len(LOGO_PREFIX):]
            return str(ROOT / "logos" / name)
        return super().translate_path(path)

    def log_message(self, fmt, *args):
        pass  # silencia o log por request


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8791
    addr = ("127.0.0.1", port)
    print(f"Harness servindo em http://127.0.0.1:{port}/ (logos em {LOGO_PREFIX} -> logos/)")
    print("Abra: http://127.0.0.1:%d/harness_wallboard.html?scn=3" % port)
    ThreadingHTTPServer(addr, HarnessHandler).serve_forever()
