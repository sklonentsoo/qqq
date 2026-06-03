from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

def main_reply_keyboard():
    """Главная клавиатура (Reply-кнопки внизу экрана)"""
    buttons = [
        [KeyboardButton(text="🛒 Магазин")],
        [KeyboardButton(text="➕ Добавить в чат")],
        [KeyboardButton(text="❓ Поддержка")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def shop_menu():
    """Меню магазина (инлайн-кнопки)"""
    buttons = [
        [InlineKeyboardButton(text="🔇 Снять мут — 100 Дум", callback_data="buy_unmute")],
        [InlineKeyboardButton(text="⚠️ Снять предупреждение — 150 Дум", callback_data="buy_remove_warn")],
        [InlineKeyboardButton(text="🌟 Стать Фанатом на 24ч — 50 Дум", callback_data="buy_temp_fanat")],
        [InlineKeyboardButton(text="♾️ Безлимит мемов (месяц) — 250 Дум", callback_data="buy_unlimited_memes")],
        [InlineKeyboardButton(text="📝 Добавить слово в память — 10 Дум", callback_data="buy_learn_word")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)