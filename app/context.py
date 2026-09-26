from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .agent import TexnikumAgent
from .config import Settings
from .db import Database
from .hub import Hub


@dataclass
class Context:
    settings: Settings
    db: Database
    bot: Any
    agent: TexnikumAgent
    hub: Hub


_ctx: Context | None = None


def set_ctx(ctx: Context) -> None:
    global _ctx
    _ctx = ctx


def get_ctx() -> Context:
    if _ctx is None:
        raise RuntimeError("Context hali yaratilmagan")
    return _ctx
