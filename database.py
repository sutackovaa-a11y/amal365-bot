import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Не найдены переменные окружения SUPABASE_URL или SUPABASE_KEY в файле .env")

# Инициализация клиента Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

async def get_or_create_user(telegram_id: int, username: str, first_name: str):
    """Проверяет наличие пользователя в таблице users, если нет — создает нового."""
    response = supabase.table("users").select("*").eq("telegram_id", telegram_id).execute()
    
    if response.data and len(response.data) > 0:
        return response.data[0]
    
    # Если пользователя нет в базе, регистрируем
    new_user = {
        "telegram_id": telegram_id,
        "username": username,
        "first_name": first_name,
        "streak_days": 0,
        "pause_mode": False,
        "language": "ru"
    }
    
    insert_response = supabase.table("users").insert(new_user).execute()
    return insert_response.data[0] if insert_response.data else None

async def update_user_city(telegram_id: int, city: str):
    """Обновляет город пользователя для расчета намазов."""
    response = supabase.table("users").update({"city": city}).eq("telegram_id", telegram_id).execute()
    return response.data
