from aiogram import Router, types
from aiogram.filters import Command

router = Router()

@router.message(Command("start"))
async def start_cmd(message: types.Message):
    await message.answer("✅ Бот работает!")

@router.message(Command("help"))
async def help_cmd(message: types.Message):
    await message.answer("✅ Команда help получена!")
