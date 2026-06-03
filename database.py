import sqlite3
import os
from datetime import datetime, timedelta
from typing import List, Tuple, Optional
import re

DB_PATH = os.getenv('DATA_DIR', '/app/data') + '/moderator.db'

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Пользователи
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        full_name TEXT,
        role TEXT DEFAULT 'Ньюген',
        message_count INTEGER DEFAULT 0,
        last_message_date TEXT,
        is_banned INTEGER DEFAULT 0,
        temp_role_expires TEXT,
        unlimited_memes_until TEXT,
        coins INTEGER DEFAULT 0
    )''')
    
    # Предупреждения
    c.execute('''CREATE TABLE IF NOT EXISTS warnings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        moderator_id INTEGER,
        reason TEXT,
        created_at TEXT
    )''')
    
    # Лог действий модераторов
    c.execute('''CREATE TABLE IF NOT EXISTS mod_actions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        moderator_id INTEGER,
        action_type TEXT,
        target_id INTEGER,
        reason TEXT,
        duration TEXT,
        created_at TEXT
    )''')
    
    # Запрещённые слова
    c.execute('''CREATE TABLE IF NOT EXISTS banned_words (
        word TEXT PRIMARY KEY
    )''')
    
    # Белый список доменов
    c.execute('''CREATE TABLE IF NOT EXISTS whitelist_links (
        domain TEXT PRIMARY KEY
    )''')
    default_domains = ['youtube.com', 'youtu.be', 'tiktok.com', 'instagram.com', 't.me']
    for dom in default_domains:
        c.execute('INSERT OR IGNORE INTO whitelist_links (domain) VALUES (?)', (dom,))
    
    # Запоминающиеся слова
    c.execute('''CREATE TABLE IF NOT EXISTS learned_words (
        word TEXT PRIMARY KEY,
        count INTEGER DEFAULT 1,
        last_seen TEXT
    )''')
    
    # Медиа для мемов
    c.execute('''CREATE TABLE IF NOT EXISTS memes_media (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_id TEXT NOT NULL,
        file_type TEXT,
        created_at TEXT
    )''')
    
    # Платные услуги (для истории)
    c.execute('''CREATE TABLE IF NOT EXISTS paid_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        service_type TEXT,
        amount_stars INTEGER,
        coins_spent INTEGER,
        created_at TEXT,
        expires_at TEXT
    )''')
    
    # Чаты, куда добавлен бот
    c.execute('''CREATE TABLE IF NOT EXISTS bot_chats (
        chat_id INTEGER PRIMARY KEY,
        chat_title TEXT,
        added_at TEXT
    )''')
    
    # Мут по чатам
    c.execute('''CREATE TABLE IF NOT EXISTS chat_mutes (
        user_id INTEGER,
        chat_id INTEGER,
        muted_until TEXT,
        PRIMARY KEY (user_id, chat_id)
    )''')
    
    # Игровая статистика
    c.execute('''CREATE TABLE IF NOT EXISTS game_stats (
        user_id INTEGER PRIMARY KEY,
        duels_won INTEGER DEFAULT 0,
        duels_lost INTEGER DEFAULT 0,
        basketball_won INTEGER DEFAULT 0,
        basketball_lost INTEGER DEFAULT 0,
        dice_won INTEGER DEFAULT 0,
        dice_lost INTEGER DEFAULT 0
    )''')
    
    # Добавляем столбец coins, если его нет (для старых баз)
    try:
        c.execute("ALTER TABLE users ADD COLUMN coins INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    
    conn.commit()
    conn.close()

# ---------- users ----------
def get_user(user_id: int) -> Optional[Tuple]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    user = c.fetchone()
    conn.close()
    return user

def create_user_if_not_exists(user_id: int, username: str, full_name: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO users (user_id, username, full_name, last_message_date, message_count) VALUES (?, ?, ?, ?, 0)',
              (user_id, username, full_name, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def update_user_role(user_id: int, role: str, expires: datetime = None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if expires:
        c.execute('UPDATE users SET role = ?, temp_role_expires = ? WHERE user_id = ?', (role, expires.isoformat(), user_id))
    else:
        c.execute('UPDATE users SET role = ?, temp_role_expires = NULL WHERE user_id = ?', (role, user_id))
    conn.commit()
    conn.close()

def update_message_stats(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now()
    today_str = now.date().isoformat()
    c.execute('SELECT message_count, last_message_date FROM users WHERE user_id = ?', (user_id,))
    row = c.fetchone()
    if row:
        count, last_date = row
        if last_date is None or last_date.split('T')[0] != today_str:
            count = 1
        else:
            count += 1
        c.execute('UPDATE users SET message_count = ?, last_message_date = ? WHERE user_id = ?',
                  (count, now.isoformat(), user_id))
    else:
        create_user_if_not_exists(user_id, '', '')
        c.execute('UPDATE users SET message_count = 1, last_message_date = ? WHERE user_id = ?',
                  (now.isoformat(), user_id))
    conn.commit()
    conn.close()

def get_top_users(limit=5):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    today = datetime.now().date().isoformat()
    c.execute('SELECT user_id, full_name, message_count FROM users WHERE last_message_date LIKE ? ORDER BY message_count DESC LIMIT ?', (today + '%', limit))
    top = c.fetchall()
    conn.close()
    return top

def get_user_stats(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    today = datetime.now().date().isoformat()
    c.execute('SELECT message_count FROM users WHERE user_id = ? AND last_message_date LIKE ?', (user_id, today + '%'))
    row = c.fetchone()
    messages = row[0] if row else 0
    c.execute('SELECT COUNT(*) FROM warnings WHERE user_id = ?', (user_id,))
    warns = c.fetchone()[0]
    conn.close()
    return messages, warns

# ---------- монеты (Думы) ----------
def get_coins(user_id: int) -> int:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT coins FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0

def add_coins(user_id: int, amount: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()

def remove_coins(user_id: int, amount: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT coins FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    if not row or row[0] < amount:
        conn.close()
        return False
    c.execute("UPDATE users SET coins = coins - ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()
    return True

def set_coins(user_id: int, amount: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET coins = ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()

# ---------- бан ----------
def ban_user(user_id: int, moderator_id: int, reason: str = ''):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE users SET is_banned = 1 WHERE user_id = ?', (user_id,))
    conn.commit()
    log_action(moderator_id, 'ban', user_id, reason, '')
    conn.close()

def unban_user(user_id: int, moderator_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE users SET is_banned = 0 WHERE user_id = ?', (user_id,))
    conn.commit()
    log_action(moderator_id, 'unban', user_id, '', '')
    conn.close()

def is_banned(user_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT is_banned FROM users WHERE user_id = ?', (user_id,))
    row = c.fetchone()
    banned = row and row[0] == 1
    conn.close()
    return banned

# ---------- мут по чатам ----------
def mute_user_in_chat(user_id: int, chat_id: int, until: datetime, moderator_id: int, reason: str = ''):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO chat_mutes (user_id, chat_id, muted_until) VALUES (?, ?, ?)',
              (user_id, chat_id, until.isoformat()))
    conn.commit()
    log_action(moderator_id, f'mute_chat_{chat_id}', user_id, reason, until.isoformat())
    conn.close()

def unmute_user_in_chat(user_id: int, chat_id: int, moderator_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('DELETE FROM chat_mutes WHERE user_id = ? AND chat_id = ?', (user_id, chat_id))
    conn.commit()
    log_action(moderator_id, f'unmute_chat_{chat_id}', user_id, '', '')
    conn.close()

def is_muted_in_chat(user_id: int, chat_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT muted_until FROM chat_mutes WHERE user_id = ? AND chat_id = ?', (user_id, chat_id))
    row = c.fetchone()
    if row and row[0]:
        until = datetime.fromisoformat(row[0])
        if until > datetime.now():
            conn.close()
            return True
        else:
            c.execute('DELETE FROM chat_mutes WHERE user_id = ? AND chat_id = ?', (user_id, chat_id))
            conn.commit()
    conn.close()
    return False

# ---------- предупреждения ----------
def add_warning(user_id: int, moderator_id: int, reason: str) -> int:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('INSERT INTO warnings (user_id, moderator_id, reason, created_at) VALUES (?, ?, ?, ?)',
              (user_id, moderator_id, reason, datetime.now().isoformat()))
    conn.commit()
    c.execute('SELECT COUNT(*) FROM warnings WHERE user_id = ?', (user_id,))
    count = c.fetchone()[0]
    conn.close()
    return count

def get_warnings(user_id: int) -> List[Tuple]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT id, moderator_id, reason, created_at FROM warnings WHERE user_id = ? ORDER BY created_at', (user_id,))
    warns = c.fetchall()
    conn.close()
    return warns

def remove_warning(warning_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('DELETE FROM warnings WHERE id = ?', (warning_id,))
    conn.commit()
    conn.close()

# ---------- лог действий ----------
def log_action(moderator_id: int, action: str, target_id: int, reason: str, duration: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('INSERT INTO mod_actions (moderator_id, action_type, target_id, reason, duration, created_at) VALUES (?, ?, ?, ?, ?, ?)',
              (moderator_id, action, target_id, reason, duration, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_mod_stats():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM users')
    total_users = c.fetchone()[0]
    today = datetime.now().date().isoformat()
    c.execute('SELECT COUNT(*) FROM users WHERE last_message_date LIKE ?', (today + '%',))
    active_today = c.fetchone()[0]
    week_ago = (datetime.now() - timedelta(days=7)).isoformat()
    c.execute('SELECT COUNT(*) FROM mod_actions WHERE action_type = "mute" AND created_at > ?', (week_ago,))
    mutes_week = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM mod_actions WHERE action_type = "ban" AND created_at > ?', (week_ago,))
    bans_week = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM memes_media')
    media_count = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM learned_words')
    words_count = c.fetchone()[0]
    conn.close()
    return {'total_users': total_users, 'active_today': active_today, 'mutes_week': mutes_week, 'bans_week': bans_week, 'media_count': media_count, 'words_count': words_count}

# ---------- фильтр слов ----------
def add_banned_word(word: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO banned_words (word) VALUES (?)', (word.lower(),))
    conn.commit()
    conn.close()

def remove_banned_word(word: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('DELETE FROM banned_words WHERE word = ?', (word.lower(),))
    conn.commit()
    conn.close()

def get_banned_words() -> List[str]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT word FROM banned_words')
    return [row[0] for row in c.fetchall()]

def is_forbidden(text: str) -> bool:
    if not text:
        return False
    text_lower = text.lower()
    for word in get_banned_words():
        if word in text_lower:
            return True
    return False

# ---------- белый список доменов ----------
def add_whitelist_domain(domain: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO whitelist_links (domain) VALUES (?)', (domain.lower(),))
    conn.commit()
    conn.close()

def remove_whitelist_domain(domain: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('DELETE FROM whitelist_links WHERE domain = ?', (domain.lower(),))
    conn.commit()
    conn.close()

def get_whitelist_domains() -> List[str]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT domain FROM whitelist_links')
    return [row[0] for row in c.fetchall()]

# ---------- запоминание слов ----------
def learn_word(word: str):
    word_clean = re.sub(r'[^\wа-яё]', '', word.lower())
    if len(word_clean) < 3:
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT count, last_seen FROM learned_words WHERE word = ?', (word_clean,))
    row = c.fetchone()
    now = datetime.now().isoformat()
    if row:
        c.execute('UPDATE learned_words SET count = ?, last_seen = ? WHERE word = ?', (row[0]+1, now, word_clean))
    else:
        c.execute('INSERT INTO learned_words (word, count, last_seen) VALUES (?, ?, ?)', (word_clean, 1, now))
    conn.commit()
    conn.close()

def get_random_learned_word() -> Optional[str]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT word FROM learned_words ORDER BY RANDOM() LIMIT 1')
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

# ---------- медиа для мемов ----------
def add_meme_media(file_id: str, file_type: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM memes_media')
    count = c.fetchone()[0]
    if count >= 500:
        c.execute('DELETE FROM memes_media WHERE id IN (SELECT id FROM memes_media ORDER BY created_at LIMIT ?)', (count - 499,))
    c.execute('INSERT INTO memes_media (file_id, file_type, created_at) VALUES (?, ?, ?)',
              (file_id, file_type, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_random_meme_media() -> Optional[Tuple[str, str]]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT file_id, file_type FROM memes_media ORDER BY RANDOM() LIMIT 1')
    row = c.fetchone()
    conn.close()
    return row if row else None

# ---------- платные услуги ----------
def get_meme_limit_usage(user_id: int) -> int:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    two_hours_ago = (datetime.now() - timedelta(hours=2)).isoformat()
    c.execute('SELECT COUNT(*) FROM paid_orders WHERE user_id = ? AND service_type = "meme_generate" AND created_at > ?', (user_id, two_hours_ago))
    count = c.fetchone()[0]
    conn.close()
    return count

def add_meme_generation(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('INSERT INTO paid_orders (user_id, service_type, amount_stars, created_at) VALUES (?, ?, ?, ?)',
              (user_id, 'meme_generate', 0, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def has_unlimited_memes(user_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT unlimited_memes_until FROM users WHERE user_id = ?', (user_id,))
    row = c.fetchone()
    if row and row[0] and datetime.fromisoformat(row[0]) > datetime.now():
        conn.close()
        return True
    else:
        if row and row[0]:
            c.execute('UPDATE users SET unlimited_memes_until = NULL WHERE user_id = ?', (user_id,))
            conn.commit()
    conn.close()
    return False

def set_unlimited_memes(user_id: int, expires: datetime):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE users SET unlimited_memes_until = ? WHERE user_id = ?', (expires.isoformat(), user_id))
    conn.commit()
    conn.close()

def purchase_service(user_id: int, service: str, stars: int, duration_hours: int = None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    expires = None
    if duration_hours:
        expires = (datetime.now() + timedelta(hours=duration_hours)).isoformat()
    c.execute('INSERT INTO paid_orders (user_id, service_type, amount_stars, created_at, expires_at) VALUES (?, ?, ?, ?, ?)',
              (user_id, service, stars, datetime.now().isoformat(), expires))
    conn.commit()
    conn.close()
    if service == 'unmute':
        # нужно знать chat_id, но в этой функции нет; в реальности эта покупка через callback, там можно передать chat_id
        pass
    elif service == 'remove_warn':
        warns = get_warnings(user_id)
        if warns:
            remove_warning(warns[0][0])
    elif service == 'temp_role_fanat':
        update_user_role(user_id, 'Фанат', datetime.now() + timedelta(hours=24))
    elif service == 'unlimited_memes':
        set_unlimited_memes(user_id, datetime.now() + timedelta(days=30))

# ---------- статистика бота ----------
def add_bot_chat(chat_id: int, chat_title: str = None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO bot_chats (chat_id, chat_title, added_at) VALUES (?, ?, ?)',
              (chat_id, chat_title, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_bot_chats() -> List[Tuple[int, str]]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT chat_id, chat_title FROM bot_chats')
    chats = c.fetchall()
    conn.close()
    return chats

# ---------- игровая статистика ----------
def get_game_stats(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT * FROM game_stats WHERE user_id = ?', (user_id,))
    row = c.fetchone()
    if not row:
        c.execute('INSERT INTO game_stats (user_id) VALUES (?)', (user_id,))
        conn.commit()
        c.execute('SELECT * FROM game_stats WHERE user_id = ?', (user_id,))
        row = c.fetchone()
    conn.close()
    return row  # (user_id, duels_won, duels_lost, basketball_won, basketball_lost, dice_won, dice_lost)

def update_game_stats(user_id: int, game: str, result: str):
    field_won = f"{game}_won"
    field_lost = f"{game}_lost"
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if result == 'win':
        c.execute(f'UPDATE game_stats SET {field_won} = {field_won} + 1 WHERE user_id = ?', (user_id,))
    else:
        c.execute(f'UPDATE game_stats SET {field_lost} = {field_lost} + 1 WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()