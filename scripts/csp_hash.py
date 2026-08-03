"""Satir ici tema onyukleyicisinin CSP sha256 karmasini hesaplar.

Kullanim:
    python3 scripts/csp_hash.py

Cikan degeri `src/middleware.py` icindeki `_INLINE_SCRIPT_HASH` sabitine yaz.
Nonce yerine hash kullaniliyor: cache'lenen HTML govdesi nonce'u bayatlatir,
hash ise statik icerik icin kalicidir.
"""

import base64
import hashlib
import re
import sys
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "partials" / "tema_onyukleyici.html"


def main() -> int:
    """Sablondaki <script> govdesinin sha256-base64 karmasini yazdirir."""
    html = TEMPLATE.read_text(encoding="utf-8")
    match = re.search(r"<script>(.*?)</script>", html, re.DOTALL)
    if match is None:
        print("HATA: <script> blogu bulunamadi", file=sys.stderr)
        return 1
    govde = match.group(1)
    digest = base64.b64encode(hashlib.sha256(govde.encode()).digest()).decode()
    print(f"'sha256-{digest}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
