import asyncio
import re
from datetime import datetime, timedelta
from aiogram import Router, types, F, Bot
from aiogram.filters import Command, ChatMemberUpdatedFilter, JOIN_TRANSITION
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from filters import HasRole, get_role_level, ROLE_HIERARCHY
from database import *
from config import ADMIN_IDS, SUPPORT_LINK
from keyboards import main_reply_keyboard, shop_menu
import utils

router = Router()

# ---------- Вспомогательная проверка прав на наказание ----------
def can_punish(moderator_id: int, target_id: int) -> bool:
    if moderator_id == target_id:
        return False
    mod_user = get_user(moderator_id)
    tgt_user = get_user(target_id)
    if not mod_user or not tgt_user:
        return False
    return get_role_level(mod_user[3]) > get_role_level(tgt_user[3])

# ---------- Обработчик добавления бота в чат: назначаем владельца чата Отцом ----------
async def get_chat_owner(bot: Bot, chat_id: int) -> int | None:
    try:
        admins = await bot.get_chat_administrators(chat_id)
        for admin in admins:
            if admin.status == "creator":
                return admin.user.id
    except Exception:
        pass
    return None

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
            await bot.send_message(owner_id, f"🏆 Вы назначены **Отцом** в чате `{chat_title}` как создатель чата.")
    await bot.send_message(chat_id, "✅ Бот добавлен! Выдайте ему права администратора для работы модерации.")

# ---------- Счётчик сообщений и авто-модерация (только в группах) ----------
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
        await message.answer(f"❌ {message.from_user.full_name}, вы в муте в этом чате.", delete_after=5)
        return
    create_user_if_not_exists(user_id, message.from_user.username, message.from_user.full_name)
    update_message_stats(user_id)
    
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
                mute_user_in_chat(user_id, chat_id, until, user_id, reason="Авто-флуд (10 сообщений подряд за 10 секунд)")
                await message.answer(f"⚠️ {message.from_user.full_name}, вы получили мут на 10 минут за флуд (10 сообщений подряд).")
                await message.delete()
                consecutive_tracker[chat_id]['count'] = 0
                return
        else:
            tracker['count'] = 1
            tracker['last_time'] = now
    
    if message.text and is_forbidden(message.text):
        await message.delete()
        warn_count = add_warning(user_id, 0, f"Запрещённое слово: {message.text[:50]}")
        await message.answer(f"🚫 {message.from_user.full_name}, запрещённое слово. Предупреждение {warn_count}/3.")
        if warn_count >= 3:
            ban_user(user_id, 0, "3 предупреждения (авто)")
            await message.answer(f"🔨 {message.from_user.full_name} забанен за 3 предупреждения.")
            try:
                await bot.ban_chat_member(chat_id, user_id)
            except: pass
        return
    
    if message.text and utils.contains_non_whitelisted_link(message.text):
        await message.delete()
        until = datetime.now() + timedelta(hours=1)
        mute_user_in_chat(user_id, chat_id, until, 0, reason="Ссылка на запрещённый ресурс")
        await message.answer(f"🔗 {message.from_user.full_name}, ссылки на другие каналы запрещены. Мут 1 час.")
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

# ---------- Обработчики Reply-кнопок (только в личных сообщениях) ----------
@router.message(F.chat.type == 'private', F.text == "🛒 Магазин")
async def reply_shop(message: types.Message):
    await message.answer("🛒 Выберите услугу:", reply_markup=shop_menu())

@router.message(F.chat.type == 'private', F.text == "➕ Добавить в чат")
async def reply_add_to_chat(message: types.Message):
    bot_username = (await message.bot.get_me()).username
    url = f"https://t.me/{bot_username}?startgroup=start"
    await message.answer(f"Добавьте меня в чат по ссылке: {url}")

@router.message(F.chat.type == 'private', F.text == "❓ Поддержка")
async def reply_support(message: types.Message):
    await message.answer(f"Связь с поддержкой: {SUPPORT_LINK}")

# ---------- Обработчик обычных сообщений в личке (без AI) ----------
@router.message(F.chat.type == 'private', F.text, ~F.text.startswith('/'))
async def private_text_handler(message: types.Message):
    # Игнорируем текст кнопок (на случай, если не сработал фильтр)
    if message.text in ("🛒 Магазин", "➕ Добавить в чат", "❓ Поддержка"):
        return
    await message.answer("🤖 Пропиши /help, чтобы узнать, что я умею.")

# ---------- Команды, работающие везде ----------
@router.message(Command("start"))
async def cmd_start(message: types.Message):
    if message.chat.type == 'private':
        await message.answer(
            f"Привет, {message.from_user.full_name}!\nЯ бот-модератор чата.\n\n"
            "Нажмите на кнопки внизу, чтобы управлять мной.",
            reply_markup=main_reply_keyboard()
        )
    else:
        await message.reply("Бот активен! Используйте команды в группе.")

@router.message(Command(commands=["help", "помощь"]))
async def cmd_help(message: types.Message):
    help_text = (
        "📚 **Доступные команды:**\n\n"
        "💰 `/balance` или `/myduom` – проверить баланс (Думы)\n"
        "🗑️ `/clear` – очистить историю диалога (только для AI, сейчас не используется)\n"
        "📊 `/top` – топ активных пользователей\n"
        "🛒 `/shop` – магазин услуг\n"
        "📈 `/stats` – ваша статистика\n"
        "🎲 `/doom`, `/mem`, `/rofl` – сгенерировать мем\n"
        "🎮 `/duel`, `/basketball`, `/dice` – мини-игры\n"
        "📊 `/game_stats` – статистика игр\n"
        "❓ `/help` – это сообщение\n\n"
        "ℹ️ Команды модерации работают только в группах."
    )
    await message.answer(help_text, parse_mode="Markdown")

@router.message(Command(commands=["clear", "очистить"]))
async def cmd_clear(message: types.Message):
    await message.answer("✅ Очистка истории не требуется (AI отключён).")

@router.message(Command(commands=["top", "топ"]))
async def cmd_top(message: types.Message):
    if message.chat.type == 'private':
        await message.answer("ℹ️ Топ активности доступен только в группе.")
        return
    top = get_top_users(5)
    if not top:
        await message.reply("Пока нет сообщений за сегодня.")
        return
    text = "📊 **Топ-5 активных пользователей за сегодня**\n\n"
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
    user_id = message.from_user.id
    coins = get_coins(user_id)
    await message.answer(f"💰 Ваш баланс: {coins} Дум.")

# ---------- Команды администратора для баланса ----------
@router.message(Command(commands=["addcoins", "начислитьдумы"]))
async def cmd_addcoins(message: types.Message, bot: Bot):
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS and get_role_level(get_user(user_id)[3]) < get_role_level("Отец"):
        await message.reply("⛔ У вас недостаточно прав.")
        return
    args = message.text.split(maxsplit=2)
    if message.chat.type == 'private':
        if len(args) == 2 and args[1].isdigit():
            amount = int(args[1])
            add_coins(message.from_user.id, amount)
            await message.reply(f"✅ Вам начислено {amount} Дум.")
            return
        else:
            await message.reply("❌ В личке используйте: `/addcoins 100`")
            return
    else:
        if len(args) < 3:
            await message.reply("❌ Использование: `/addcoins @username количество`")
            return
        target_username = args[1].lstrip('@')
        try:
            amount = int(args[2])
        except ValueError:
            await message.reply("❌ Количество должно быть числом.")
            return
        try:
            chat_member = await bot.get_chat_member(message.chat.id, target_username)
            target_id = chat_member.user.id
        except:
            await message.reply("❌ Пользователь не найден в этом чате.")
            return
        add_coins(target_id, amount)
        await message.reply(f"✅ Пользователю @{target_username} начислено {amount} Дум.")

@router.message(Command(commands=["removecoins", "отнятьдумы"]))
async def cmd_removecoins(message: types.Message, bot: Bot):
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS and get_role_level(get_user(user_id)[3]) < get_role_level("Отец"):
        await message.reply("⛔ У вас недостаточно прав.")
        return
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.reply("❌ Использование: `/removecoins @username количество`")
        return
    target_username = args[1].lstrip('@')
    try:
        amount = int(args[2])
    except ValueError:
        await message.reply("❌ Количество должно быть числом.")
        return
    try:
        chat_member = await bot.get_chat_member(message.chat.id, target_username)
        target_id = chat_member.user.id
    except:
        await message.reply("❌ Пользователь не найден в этом чате.")
        return
    current = get_coins(target_id)
    if current < amount:
        await message.reply(f"❌ У пользователя только {current} Дум.")
        return
    remove_coins(target_id, amount)
    await message.reply(f"✅ У пользователя @{target_username} отнято {amount} Дум.")

@router.message(Command(commands=["setcoins", "установитьдумы"]))
async def cmd_setcoins(message: types.Message, bot: Bot):
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS and get_role_level(get_user(user_id)[3]) < get_role_level("Отец"):
        await message.reply("⛔ У вас недостаточно прав.")
        return
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.reply("❌ Использование: `/setcoins @username количество`")
        return
    target_username = args[1].lstrip('@')
    try:
        amount = int(args[2])
    except ValueError:
        await message.reply("❌ Количество должно быть числом.")
        return
    try:
        chat_member = await bot.get_chat_member(message.chat.id, target_username)
        target_id = chat_member.user.id
    except:
        await message.reply("❌ Пользователь не найден в этом чате.")
        return
    set_coins(target_id, amount)
    await message.reply(f"✅ Баланс @{target_username} установлен на {amount} Дум.")

# ---------- Мемы ----------
@router.message(Command(commands=["doom", "mem", "rofl", "мем"]))
async def cmd_meme(message: types.Message, bot: Bot):
    if message.chat.type == 'private':
        await message.answer("ℹ️ Команда мема работает только в группе.")
        return
    user_id = message.from_user.id
    unlimited = has_unlimited_memes(user_id)
    if not unlimited:
        used = get_meme_limit_usage(user_id)
        if used >= 2:
            await message.reply("⚠️ Вы использовали лимит 2 мема за 2 часа. Купите безлимит в `/shop`.")
            return
        add_meme_generation(user_id)
    word = get_random_learned_word()
    media = get_random_meme_media()
    if media:
        file_id, file_type = media
        if file_type == 'photo':
            await bot.send_photo(message.chat.id, file_id, caption=word or "Вот ваш мем!")
        elif file_type == 'video':
            await bot.send_video(message.chat.id, file_id, caption=word or "Вот ваш мем!")
        elif file_type == 'gif':
            await bot.send_animation(message.chat.id, file_id, caption=word or "Вот ваш мем!")
        else:
            await message.reply(word or "Ничего не нашлось для мема :(")
    else:
        await message.reply(word or "Пока нет материалов для мема. Пишите больше слов и кидайте картинки!")

# ---------- Команды модерации (только в группах) ----------
def group_only(func):
    async def wrapper(message: types.Message, *args, **kwargs):
        if message.chat.type == 'private':
            await message.answer("❌ Эта команда работает только в группах.")
            return
        return await func(message, *args, **kwargs)
    return wrapper

@router.message(Command(commands=["mute", "мут"]))
@group_only
async def cmd_mute(message: types.Message, bot: Bot):
    if not await HasRole("Братик")(message):
        await message.reply("⛔ У вас недостаточно прав для выполнения этой команды.")
        return
    args = message.text.split(maxsplit=3)
    if len(args) < 2:
        await message.reply("❌ Использование: `/mute @username [10m|1h|24h] [причина]`", parse_mode="Markdown")
        return
    target_username = args[1].lstrip('@')
    duration_str = args[2] if len(args) > 2 else '10m'
    reason = args[3] if len(args) > 3 else ''
    try:
        chat_member = await bot.get_chat_member(message.chat.id, target_username)
        target_id = chat_member.user.id
    except:
        await message.reply("❌ Пользователь не найден в чате.")
        return
    if not can_punish(message.from_user.id, target_id):
        await message.reply("❌ Вы не можете наказать этого пользователя (недостаточно прав).")
        return
    match = re.match(r'(\d+)([mh])', duration_str)
    if not match:
        await message.reply("❌ Неверный формат времени. Используйте 10m, 1h, 24h.")
        return
    value, unit = match.groups()
    value = int(value)
    delta = timedelta(minutes=value) if unit == 'm' else timedelta(hours=value)
    until = datetime.now() + delta
    mute_user_in_chat(target_id, message.chat.id, until, message.from_user.id, reason)
    await message.reply(f"✅ @{target_username} замьючен в этом чате до {until.strftime('%Y-%m-%d %H:%M')}. Причина: {reason or 'не указана'}")
    try:
        await bot.send_message(target_id, f"⚠️ Вы получили мут в чате {message.chat.title} до {until.strftime('%Y-%m-%d %H:%M')} по причине: {reason or 'не указана'}")
    except:
        pass

@router.message(Command(commands=["unmute", "размут"]))
@group_only
async def cmd_unmute(message: types.Message, bot: Bot):
    if not await HasRole("Братик")(message):
        await message.reply("⛔ У вас недостаточно прав для выполнения этой команды.")
        return
    args = message.text.split()
    if len(args) < 2:
        await message.reply("❌ Использование: `/unmute @username`", parse_mode="Markdown")
        return
    target_username = args[1].lstrip('@')
    try:
        chat_member = await bot.get_chat_member(message.chat.id, target_username)
        target_id = chat_member.user.id
    except:
        await message.reply("❌ Пользователь не найден.")
        return
    mod_level = get_role_level(get_user(message.from_user.id)[3])
    tgt_level = get_role_level(get_user(target_id)[3])
    if mod_level < tgt_level:
        await message.reply("❌ Вы не можете снять мут с пользователя с более высокой ролью.")
        return
    unmute_user_in_chat(target_id, message.chat.id, message.from_user.id)
    await message.reply(f"✅ Мут снят с @{target_username} в этом чате.")
    try:
        await bot.send_message(target_id, f"✅ С вас снят мут в чате {message.chat.title}.")
    except:
        pass

@router.message(Command(commands=["ban", "бан"]))
@group_only
async def cmd_ban(message: types.Message, bot: Bot):
    if not await HasRole("Отчим")(message):
        await message.reply("⛔ У вас недостаточно прав для выполнения этой команды.")
        return
    args = message.text.split(maxsplit=2)
    if len(args) < 2:
        await message.reply("❌ Использование: `/ban @username [причина]`", parse_mode="Markdown")
        return
    target_username = args[1].lstrip('@')
    reason = args[2] if len(args) > 2 else ''
    try:
        chat_member = await bot.get_chat_member(message.chat.id, target_username)
        target_id = chat_member.user.id
    except:
        await message.reply("❌ Пользователь не найден.")
        return
    if not can_punish(message.from_user.id, target_id):
        await message.reply("❌ Вы не можете наказать этого пользователя (недостаточно прав).")
        return
    try:
        await bot.ban_chat_member(message.chat.id, target_id)
        ban_user(target_id, message.from_user.id, reason)
        await message.reply(f"🔨 @{target_username} забанен. Причина: {reason or 'не указана'}")
        try:
            await bot.send_message(target_id, f"⚠️ Вы были забанены в чате {message.chat.title}. Причина: {reason or 'не указана'}")
        except: pass
    except Exception as e:
        await message.reply(f"❌ Не удалось забанить: {e}")

@router.message(Command(commands=["warn", "варн"]))
@group_only
async def cmd_warn(message: types.Message, bot: Bot):
    if not await HasRole("Братик")(message):
        await message.reply("⛔ У вас недостаточно прав для выполнения этой команды.")
        return
    args = message.text.split(maxsplit=2)
    if len(args) < 2:
        await message.reply("❌ Использование: `/warn @username [причина]`", parse_mode="Markdown")
        return
    target_username = args[1].lstrip('@')
    reason = args[2] if len(args) > 2 else ''
    try:
        chat_member = await bot.get_chat_member(message.chat.id, target_username)
        target_id = chat_member.user.id
    except:
        await message.reply("❌ Пользователь не найден.")
        return
    if not can_punish(message.from_user.id, target_id):
        await message.reply("❌ Вы не можете наказать этого пользователя (недостаточно прав).")
        return
    count = add_warning(target_id, message.from_user.id, reason)
    await message.reply(f"⚠️ @{target_username} получил предупреждение ({count}/3). Причина: {reason or 'не указана'}")
    if count >= 3:
        try:
            await bot.ban_chat_member(message.chat.id, target_id)
            ban_user(target_id, message.from_user.id, "3 предупреждения")
            await message.reply(f"🔨 @{target_username} забанен автоматически (3 предупреждения).")
        except Exception as e:
            await message.reply(f"❌ Не удалось забанить после 3 варнов: {e}")

@router.message(Command(commands=["warns", "варны"]))
@group_only
async def cmd_warns(message: types.Message):
    if not await HasRole("Братик")(message):
        await message.reply("⛔ У вас недостаточно прав для выполнения этой команды.")
        return
    args = message.text.split()
    if len(args) < 2:
        await message.reply("❌ Использование: `/warns @username`", parse_mode="Markdown")
        return
    target_username = args[1].lstrip('@')
    await message.reply("ℹ️ Команда временно недоступна. Используйте `/warn` для выдачи предупреждений.")

@router.message(Command(commands=["promote", "повысить"]))
@group_only
async def cmd_promote(message: types.Message, bot: Bot):
    if not await HasRole("Отец")(message):
        await message.reply("⛔ У вас недостаточно прав для выполнения этой команды.")
        return
    args = message.text.split(maxsplit=2)
    if len(args) < 2:
        await message.reply("❌ Использование: `/promote @username [роль]`\nРоли: Ньюген, Фанат, Братик, Отчим, Отец")
        return
    target_username = args[1].lstrip('@')
    new_role = args[2] if len(args) > 2 else None
    try:
        chat_member = await bot.get_chat_member(message.chat.id, target_username)
        target_id = chat_member.user.id
    except:
        await message.reply("❌ Пользователь не найден в чате.")
        return
    user_data = get_user(target_id)
    if not user_data:
        await message.reply("❌ Пользователь не зарегистрирован в базе.")
        return
    current_role = user_data[3]
    if new_role:
        if new_role not in ROLE_HIERARCHY:
            await message.reply("❌ Неверная роль. Доступны: " + ", ".join(ROLE_HIERARCHY))
            return
        target_level = get_role_level(new_role)
        if target_level > get_role_level(current_role):
            update_user_role(target_id, new_role)
            await message.reply(f"✅ Пользователь @{target_username} повышен до роли {new_role}.")
        else:
            await message.reply("❌ Новая роль должна быть выше текущей.")
    else:
        current_level = get_role_level(current_role)
        if current_level >= len(ROLE_HIERARCHY)-1:
            await message.reply("❌ Пользователь уже имеет высшую роль.")
            return
        next_role = ROLE_HIERARCHY[current_level + 1]
        update_user_role(target_id, next_role)
        await message.reply(f"✅ Пользователь @{target_username} повышен до роли {next_role}.")

@router.message(Command(commands=["demote", "понизить"]))
@group_only
async def cmd_demote(message: types.Message, bot: Bot):
    if not await HasRole("Отец")(message):
        await message.reply("⛔ У вас недостаточно прав для выполнения этой команды.")
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("❌ Использование: `/demote @username`")
        return
    target_username = args[1].lstrip('@')
    try:
        chat_member = await bot.get_chat_member(message.chat.id, target_username)
        target_id = chat_member.user.id
    except:
        await message.reply("❌ Пользователь не найден в чате.")
        return
    user_data = get_user(target_id)
    if not user_data:
        await message.reply("❌ Пользователь не зарегистрирован в базе.")
        return
    current_role = user_data[3]
    current_level = get_role_level(current_role)
    if current_level <= 0:
        await message.reply("❌ Нельзя понизить пользователя ниже роли Ньюген.")
        return
    prev_role = ROLE_HIERARCHY[current_level - 1]
    update_user_role(target_id, prev_role)
    await message.reply(f"✅ Пользователь @{target_username} понижен до роли {prev_role}.")

@router.message(Command(commands=["statsbot", "статистикаббота"]))
async def cmd_statsbot(message: types.Message, bot: Bot):
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS and get_role_level(get_user(user_id)[3]) < get_role_level("Отец"):
        await message.answer("⛔ Нет прав для просмотра статистики бота.")
        return
    stats = get_mod_stats()
    chats = get_bot_chats()
    report = (
        f"📊 **Статистика бота**\n\n"
        f"• Всего участников в базе: {stats['total_users']}\n"
        f"• Активных сегодня: {stats['active_today']}\n"
        f"• Муты за неделю: {stats['mutes_week']}\n"
        f"• Баны за неделю: {stats['bans_week']}\n"
        f"• Собрано медиа: {stats['media_count']}\n"
        f"• Запомнено слов: {stats['words_count']}\n"
        f"• Добавлен в чатов: {len(chats)}\n"
    )
    await bot.send_message(user_id, report, parse_mode="Markdown")
    if message.chat.type != 'private':
        await message.reply("✅ Статистика отправлена в личку.")

# ---------- Обработчики покупок (callback) ----------
@router.callback_query(F.data == "buy_unmute")
async def buy_unmute(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    cost = 100
    if remove_coins(user_id, cost):
        await callback.message.answer("⚠️ Эта услуга требует указания чата. Используйте команду `/unmute` после оплаты.")
    else:
        await callback.message.answer(f"❌ Недостаточно Дум. Нужно {cost}, у вас {get_coins(user_id)}.")
    await callback.answer()

@router.callback_query(F.data == "buy_remove_warn")
async def buy_remove_warn(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    cost = 150
    if remove_coins(user_id, cost):
        warns = get_warnings(user_id)
        if warns:
            remove_warning(warns[0][0])
            await callback.message.answer(f"✅ Предупреждение снято! Списано {cost} Дум.")
        else:
            await callback.message.answer("⚠️ У вас нет предупреждений.")
    else:
        await callback.message.answer(f"❌ Недостаточно Дум. Нужно {cost}, у вас {get_coins(user_id)}.")
    await callback.answer()

@router.callback_query(F.data == "buy_temp_fanat")
async def buy_temp_fanat(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    cost = 50
    if remove_coins(user_id, cost):
        update_user_role(user_id, 'Фанат', datetime.now() + timedelta(hours=24))
        await callback.message.answer(f"✅ Роль 'Фанат' выдана на 24 часа! Списано {cost} Дум.")
    else:
        await callback.message.answer(f"❌ Недостаточно Дум. Нужно {cost}, у вас {get_coins(user_id)}.")
    await callback.answer()

@router.callback_query(F.data == "buy_unlimited_memes")
async def buy_unlimited_memes(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    cost = 250
    if remove_coins(user_id, cost):
        set_unlimited_memes(user_id, datetime.now() + timedelta(days=30))
        await callback.message.answer(f"✅ Безлимит мемов активирован на месяц! Списано {cost} Дум.")
    else:
        await callback.message.answer(f"❌ Недостаточно Дум. Нужно {cost}, у вас {get_coins(user_id)}.")
    await callback.answer()

@router.callback_query(F.data == "buy_learn_word")
async def buy_learn_word(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    cost = 10
    if remove_coins(user_id, cost):
        await callback.message.answer("✍️ Отправьте слово, которое хотите добавить в память бота.")
    else:
        await callback.message.answer(f"❌ Недостаточно Дум. Нужно {cost}, у вас {get_coins(user_id)}.")
    await callback.answer()

# ---------- Подключение мини-игр ----------
from games import router as games_router
router.include_router(games_router)
