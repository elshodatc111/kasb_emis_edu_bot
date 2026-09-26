"""Shaxsiy ma'lumotlarni (PINFL, pasport seriyasi/raqami) OpenAI ga yuborishdan oldin yashirish."""
from __future__ import annotations

import re

# PINFL: 14 xonali raqam (orasida bo'sh joy yoki '-' bo'lishi mumkin)
_PINFL = re.compile(r"(?<![\d])(?:\d[ \-]?){13}\d(?![\d])")
# Pasport: 2 harf + 7 raqam (AA1234567, AA 1234567, AA-1234567), kirill harflari ham
_PASSPORT = re.compile(r"(?<![A-Za-z\u0400-\u04FF\-])[A-Za-z\u0400-\u04FF]{2}[ \-]?\d{7}(?!\d)")
# ID-karta: 9 xonali raqam (faqat 'pasport'/'id' so'zi yonida bo'lsa)
_ID_HINT = re.compile(
    r"(?i)\b(pasport|passport|паспорт|id[- ]?karta|id[- ]?card|seriya|seriyasi)\b[^\n\d]{0,20}(\d{9})(?!\d)"
)


def mask_sensitive(text: str | None) -> tuple[str, int]:
    """Matndagi PINFL va pasport ma'lumotlarini yashiradi. (yangi_matn, almashtirishlar_soni) qaytaradi."""
    if not text:
        return text or "", 0
    count = 0

    def _sub(token: str):
        def inner(_m):
            nonlocal count
            count += 1
            return token

        return inner

    out = _PINFL.sub(_sub("[PINFL]"), text)
    out = _PASSPORT.sub(_sub("[PASPORT]"), out)

    def _id(m):
        nonlocal count
        count += 1
        return m.group(0).replace(m.group(2), "[PASPORT]")

    out = _ID_HINT.sub(_id, out)
    return out, count
