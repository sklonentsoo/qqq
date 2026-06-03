import asyncio
import logging
from aiogram import Bot, Dispatcher
from config import BOT_TOKEN
from database import init_db
from handlers import router

logging.basicConfig(level=logging.INFO)

async def main():
    # Инициализируем базу данных (создаёт таблицы, если их нет)
    init_db()
    
    # Создаём бота и диспетчер
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    
    # Подключаем все обработчики команд (из handlers.py, включая игры)
    dp.include_router(router)
    
    # Удаляем вебхук (на случай, если он был установлен) и запускаем long polling
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())