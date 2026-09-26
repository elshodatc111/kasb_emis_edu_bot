"""Javoblarni Telegram (HTML) uchun tartibli ko'rinishga keltirish va ichki belgilarni tozalash."""
from __future__ import annotations

import html
import re

BOT_NAME = "Texnik yordam markazi"

# OpenAI file_search havolalari (masalan: fileciteturn3file7) foydalanuvchiga chiqmasligi kerak
_CITE_BLOCK = re.compile(r"\ue200[^\ue201]*\ue201")
_PRIVATE = re.compile(r"[-]")
_TURN_REF = re.compile(r"\s*\[?\bturn\d+file\d+\b\]?")


def clean_citations(text: str) -> str:
    text = _CITE_BLOCK.sub("", text or "")
    text = _PRIVATE.sub("", text)
    text = _TURN_REF.sub("", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _inline(text: str) -> str:
    """Xavfsiz: avval HTML escape, keyin **qalin** va `kod` belgilari."""
    t = html.escape(text, quote=False)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", t)
    return t


def _body_html(body: str) -> str:
    lines = []
    for raw in body.splitlines():
        line = raw.rstrip()
        line = re.sub(r"^#{1,6}\s*", "", line)          # markdown sarlavha belgilari
        line = re.sub(r"^[-*•]\s+", "▫️ ", line)          # ro'yxat belgilari
        m = re.match(r"^(\d+)[.)]\s+(.*)$", line)
        lines.append(f"<b>{m.group(1)}.</b> {_inline(m.group(2))}" if m else _inline(line))
    return "\n".join(lines).strip()


def bot_plain(title: str, body: str, section: str = "", video: tuple[str, str] | None = None) -> str:
    """Bazada / panelda ko'rinadigan oddiy matn."""
    parts = []
    if title:
        parts.append(title)
    parts.append(clean_citations(body))
    if section:
        parts.append(f"Manba: {section}")
    if video:
        parts.append(f"Video dars: {video[0]} — {video[1]}")
    return "\n\n".join(parts)


def bot_html(title: str, body: str, section: str = "", video: tuple[str, str] | None = None) -> str:
    body = clean_citations(body)
    out = [f"🎓 <b>{html.escape(BOT_NAME, quote=False)}</b>", "━━━━━━━━━━━━━━"]
    if title:
        out.append(f"<b>{html.escape(title.strip(), quote=False)}</b>")
    out.append("")
    out.append(_body_html(body))
    if section:
        out += ["", f"📎 <i>Manba: {html.escape(section.strip(), quote=False)}</i>"]
    if video:
        out += ["", f'🎬 Video dars: <a href="{html.escape(video[1], quote=True)}">{html.escape(video[0], quote=False)}</a>']
    return "\n".join(out)[:4000]


def admin_html(name: str, text: str) -> str:
    return f"👤 <b>Admin: {html.escape(name, quote=False)}</b>\n━━━━━━━━━━━━━━\n\n{_body_html(text)}"[:4000]


def system_html(text: str) -> str:
    """Bot xizmat xabarlari (javob topilmadi va h.k.) — nom bilan."""
    return f"🎓 <b>{html.escape(BOT_NAME, quote=False)}</b>\n━━━━━━━━━━━━━━\n\n{html.escape(text, quote=False)}"
