from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from ..constants import ROLES

BTN_ADMIN = "Adminga murojaat"
BTN_BOT = "Botga qaytish"
BTN_HELP = "Yordam"
BTN_FAQ = "Ko'p so'raladigan savollar"
BTN_VIDEO = "Video darslar"
BTN_QUIZ = "Kunlik test"


def main_menu(admin_mode: bool = False) -> ReplyKeyboardMarkup:
    first = BTN_BOT if admin_mode else BTN_ADMIN
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text=first), KeyboardButton(text=BTN_HELP)],
        [KeyboardButton(text=BTN_FAQ), KeyboardButton(text=BTN_VIDEO)],
        [KeyboardButton(text=BTN_QUIZ)],
    ], resize_keyboard=True)


def phone_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Telefon raqamni yuborish", request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True)


def roles_keyboard() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=r, callback_data=f"role:{i}")] for i, r in enumerate(ROLES)]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def approval_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Ruxsat berish", callback_data=f"appr:{user_id}"),
        InlineKeyboardButton(text="Rad etish", callback_data=f"rej:{user_id}"),
    ]])
