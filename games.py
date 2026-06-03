import random
from aiogram import Router, types, F, Bot
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database import update_game_stats, get_game_stats

router = Router()

# Словарь для активных вызовов: ключ (chat_id, challenger_id) -> данные
challenges = {}

@router.callback_query(F.data.startswith("accept_game_"))
async def accept_game(callback: types.CallbackQuery, bot: Bot):
    data = callback.data.split('_')
    game_type = data[2]
    challenger_id = int(data[3])
    chat_id = callback.message.chat.id
    opponent_id = callback.from_user.id
    if opponent_id == challenger_id:
        await callback.answer("Нельзя играть с самим собой!")
        return
    key = (chat_id, challenger_id)
    if key not in challenges or challenges[key]['game'] != game_type:
        await callback.answer("Вызов устарел или не найден.", show_alert=True)
        return
    await callback.message.delete()
    challenger_name = (await bot.get_chat_member(chat_id, challenger_id)).user.first_name
    opponent_name = callback.from_user.first_name
    if game_type == 'duel':
        challenger_roll = random.randint(1, 6)
        opponent_roll = random.randint(1, 6)
        text = f"🎲 **Дуэль**\n{challenger_name} vs {opponent_name}\n\nКубик {challenger_name}: {challenger_roll}\nКубик {opponent_name}: {opponent_roll}\n"
        if challenger_roll > opponent_roll:
            text += f"🏆 Победил {challenger_name}!"
            update_game_stats(challenger_id, 'duel', 'win')
            update_game_stats(opponent_id, 'duel', 'loss')
        elif challenger_roll < opponent_roll:
            text += f"🏆 Победил {opponent_name}!"
            update_game_stats(challenger_id, 'duel', 'loss')
            update_game_stats(opponent_id, 'duel', 'win')
        else:
            text += "🤝 Ничья!"
        await callback.message.answer(text)
    elif game_type == 'basketball':
        challenger_score = random.randint(0, 15)
        opponent_score = random.randint(0, 15)
        text = f"🏀 **Баскетбол**\n{challenger_name} vs {opponent_name}\n\nСчёт: {challenger_score} : {opponent_score}\n"
        if challenger_score > opponent_score:
            text += f"🏆 Победил {challenger_name}!"
            update_game_stats(challenger_id, 'basketball', 'win')
            update_game_stats(opponent_id, 'basketball', 'loss')
        elif challenger_score < opponent_score:
            text += f"🏆 Победил {opponent_name}!"
            update_game_stats(challenger_id, 'basketball', 'loss')
            update_game_stats(opponent_id, 'basketball', 'win')
        else:
            text += "🤝 Ничья!"
        await callback.message.answer(text)
    elif game_type == 'dice':
        challenger_roll = random.randint(1, 6)
        opponent_roll = random.randint(1, 6)
        text = f"🎲 **Кубик**\n{challenger_name} vs {opponent_name}\n\nВыпало у {challenger_name}: {challenger_roll}\nВыпало у {opponent_name}: {opponent_roll}\n"
        if challenger_roll > opponent_roll:
            text += f"🏆 Победил {challenger_name}!"
            update_game_stats(challenger_id, 'dice', 'win')
            update_game_stats(opponent_id, 'dice', 'loss')
        elif challenger_roll < opponent_roll:
            text += f"🏆 Победил {opponent_name}!"
            update_game_stats(challenger_id, 'dice', 'loss')
            update_game_stats(opponent_id, 'dice', 'win')
        else:
            text += "🤝 Ничья!"
        await callback.message.answer(text)
    del challenges[key]

# Команда /duel
@router.message(Command("duel"))
async def cmd_duel(message: types.Message, bot: Bot):
    if message.chat.type == 'private':
        await message.reply("❌ Играть можно только в группах.")
        return
    args = message.text.split()
    if len(args) < 2:
        await message.reply("❌ Использование: `/duel @username`")
        return
    target_username = args[1].lstrip('@')
    try:
        chat_member = await bot.get_chat_member(message.chat.id, target_username)
        target_id = chat_member.user.id
    except:
        await message.reply("❌ Пользователь не найден.")
        return
    if target_id == message.from_user.id:
        await message.reply("❌ Нельзя вызвать самого себя.")
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎮 Принять вызов", callback_data=f"accept_game_duel_{message.from_user.id}")]
    ])
    sent_msg = await message.reply(f"@{target_username}, {message.from_user.full_name} вызывает вас на дуэль! Нажмите кнопку.", reply_markup=keyboard)
    challenges[(message.chat.id, message.from_user.id)] = {
        'game': 'duel',
        'opponent_id': target_id,
        'message_id': sent_msg.message_id
    }

# Команда /basketball
@router.message(Command("basketball"))
async def cmd_basketball(message: types.Message, bot: Bot):
    if message.chat.type == 'private':
        await message.reply("❌ Играть можно только в группах.")
        return
    args = message.text.split()
    if len(args) < 2:
        await message.reply("❌ Использование: `/basketball @username`")
        return
    target_username = args[1].lstrip('@')
    try:
        chat_member = await bot.get_chat_member(message.chat.id, target_username)
        target_id = chat_member.user.id
    except:
        await message.reply("❌ Пользователь не найден.")
        return
    if target_id == message.from_user.id:
        await message.reply("❌ Нельзя вызвать самого себя.")
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏀 Принять вызов", callback_data=f"accept_game_basketball_{message.from_user.id}")]
    ])
    sent_msg = await message.reply(f"@{target_username}, {message.from_user.full_name} вызывает вас на баскетбол! Нажмите кнопку.", reply_markup=keyboard)
    challenges[(message.chat.id, message.from_user.id)] = {
        'game': 'basketball',
        'opponent_id': target_id,
        'message_id': sent_msg.message_id
    }

# Команда /dice
@router.message(Command("dice"))
async def cmd_dice(message: types.Message, bot: Bot):
    if message.chat.type == 'private':
        await message.reply("❌ Играть можно только в группах.")
        return
    args = message.text.split()
    if len(args) < 2:
        await message.reply("❌ Использование: `/dice @username`")
        return
    target_username = args[1].lstrip('@')
    try:
        chat_member = await bot.get_chat_member(message.chat.id, target_username)
        target_id = chat_member.user.id
    except:
        await message.reply("❌ Пользователь не найден.")
        return
    if target_id == message.from_user.id:
        await message.reply("❌ Нельзя вызвать самого себя.")
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎲 Принять вызов", callback_data=f"accept_game_dice_{message.from_user.id}")]
    ])
    sent_msg = await message.reply(f"@{target_username}, {message.from_user.full_name} вызывает вас на кости! Нажмите кнопку.", reply_markup=keyboard)
    challenges[(message.chat.id, message.from_user.id)] = {
        'game': 'dice',
        'opponent_id': target_id,
        'message_id': sent_msg.message_id
    }

# Статистика игр
@router.message(Command("game_stats"))
async def cmd_game_stats(message: types.Message):
    user_id = message.from_user.id
    stats = get_game_stats(user_id)
    text = (
        f"📊 **Ваша игровая статистика**\n\n"
        f"🎲 **Дуэль**: побед {stats[1]} — поражений {stats[2]}\n"
        f"🏀 **Баскетбол**: побед {stats[3]} — поражений {stats[4]}\n"
        f"🎲 **Кубик**: побед {stats[5]} — поражений {stats[6]}"
    )
    await message.reply(text, parse_mode="Markdown")