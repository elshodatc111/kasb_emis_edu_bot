"""Javoblarni Telegram (HTML) uchun tartibli ko'rinishga keltirish va ichki belgilarni tozalash."""
from __future__ import annotations

import html
import re

BOT_NAME = "AI Menejer"

# OpenAI file_search havolalari (masalan: fileciteturn3file7) foydalanuvchiga chiqmasligi kerak
_CITE_BLOCK = re.compile(r"[^]*")
_PRIVATE = re.compile(r"[-]")  # OpenAI'ning qolgan xizmat belgilari (Unicode Private Use Area)
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


_ITEM_RE = re.compile(r"^(<b>\d+\.</b>|▫️)")


def _body_html(body: str) -> str:
    """Matnni Telegram uchun tayyorlaydi: sarlavha/ro'yxat belgilari, ortiqcha bo'sh qatorlarsiz ixcham ko'rinish."""
    lines = []
    for raw in body.splitlines():
        line = raw.rstrip()
        line = re.sub(r"^#{1,6}\s*", "", line)          # markdown sarlavha belgilari
        line = re.sub(r"^[-*•]\s+", "▫️ ", line)          # ro'yxat belgilari
        m = re.match(r"^(\d+)[.)]\s+(.*)$", line)
        lines.append(f"<b>{m.group(1)}.</b> {_inline(m.group(2))}" if m else _inline(line))
    out: list[str] = []
    for i, line in enumerate(lines):
        if line == "":
            if not out or out[-1] == "":
                continue  # boshidagi yoki ketma-ket bo'sh qatorlarni olib tashlaydi
            prev_item, next_item = _ITEM_RE.match(out[-1]), _ITEM_RE.match(lines[i + 1] if i + 1 < len(lines) else "")
            if prev_item and next_item:
                continue  # ro'yxat bandlari orasida bo'sh joy qoldirmaydi
        out.append(line)
    return "\n".join(out).strip()


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
    blocks = [f"🤖 <b>{html.escape(BOT_NAME, quote=False)}</b>"]
    if title:
        blocks.append(f"<b>{html.escape(title.strip(), quote=False)}</b>")
    blocks.append(_body_html(body))
    if section:
        blocks.append(f"📎 <i>Manba: {html.escape(section.strip(), quote=False)}</i>")
    if video:
        blocks.append(f'🎬 Video dars: <a href="{html.escape(video[1], quote=True)}">{html.escape(video[0], quote=False)}</a>')
    return "\n\n".join(b for b in blocks if b)[:4000]


def admin_html(name: str, text: str) -> str:
    """Admin javobi: sarlavha o'rniga to'g'ridan-to'g'ri adminning ismi (AI javobidan ajratib turadi)."""
    return f"🧑‍💼 <b>{html.escape(name, quote=False)}</b>\n{_body_html(text)}"[:4000]


def system_html(text: str) -> str:
    """Bot xizmat xabarlari (javob topilmadi va h.k.) — nom bilan."""
    return f"🤖 <b>{html.escape(BOT_NAME, quote=False)}</b>\n\n{html.escape(text, quote=False)}"


ANN_KINDS = {
    "info": ("📢", "E'lon"),
    "important": ("🚨", "MUHIM OGOHLANTIRISH"),
    "reminder": ("⏰", "Eslatma"),
}


def visible_len(html_text: str) -> int:
    """Telegram limitlari teglarsiz matn uzunligiga qaraydi."""
    return len(html.unescape(re.sub(r"<[^>]+>", "", html_text)))


def ann_html(kind: str, title: str | None, text: str | None, author: str) -> str:
    """Ommaviy e'lon: nom, tur, sarlavha, matn va kim yuborgani."""
    icon, label = ANN_KINDS.get(kind, ANN_KINDS["info"])
    blocks = [f"🤖 <b>{html.escape(BOT_NAME, quote=False)}</b>\n{icon} <b>{label}</b>"]
    if title and title.strip():
        blocks.append(f"<b>{html.escape(title.strip(), quote=False)}</b>")
    if text and text.strip():
        blocks.append(_body_html(text.strip()))
    blocks.append(f"👤 <i>Admin: {html.escape(author, quote=False)}</i>")
    return "\n\n".join(blocks)
