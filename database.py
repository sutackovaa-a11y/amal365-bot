# database.py
import os
from supabase import create_client, Client
from dotenv import load_dotenv
from datetime import datetime, timezone

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Supabase URL and Key must be set in environment variables.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def create_user(telegram_id: int, username: str = None, first_name: str = None):
    try:
        existing = get_user(telegram_id)
        if not existing:
            user_data = {
                "telegram_id": telegram_id,
                "username": username,
                "first_name": first_name,
                "language": "ru",
                "city": "Москва",
                "mode": "alfard",
                "current_level": "alfard",
                "streak_days": 1,
                "pause_mode": False,
                "pause_reason": None,
                "fajr_done": False,
                "dhuhr_done": False,
                "asr_done": False,
                "maghrib_done": False,
                "isha_done": False,
                "tahajjud_done": False,
                "morning_adhkar_done": False,
                "evening_adhkar_done": False,
                "tasbih_count": 0,
                "quran_pages": 0,
                "books_pages": 0,
                "activity_steps": 0,
                "activity_workout": 0,
                "last_active": datetime.now(timezone.utc).isoformat(),
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            response = supabase.table("users").insert(user_data).execute()
            return response.data
        return existing
    except Exception as e:
        print(f"Error creating user: {e}")
        return None

def get_user(telegram_id: int):
    try:
        response = supabase.table("users").select("*").eq("telegram_id", telegram_id).execute()
        if response.data:
            return response.data[0]
    except Exception as e:
        print(f"Error getting user: {e}")
    return None

def update_user(telegram_id: int, **kwargs):
    try:
        kwargs["last_active"] = datetime.now(timezone.utc).isoformat()
        response = supabase.table("users").update(kwargs).eq("telegram_id", telegram_id).execute()
        return response.data
    except Exception as e:
        print(f"Error updating user: {e}")
        return None

def save_prayer(telegram_id: int, prayer_name: str):
    field_map = {
        "Фаджр": "fajr_done",
        "Зухр": "dhuhr_done",
        "Аср": "asr_done",
        "Магриб": "maghrib_done",
        "Иша": "isha_done",
        "Тахаджуд": "tahajjud_done"
    }
    field = field_map.get(prayer_name)
    if field:
        user = get_user(telegram_id)
        if user:
            current_status = user.get(field, False)
            if not current_status:
                new_streak = user.get("streak_days", 1) + 1
                return update_user(telegram_id, **{field: True, "streak_days": new_streak})
    return None

def save_adhkar(telegram_id: int, adhkar_type: str):
    user = get_user(telegram_id)
    if user:
        field = f"{adhkar_type}_adhkar_done"
        return update_user(telegram_id, **{field: True})
    return None

def save_tasbih(telegram_id: int, count: int):
    user = get_user(telegram_id)
    if user:
        current = user.get("tasbih_count", 0)
        return update_user(telegram_id, tasbih_count=current + count)
    return None

def save_quran(telegram_id: int, pages: int):
    user = get_user(telegram_id)
    if user:
        current = user.get("quran_pages", 0)
        return update_user(telegram_id, quran_pages=current + pages)
    return None

def save_books(telegram_id: int, pages: int):
    user = get_user(telegram_id)
    if user:
        current = user.get("books_pages", 0)
        return update_user(telegram_id, books_pages=current + pages)
    return None

def save_activity(telegram_id: int, steps: int = 0, workout: int = 0):
    user = get_user(telegram_id)
    if user:
        curr_steps = user.get("activity_steps", 0)
        curr_workout = user.get("activity_workout", 0)
        return update_user(telegram_id, activity_steps=curr_steps + steps, activity_workout=curr_workout + workout)
    return None

def save_reflection(telegram_id: int, mood: str):
    try:
        data = {
            "telegram_id": telegram_id,
            "mood": mood,
            "date": datetime.now(timezone.utc).isoformat()
        }
        response = supabase.table("reflections").insert(data).execute()
        return response.data
    except Exception as e:
        print(f"Error saving reflection: {e}")
        return None

def get_stats(telegram_id: int):
    return get_user(telegram_id)

def get_streak(telegram_id: int):
    user = get_user(telegram_id)
    if user:
        return user.get("streak_days", 1)
    return 1

def pause_mode(telegram_id: int, reason: str = None):
    return update_user(telegram_id, pause_mode=True, pause_reason=reason)

def resume_mode(telegram_id: int):
    return update_user(telegram_id, pause_mode=False, pause_reason=None)

def get_all_active_users():
    try:
        response = supabase.table("users").select("*").eq("pause_mode", False).execute()
        return response.data if response.data else []
    except Exception as e:
        print(f"Error getting active users: {e}")
        return []
