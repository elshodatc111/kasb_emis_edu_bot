from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


def _int_list(value: str) -> list[int]:
    out: list[int] = []
    for part in value.replace(";", ",").split(","):
        part = part.strip()
        if part.isdigit():
            out.append(int(part))
    return out


def _admins(value: str) -> tuple[list[int], dict[int, str]]:
    """ADMIN_IDS: '123:Ism Familiya, 456:Ism' yoki oddiy '123,456'."""
    ids: list[int] = []
    names: dict[int, str] = {}
    for part in value.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        raw_id, _, name = part.partition(":")
        raw_id = raw_id.strip()
        if raw_id.isdigit():
            ids.append(int(raw_id))
            if name.strip():
                names[int(raw_id)] = name.strip()
    return ids, names


def _days(value: str, default: str) -> frozenset[int]:
    """'1-5' yoki '1,2,3' -> {1..7} (1 = dushanba)."""
    out: set[int] = set()
    for part in (value or default).replace(" ", "").split(","):
        if "-" in part:
            a, _, b = part.partition("-")
            if a.isdigit() and b.isdigit():
                out.update(range(int(a), int(b) + 1))
        elif part.isdigit():
            out.add(int(part))
    out = {d for d in out if 1 <= d <= 7}
    return frozenset(out) if out else frozenset({1, 2, 3, 4, 5})


def _hhmm(value: str, default: str) -> tuple[int, int]:
    try:
        h, m = (value or default).strip().split(":")
        return int(h), int(m)
    except Exception:
        h, m = default.split(":")
        return int(h), int(m)


@dataclass
class Settings:
    bot_token: str = ""
    admin_ids: list[int] = field(default_factory=list)
    admin_names: dict[int, str] = field(default_factory=dict)
    openai_api_key: str = ""
    openai_admin_key: str = ""
    vector_store_id: str = ""
    model: str = "gpt-6-luna"
    report_model: str = "gpt-6-luna"
    web_host: str = "127.0.0.1"
    web_port: int = 8000
    base_url: str = "http://127.0.0.1:8000"
    cookie_secure: bool = False
    secret_key: str = ""
    timezone: str = "Asia/Tashkent"
    db_path: str = "data/texnikum.db"
    rate_limit_per_min: int = 6
    history_turns: int = 6
    admin_mode_timeout_min: int = 60
    daily_time: tuple[int, int] = (20, 0)
    weekly_time: tuple[int, int] = (20, 30)
    monthly_time: tuple[int, int] = (9, 0)
    # admin ish vaqti (foydalanuvchiga ogohlantirish uchun)
    work_start: tuple[int, int] = (9, 0)
    work_end: tuple[int, int] = (19, 0)
    work_days: frozenset = frozenset({1, 2, 3, 4, 5})
    # javobsiz suhbatlar haqida adminga eslatma
    remind_every_min: int = 10
    remind_from: tuple[int, int] = (8, 0)
    remind_to: tuple[int, int] = (22, 0)
    # kunlik viktorina
    quiz_start: tuple[int, int] = (12, 20)
    quiz_end: tuple[int, int] = (13, 0)
    quiz_size: int = 5
    quiz_days: frozenset = frozenset({1, 2, 3, 4, 5, 6, 7})
    # FAQ tahlili
    faq_time: tuple[int, int] = (21, 30)
    faq_days: int = 30

    def admin_name(self, admin_id: int | None) -> str:
        return self.admin_names.get(admin_id or 0) or "Administrator"

    @property
    def db_file(self) -> Path:
        p = Path(self.db_path)
        return p if p.is_absolute() else ROOT / p


def _secret(explicit: str) -> str:
    if explicit:
        return explicit
    path = ROOT / "data" / ".secret"
    try:
        if path.exists():
            return path.read_text().strip()
        path.parent.mkdir(parents=True, exist_ok=True)
        value = secrets.token_hex(32)
        path.write_text(value)
        return value
    except OSError:
        return secrets.token_hex(32)


def load_settings(env_file: str | None = None) -> Settings:
    load_dotenv(env_file or ROOT / ".env", encoding="utf-8-sig")
    g = os.environ.get
    model = g("OPENAI_MODEL", "gpt-6-luna").strip() or "gpt-6-luna"
    admin_ids, admin_names = _admins(g("ADMIN_IDS", ""))
    return Settings(
        bot_token=g("BOT_TOKEN", "").strip(),
        admin_ids=admin_ids,
        admin_names=admin_names,
        openai_api_key=g("OPENAI_API_KEY", "").strip(),
        openai_admin_key=g("OPENAI_ADMIN_KEY", "").strip(),
        vector_store_id=g("OPENAI_VECTOR_STORE_ID", "").strip(),
        model=model,
        report_model=(g("OPENAI_REPORT_MODEL", "").strip() or model),
        web_host=g("WEB_HOST", "127.0.0.1").strip(),
        web_port=int(g("WEB_PORT", "8000") or 8000),
        base_url=g("BASE_URL", "http://127.0.0.1:8000").strip().rstrip("/"),
        cookie_secure=g("COOKIE_SECURE", "0").strip() in ("1", "true", "True"),
        secret_key=_secret(g("SECRET_KEY", "").strip()),
        timezone=g("TIMEZONE", "Asia/Tashkent").strip(),
        db_path=g("DB_PATH", "data/texnikum.db").strip(),
        rate_limit_per_min=int(g("RATE_LIMIT_PER_MIN", "6") or 6),
        history_turns=int(g("HISTORY_TURNS", "6") or 6),
        admin_mode_timeout_min=int(g("ADMIN_MODE_TIMEOUT_MIN", "60") or 60),
        daily_time=_hhmm(g("DAILY_REPORT_TIME", ""), "20:00"),
        weekly_time=_hhmm(g("WEEKLY_REPORT_TIME", ""), "20:30"),
        monthly_time=_hhmm(g("MONTHLY_REPORT_TIME", ""), "09:00"),
        work_start=_hhmm(g("WORK_START", ""), "09:00"),
        work_end=_hhmm(g("WORK_END", ""), "19:00"),
        work_days=_days(g("WORK_DAYS", ""), "1-5"),
        remind_every_min=max(1, int(g("REMIND_EVERY_MIN", "10") or 10)),
        remind_from=_hhmm(g("REMIND_FROM", ""), "08:00"),
        remind_to=_hhmm(g("REMIND_TO", ""), "22:00"),
        quiz_start=_hhmm(g("QUIZ_START", ""), "12:20"),
        quiz_end=_hhmm(g("QUIZ_END", ""), "13:00"),
        quiz_size=max(1, int(g("QUIZ_SIZE", "5") or 5)),
        quiz_days=_days(g("QUIZ_DAYS", ""), "1-7"),
        faq_time=_hhmm(g("FAQ_TIME", ""), "21:30"),
    )
