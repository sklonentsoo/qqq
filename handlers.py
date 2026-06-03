import asyncio
import re
from datetime import datetime, timedelta
from aiogram import Router, types, F, Bot
from aiogram.filters import Command, ChatMemberUpdatedFilter, JOIN_TRANSITION
from filters import HasRole, get_role_level, ROLE_HIERARCHY
from database import *
from config import ADMIN_IDS, SUPPORT_LINK
from keyboards import main_reply_keyboard, shop_menu
import utils

router = Router()

# ---------- Ожидающие действия для оплаты ----------
pending_actions = {}

async def extract_chat_id_from_message(message: types.Message) -> int | None:
    if message.forward_from_chat:
        return message.forward_from_chat.id
    if message.text:
        match = re.search(r'https://t\.me/c/(\d+)', message.text)
        if match:
            return -100 + int(match.group(1))
        if message.text.lstrip('-').isdigit():
            return int(message.text)
    return None

def can_punish(moderator_id: int, target_id: int) -> bool:
    if moderator_id == target_id:
        return False
    mod_user = get_user(moderator_id)
    tgt_user = get_user(target_id)
    if not mod_user or not tgt_user:
        return False
    return get_role_level(mod_user[3]) > get_role_level(tgt_user[3])

async def get_chat_owner(bot: Bot, chat_id: int) -> int | None:
    try:
        admins = await bot.get_chat_administrators(chat_id)
        for admin in admins:
            if admin.status == "creator":
                return admin.user.id
    except Exception:
        pass
    return None

# ---------- Добавление бота в чат ----------
@router.my_chat_member(ChatMemberUpdatedFilter(member_status_changed=JOIN_TRANSITION))
async def on_bot_added(event: types.ChatMemberUpdated, bot: Bot):
    chat_id = event.chat.id
    chat_title = event.chat.title or "Без названия"
    add_bot_chat(chat_id, chat_title)
    owner_id = await get_chat_owner(bot, chat_id)
    if owner_id:
        create_user_if_not_exists(owner_id, None, None)
        user = get_user(owner_id)
        current_role = user[3] if user else 'Ньюген'
        if get_role_level(current_role) < get_role_level("Отец"):
            update_user_role(owner_id, "Отец")
            await bot.send_message(owner_id, f"🏆 Вы назначены **Отцом** в чате `{chat_title}`.")
    await bot.send_message(chat_id, "✅ Бот добавлен! Выдайте ему права администратора для работы модерации.")

# ---------- Обработчик сообщений в группах ----------
consecutive_tracker = {}

@router.message(F.chat.type.in_({'group', 'supergroup'}))
async def message_handler(message: types.Message, bot: Bot):
    user_id = message.from_user.id
    chat_id = message.chat.id
    if message.from_user.is_bot:
        return
    if is_banned(user_id):
        await message.delete()
        return
    if is_muted_in_chat(user_id, chat_id):
        await message.delete()
        await message.answer(f"❌ {message.from_user.full_name}, вы в муте.", delete_after=5)
        return
    create_user_if_not_exists(user_id, message.from_user.username, message.from_user.full_name)
    update_message_stats(user_id)
    
    # Антифлуд
    now = datetime.now()
    tracker = consecutive_tracker.get(chat_id)
    if tracker is None or tracker['user_id'] != user_id:
        consecutive_tracker[chat_id] = {'user_id': user_id, 'count': 1, 'last_time': now}
    else:
        time_diff = (now - tracker['last_time']).total_seconds()
        if time_diff <= 10:
            tracker['count'] += 1
            tracker['last_time'] = now
            if tracker['count'] >= 10:
                until = now + timedelta(minutes=10)
                mute_user_in_chat(user_id, chat_id, until, user_id, reason="Авто-флуд")
                await message.answer(f"⚠️ {message.from_user.full_name} мут 10 минут за флуд.")
                await message.delete()
                consecutive_tracker[chat_id]['count'] = 0
                return
        else:
            tracker['count'] = 1
            tracker['last_time'] = now
    
    # Фильтр мата
    if message.text and is_forbidden(message.text):
        await message.delete()
        warn_count = add_warning(user_id, 0, f"Запрещённое слово: {message.text[:50]}")
        await message.answer(f"🚫 {message.from_user.full_name}, предупреждение {warn_count}/3.")
        if warn_count >= 3:
            ban_user(user_id, 0, "3 предупреждения")
            await message.answer(f"🔨 {message.from_user.full_name} забанен.")
            try:
                await bot.ban_chat_member(chat_id, user_id)
            except: pass
        return
    
    # Защита от ссылок
    if message.text and utils.contains_non_whitelisted_link(message.text):
        await message.delete()
        until = datetime.now() + timedelta(hours=1)
        mute_user_in_chat(user_id, chat_id, until, 0, reason="Запрещённая ссылка")
        await message.answer(f"🔗 {message.from_user.full_name} мут 1 час за ссылку.")
        return
    
    if message.text:
        words = re.findall(r'\b\w+\b', message.text.lower())
        for w in words:
            learn_word(w)
    if message.photo:
        add_meme_media(message.photo[-1].file_id, 'photo')
    elif message.video:
        add_meme_media(message.video.file_id, 'video')
    elif message.animation:
        add_meme_media(message.animation.file_id, 'gif')

# ---------- Reply-кнопки в личке ----------
@router.message(F.chat.type == 'private', F.text == "🛒 Магазин")
async def reply_shop(message: types.Message):
    await message.answer("🛒 Выберите услугу:", reply_markup=shop_menu())

@router.message(F.chat.type == 'private', F.text == "➕ Добавить в чат")
async def reply_add_to_chat(message: types.Message):
    bot_username = (await message.bot.get_me()).username
    url = f"https://t.me/{bot_username}?startgroup=start"
    await message.answer(f"Добавьте меня в чат по ссылке: {url}")

@router.message(F.chat.type == 'private', F.text == "💰 Баланс")
async def reply_balance(message: types.Message):
    coins = get_coins(message.from_user.id)
    await message.answer(f"💰 Ваш баланс: {coins} Дум.")

@router.message(F.chat.type == 'private', F.text == "❓ Поддержка")
async def reply_support(message: types.Message):
    await message.answer(f"Связь: {SUPPORT_LINK}")

@router.message(F.chat.type == 'private', F.text, ~F.text.startswith('/'))
async def private_text_handler(message: types.Message):
    if message.text in ("🛒 Магазин", "➕ Добавить в чат", "💰 Баланс", "❓ Поддержка"):
        return
    await message.answer("🤖 Пропиши /help для списка команд.")

# ---------- Обработка пересланных сообщений для снятия мута/варна ----------
@router.message(F.chat.type == 'private', F.forward_from_chat | F.text)
async def handle_pending_action(message: types.Message):
    user_id = message.from_user.id
    if user_id not in pending_actions:
        return
    action_data = pending_actions[user_id]
    chat_id = await extract_chat_id_from_message(message)
    if not chat_id:
        await message.answer("❌ Не удалось определить чат.")
        return
    if action_data['action'] == 'unmute':
        try:
            chat_member = await message.bot.get_chat_member(chat_id, user_id)
            if chat_member.status in ('left', 'kicked'):
                await message.answer("❌ Вы не участник этого чата.")
                return
        except Exception as e:
            await message.answer(f"❌ Ошибка: {e}")
            return
        unmute_user_in_chat(user_id, chat_id, user_id)
        await message.answer(f"✅ Мут снят в чате ID `{chat_id}`. Списано {action_data['cost']} Дум.")
    elif action_data['action'] == 'remove_warn':
        warns = get_warnings(user_id)
        if warns:
            remove_warning(warns[0][0])
            await message.answer(f"✅ Предупреждение снято. Списано {action_data['cost']} Дум.")
        else:
            await message.answer("⚠️ У вас нет предупреждений.")
    del pending_actions[user_id]

# ---------- Команды ----------
@router.message(Command("start"))
async def cmd_start(message: types.Message):
    if message.chat.type == 'private':
        await message.answer(
            f"Привет, {message.from_user.full_name}!\nЯ бот-модератор.\nНажми на кнопки внизу.",
            reply_markup=main_reply_keyboard()
        )
    else:
        await message.reply("Бот активен! Используйте команды в группе.")

@router.message(Command(commands=["help", "помощь", "команды"]))
async def cmd_help(message: types.Message):
    text = (
        "📚 **Команды:**\n\n"
        "💰 `/balance` `/мойдум` – баланс\n"
        "📊 `/top` `/топ` – топ активности\n"
        "🛒 `/shop` `/магазин` – магазин\n"
        "📈 `/stats` `/стата` – моя статистика\n"
        "🎲 `/doom` `/mem` `/rofl` `/мем` – мем\n"
        "🎮 `/duel` `/basketball` `/dice` – игры\n\n"
        "**Модерация (только в группах):**\n"
        "`/mute` `/мут` – мут\n"
        "`/unmute` `/размут` – снять мут\n"
        "`/ban` `/бан` – бан\n"
        "`/warn` `/варн` – предупреждение\n"
        "`/promote` `/повысить` – повысить роль\n"
        "`/demote` `/понизить` – понизить роль\n\n"
        "❓ `/help` – это сообщение"
    )
    await message.reply(text, parse_mode="Markdown")

@router.message(Command(commands=["top", "топ"]))
async def cmd_top(message: types.Message):
    if message.chat.type == 'private':
        await message.answer("ℹ️ Топ работает только в группе.")
        return
    top = get_top_users(5)
    if not top:
        await message.reply("Пока нет сообщений за сегодня.")
        return
    text = "📊 **Топ-5 за сегодня**\n\n"
    for i, (uid, name, count) in enumerate(top, 1):
        text += f"{i}. {name or f'[{uid}](tg://user?id={uid})'} — {count} сообщений\n"
    await message.reply(text, parse_mode="Markdown")

@router.message(Command(commands=["shop", "магазин"]))
async def cmd_shop(message: types.Message):
    await message.reply("🛒 Магазин услуг", reply_markup=shop_menu())

@router.message(Command(commands=["stats", "стата", "my_stats", "моястата"]))
async def cmd_my_stats(message: types.Message):
    user_id = message.from_user.id
    msgs, warns = get_user_stats(user_id)
    role = get_user(user_id)[3] if get_user(user_id) else 'Ньюген'
    text = f"📊 **Ваша статистика**\nРоль: {role}\nСообщений сегодня: {msgs}\nПредупреждений: {warns}"
    await message.reply(text, parse_mode="Markdown")

@router.message(Command(commands=["balance", "myduom", "мойдум"]))
async def cmd_balance(message: types.Message):
    coins = get_coins(message.from_user.id)
    await message.answer(f"💰 Ваш баланс: {coins} Дум.")

# ---------- Админские команды ----------
@router.message(Command(commands=["addcoins", "начислитьдумы"]))
async def cmd_addcoins(message: types.Message, bot: Bot):
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS and get_role_level(get_user(user_id)[3]) < get_role_level("Отец"):
        await message.reply("⛔ Нет прав.")
        return
    args = message.text.split(maxsplit=2)
    if message.chat.type == 'private':
        if len(args) == 2 and args[1].isdigit():
            add_coins(user_id, int(args[1]))
            await message.reply(f"✅ Вам начислено {args[1]} Дум.")
            return
        else:
            await message.reply("❌ В личке: `/addcoins 100`")
            return
    else:
        if len(args) < 3:
            await message.reply("❌ Использование: `/addcoins @username количество`")
            return
        target = args[1].lstrip('@')
        try:
            amount = int(args[2])
        except:
            await message.reply("❌ Количество должно быть числом.")
            return
        try:
            member = await bot.get_chat_member(message.chat.id, target)
            add_coins(member.user.id, amount)
            await message.reply(f"✅ @{target} начислено {amount} Дум.")
        except:
            await message.reply("❌ Пользователь не найден.")

# ---------- Мемы ----------
@router.message(Command(commands=["doom", "mem", "rofl", "мем"]))
async def cmd_meme(message: types.Message, bot: Bot):
    if message.chat.type == 'private':
        await message.answer("ℹ️ Мемы только в группах.")
        return
    user_id = message.from_user.id
    unlimited = has_unlimited_memes(user_id)
    if not unlimited:
        used = get_meme_limit_usage(user_id)
        if used >= 2:
            await message.reply("⚠️ Лимит 2 мема за 2 часа. Купи безлимит в `/shop`.")
            return
        add_meme_generation(user_id)
    word = get_random_learned_word()
    media = get_random_meme_media()
    if media:
        file_id, file_type = media
        if file_type == 'photo':
            await bot.send_photo(message.chat.id, file_id, caption=word or "Вот мем!")
        elif file_type == 'video':
            await bot.send_video(message.chat.id, file_id, caption=word or "Вот мем!")
        elif file_type == 'gif':
            await bot.send_animation(message.chat.id, file_id, caption=word or "Вот мем!")
        else:
            await message.reply(word or "Нет медиа.")
    else:
        await message.reply(word or "Нет материалов. Пишите слова и кидайте картинки!")

# ---------- Модерационные команды (только группы) ----------
def group_only(func):
    async def wrapper(message: types.Message, *args, **kwargs):
        if message.chat.type == 'private':
            await message.answer("❌ Команда только в группах.")
            return
        return await func(message, *args, **kwargs)
    return wrapper

@router.message(Command(commands=["mute", "мут"]))
@group_only
async def cmd_mute(message: types.Message, bot: Bot):
    if not await HasRole("Братик")(message):
        await message.reply("⛔ Недостаточно прав.")
        return
    args = message.text.split(maxsplit=3)
    if len(args) < 2:
        await message.reply("❌ Использование: `/mute @username [10m|1h|24h] [причина]`")
        return
    target = args[1].lstrip('@')
    dur = args[2] if len(args) > 2 else '10m'
    reason = args[3] if len(args) > 3 else ''
    try:
        member = await bot.get_chat_member(message.chat.id, target)
        target_id = member.user.id
    except:
        await message.reply("❌ Пользователь не найден.")
        return
    if not can_punish(message.from_user.id, target_id):
        await message.reply("❌ Нельзя наказать.")
        return
    m = re.match(r'(\d+)([mh])', dur)
    if not m:
        await message.reply("❌ Формат: 10m, 1h, 24h")
        return
    val, unit = m.groups()
    delta = timedelta(minutes=int(val)) if unit == 'm' else timedelta(hours=int(val))
    until = datetime.now() + delta
    mute_user_in_chat(target_id, message.chat.id, until, message.from_user.id, reason)
    await message.reply(f"✅ @{target} замьючен до {until.strftime('%H:%M %d.%m')}. Причина: {reason or 'не указана'}")

@router.message(Command(commands=["unmute", "размут"]))
@group_only
async def cmd_unmute(message: types.Message, bot: Bot):
    if not await HasRole("Братик")(message):
        await message.reply("⛔ Недостаточно прав.")
        return
    args = message.text.split()
    if len(args) < 2:
        await message.reply("❌ Использование: `/unmute @username`")
        return
    target = args[1].lstrip('@')
    try:
        member = await bot.get_chat_member(message.chat.id, target)
        target_id = member.user.id
    except:
        await message.reply("❌ Пользователь не найден.")
        return
    mod_level = get_role_level(get_user(message.from_user.id)[3])
    tgt_level = get_role_level(get_user(target_id)[3])
    if mod_level < tgt_level:
        await message.reply("❌ Нельзя снять мут.")
        return
    unmute_user_in_chat(target_id, message.chat.id, message.from_user.id)
    await message.reply(f"✅ Мут снят с @{target}.")

@router.message(Command(commands=["ban", "бан"]))
@group_only
async def cmd_ban(message: types.Message, bot: Bot):
    if not await HasRole("Отчим")(message):
        await message.reply("⛔ Недостаточно прав.")
        return
    args = message.text.split(maxsplit=2)
    if len(args) < 2:
        await message.reply("❌ Использование: `/ban @username [причина]`")
        return
    target = args[1].lstrip('@')
    reason = args[2] if len(args) > 2 else ''
    try:
        member = await bot.get_chat_member(message.chat.id, target)
        target_id = member.user.id
    except:
        await message.reply("❌ Пользователь не найден.")
        return
    if not can_punish(message.from_user.id, target_id):
        await message.reply("❌ Нельзя забанить.")
        return
    try:
        await bot.ban_chat_member(message.chat.id, target_id)
        ban_user(target_id, message.from_user.id, reason)
        await message.reply(f"🔨 @{target} забанен. Причина: {reason or 'не указана'}")
    except Exception as e:
        await message.reply(f"❌ Ошибка: {e}")

@router.message(Command(commands=["warn", "варн"]))
@group_only
async def cmd_warn(message: types.Message, bot: Bot):
    if not await HasRole("Братик")(message):
        await message.reply("⛔ Недостаточно прав.")
        return
    args = message.text.split(maxsplit=2)
    if len(args) < 2:
        await message.reply("❌ Использование: `/warn @username [причина]`")
        return
    target = args[1].lstrip('@')
    reason = args[2] if len(args) > 2 else ''
    try:
        member = await bot.get_chat_member(message.chat.id, target)
        target_id = member.user.id
    except:
        await message.reply("❌ Пользователь не найден.")
        return
    if not can_punish(message.from_user.id, target_id):
        await message.reply("❌ Нельзя выдать предупреждение.")
        return
    count = add_warning(target_id, message.from_user.id, reason)
    await message.reply(f"⚠️ @{target} предупреждение {count}/3. Причина: {reason or 'не указана'}")
    if count >= 3:
        try:
            await bot.ban_chat_member(message.chat.id, target_id)
            ban_user(target_id, message.from_user.id, "3 предупреждения")
            await message.reply(f"🔨 @{target} забанен за 3 предупреждения.")
        except Exception as e:
            await message.reply(f"❌ Ошибка: {e}")

@router.message(Command(commands=["promote", "повысить"]))
@group_only
async def cmd_promote(message: types.Message, bot: Bot):
    if not await HasRole("Отец")(message):
        await message.reply("⛔ Недостаточно прав.")
        return
    args = message.text.split(maxsplit=2)
    if len(args) < 2:
        await message.reply("❌ Использование: `/promote @username [роль]`")
        return
    target = args[1].lstrip('@')
    new_role = args[2] if len(args) > 2 else None
    try:
        member = await bot.get_chat_member(message.chat.id, target)
        target_id = member.user.id
    except:
        await message.reply("❌ Пользователь не найден.")
        return
    user_data = get_user(target_id)
    if not user_data:
        await message.reply("❌ Пользователь не в базе.")
        return
    current_role = user_data[3]
    if new_role:
        if new_role not in ROLE_HIERARCHY:
            await message.reply("❌ Неверная роль.")
            return
        if get_role_level(new_role) > get_role_level(current_role):
            update_user_role(target_id, new_role)
            await message.reply(f"✅ @{target} повышен до {new_role}.")
        else:
            await message.reply("❌ Новая роль должна быть выше текущей.")
    else:
        current_level = get_role_level(current_role)
        if current_level >= len(ROLE_HIERARCHY)-1:
            await message.reply("❌ Уже высшая роль.")
            return
        next_role = ROLE_HIERARCHY[current_level + 1]
        update_user_role(target_id, next_role)
        await message.reply(f"✅ @{target} повышен до {next_role}.")

@router.message(Command(commands=["demote", "понизить"]))
@group_only
async def cmd_demote(message: types.Message, bot: Bot):
    if not await HasRole("Отец")(message):
        await message.reply("⛔ Недостаточно прав.")
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("❌ Использование: `/demote @username`")
        return
    target = args[1].lstrip('@')
    try:
        member = await bot.get_chat_member(message.chat.id, target)
        target_id = member.user.id
    except:
        await message.reply("❌ Пользователь не найден.")
        return
    user_data = get_user(target_id)
    if not user_data:
        await message.reply("❌ Пользователь не в базе.")
        return
    current_role = user_data[3]
    current_level = get_role_level(current_role)
    if current_level <= 0:
        await message.reply("❌ Нельзя понизить ниже Ньюген.")
        return
    prev_role = ROLE_HIERARCHY[current_level - 1]
    update_user_role(target_id, prev_role)
    await message.reply(f"✅ @{target} понижен до {prev_role}.")

# ---------- Callback'и магазина ----------
@router.callback_query(F.data == "buy_unmute")
async def buy_unmute(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    cost = 100
    if remove_coins(user_id, cost):
        pending_actions[user_id] = {'action': 'unmute', 'cost': cost}
        await callback.message.answer("💰 Деньги списаны. Перешлите сообщение из чата для снятия мута.")
    else:
        await callback.message.answer(f"❌ Недостаточно Дум. Нужно {cost}, у вас {get_coins(user_id)}.")
    await callback.answer()

@router.callback_query(F.data == "buy_remove_warn")
async def buy_remove_warn(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    cost = 150
    if remove_coins(user_id, cost):
        pending_actions[user_id] = {'action': 'remove_warn', 'cost': cost}
        await callback.message.answer("💰 Деньги списаны. Перешлите сообщение из чата для снятия предупреждения.")
    else:
        await callback.message.answer(f"❌ Недостаточно Дум. Нужно {cost}, у вас {get_coins(user_id)}.")
    await callback.answer()

@router.callback_query(F.data == "buy_temp_fanat")
async def buy_temp_fanat(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    cost = 50
    if remove_coins(user_id, cost):
        update_user_role(user_id, 'Фанат', datetime.now() + timedelta(hours=24))
        await callback.message.answer(f"✅ Роль 'Фанат' на 24 часа! Списано {cost} Дум.")
    else:
        await callback.message.answer(f"❌ Недостаточно Дум. Нужно {cost}, у вас {get_coins(user_id)}.")
    await callback.answer()

@router.callback_query(F.data == "buy_unlimited_memes")
async def buy_unlimited_memes(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    cost = 250
    if remove_coins(user_id, cost):
        set_unlimited_memes(user_id, datetime.now() + timedelta(days=30))
        await callback.message.answer(f"✅ Безлимит мемов на месяц! Списано {cost} Дум.")
    else:
        await callback.message.answer(f"❌ Недостаточно Дум. Нужно {cost}, у вас {get_coins(user_id)}.")
    await callback.answer()

# ---------- Подключение мини-игр ----------
from games import router as games_router
router.include_router(games_router)
