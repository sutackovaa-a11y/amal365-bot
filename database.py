import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def save_or_update_user(telegram_id: int, full_name: str, city: str = None, mode: str = None):
    """Сохраняет или обновляет данные пользователя в таблице users"""
    data = {
        "telegram_id": telegram_id,
        "full_name": full_name,
    }
    if city:
        data["city"] = city
    if mode:
        data["spiritual_mode"] = mode

    response = supabase.table("users").upsert(data, on_conflict="telegram_id").execute()
    return response

def get_user(telegram_id: int):
    """Получает данные пользователя"""
    response = supabase.table("users").select("*").eq("telegram_id", telegram_id).execute()
    if response.data:
        return response.data[0]
    return None
