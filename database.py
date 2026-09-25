import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def get_user(user_id: int):
    """Получает данные пользователя из базы данных Supabase."""
    try:
        response = supabase.table("users").select("*").eq("user_id", user_id).execute()
        if response.data:
            return response.data[0]
    except Exception as e:
        print(f"Ошибка получения пользователя: {e}")
    return None

def save_or_update_user(user_id: int, full_name: str, mode: str = None, city: str = None, streak: int = None, paused: bool = None, pause_reason: str = None):
    """Сохраняет или обновляет данные пользователя, не затирая существующие поля."""
    try:
        existing = get_user(user_id)
        if not existing:
            user_data = {
                "user_id": user_id,
                "full_name": full_name,
                "spiritual_mode": mode or "alfard",
                "city": city or "Не указан",
                "streak": streak or 1,
                "paused": False,
                "pause_reason": None,
                "prayers_pct": 94,
                "quran_days": 31,
                "azkar_days": 27,
                "salawat_days": 22
            }
        else:
            user_data = {
                "user_id": user_id,
                "full_name": full_name or existing.get("full_name"),
                "spiritual_mode": mode if mode is not None else existing.get("spiritual_mode", "alfard"),
                "city": city if city is not None else existing.get("city", "Не указан"),
                "streak": streak if streak is not None else existing.get("streak", 1),
                "paused": paused if paused is not None else existing.get("paused", False),
                "pause_reason": pause_reason if pause_reason is not None else existing.get("pause_reason")
            }
        supabase.table("users").upsert(user_data, on_conflict="user_id").execute()
    except Exception as e:
        print(f"Ошибка сохранения пользователя: {e}")
