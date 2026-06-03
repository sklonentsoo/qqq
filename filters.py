from aiogram.filters import BaseFilter
from aiogram.types import Message
from database import get_user
from config import ADMIN_IDS

ROLE_HIERARCHY = ['Ньюген', 'Фанат', 'Братик', 'Отчим', 'Отец']

def get_role_level(role: str) -> int:
    return ROLE_HIERARCHY.index(role) if role in ROLE_HIERARCHY else 0

class HasRole(BaseFilter):
    def __init__(self, min_role: str):
        self.min_role = min_role
        self.min_level = get_role_level(min_role)
    
    async def __call__(self, message: Message) -> bool:
        user_id = message.from_user.id
        if user_id in ADMIN_IDS:
            return True
        user = get_user(user_id)
        if not user:
            return False
        return get_role_level(user[3]) >= self.min_level