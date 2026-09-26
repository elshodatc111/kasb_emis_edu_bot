from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from .handlers import router


def build_dispatcher() -> Dispatcher:
    router._parent_router = None  # bir necha marta yaratilsa (testlar) router qayta ulanishi uchun
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    return dp
