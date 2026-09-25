import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def save_or_update_user(user_id: int, full_name: str, mode: str = None, city: str = None):
    """Сохраняет пользователя или обновляет конкретные поля (этап, город)."""
    try:
        response = supabase.table("users").select("*").eq("user_id", user_id).execute()
        
        if not response.data:
            user_data = {
                "user_id": user_id,
                "full_name": full_name,
                "spiritual_mode": mode or "alfard",
                "city": city or "Не указан",
                "streak": 1
            }
            supabase.table("users").insert(user_data).execute()
        else:
            update_data = {}
            if mode is not None:
                update_data["spiritual_mode"] = mode
            if city is not None:
                update_data["city"] = city
            if update_data:
                supabase.table("users").update(update_data).eq("user_id", user_id).execute()
    except Exception as e:
        print(f"Ошибка базы данных (save_or_update_user): {e}")

def get_user(user_id: int):
    """Получает данные пользователя из базы."""
    try:
        response = supabase.table("users").select("*").eq("user_id", user_id).execute()
        if response.data:
            return response.data[0]
    except Exception as e:
        print(f"Ошибка базы данных (get_user): {e}")
    return None
