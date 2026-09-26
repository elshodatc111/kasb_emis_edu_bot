from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from aiogram import F

from ..constants import ROLE_ICONS, ROLES

# Tugma matnlari (emoji bilan). Filtrlar faqat oxirgi so'zlarga qaraydi, shuning uchun eski (emojisiz) tugmalar ham ishlaydi.
LBL_ADMIN, LBL_BOT, LBL_HELP = "Adminga murojaat", "Botga qaytish", "Yordam"
LBL_FAQ, LBL_VIDEO, LBL_QUIZ = "Ko'p so'raladigan savollar", "Video darslar", "Kunlik test"
BTN_ADMIN = f"🙋 {LBL_ADMIN}"
BTN_BOT = f"↩️ {LBL_BOT}"
BTN_HELP = f"ℹ️ {LBL_HELP}"
BTN_FAQ = f"❓ {LBL_FAQ}"
BTN_VIDEO = f"🎬 {LBL_VIDEO}"
BTN_QUIZ = f"🧩 {LBL_QUIZ}"


def is_button(label: str):
    """Tugma bosilganini aniqlaydi (emojiga bog'liq emas)."""
    return F.text.func(lambda t, _l=label: bool(t) and t.strip().endswith(_l))


def main_menu(admin_mode: bool = False) -> ReplyKeyboardMarkup:
    first = BTN_BOT if admin_mode else BTN_ADMIN
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text=first), KeyboardButton(text=BTN_HELP)],
        [KeyboardButton(text=BTN_FAQ), KeyboardButton(text=BTN_VIDEO)],
        [KeyboardButton(text=BTN_QUIZ)],
    ], resize_keyboard=True)


def phone_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Telefon raqamni yuborish", request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True)


def roles_keyboard() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"{ROLE_ICONS.get(r, '👤')} {r}", callback_data=f"role:{i}")] for i, r in enumerate(ROLES)]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def approval_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Ruxsat berish", callback_data=f"appr:{user_id}"),
        InlineKeyboardButton(text="❌ Rad etish", callback_data=f"rej:{user_id}"),
    ]])
