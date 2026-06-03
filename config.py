import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    raise ValueError('BOT_TOKEN не задан')

ADMIN_IDS = [int(x.strip()) for x in os.getenv('ADMIN_IDS', '').split(',') if x.strip()]
TIMEZONE = os.getenv('TIMEZONE', 'Europe/Moscow')
SUPPORT_LINK = os.getenv('SUPPORT_LINK', 'https://t.me/durov')