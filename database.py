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
                "current_level": "alfard",
                "streak_days": 0,
                "pause_mode": False,
                "pause_reason": None,
                "last_active": datetime.now(timezone.utc).isoformat(),
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            response = supabase.table("users").insert(user_data).execute()
            if response.data:
                return response.data[0]
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

def get_today_progress(user_id: int):
    today_str = datetime.now(timezone.utc).date().isoformat()
    try:
        response = supabase.table("daily_progress").select("*").eq("user_id", user_id).eq("date", today_str).execute()
        if response.data:
            return response.data[0]
        else:
            new_prog = {
                "user_id": user_id,
                "date": today_str,
                "fajr_done": False,
                "dhuhr_done": False,
                "asr_done": False,
                "maghrib_done": False,
                "isha_done": False,
                "tahajjud_done": False,
                "morning_adhkar_done": False,
                "evening_adhkar_done": False,
                "salawat_count": 0,
                "subhanallah_count": 0,
                "alhamdulillah_count": 0,
                "allahuakbar_count": 0,
                "astaghfirullah_count": 0,
                "la_ilaha_illallah_count": 0,
                "quran_done": False,
                "quran_pages": 0,
                "activity_steps": 0,
                "knowledge_done": False,
                "reflection_text": None,
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            ins = supabase.table("daily_progress").insert(new_prog).execute()
            if ins.data:
                return ins.data[0]
    except Exception as e:
        print(f"Error getting/creating daily progress: {e}")
    return None

def update_today_progress(user_id: int, **kwargs):
    today_str = datetime.now(timezone.utc).date().isoformat()
    try:
        get_today_progress(user_id)
        response = supabase.table("daily_progress").update(kwargs).eq("user_id", user_id).eq("date", today_str).execute()
        return response.data
    except Exception as e:
        print(f"Error updating daily progress: {e}")
    return None

def save_prayer(telegram_id: int, prayer_name: str):
    user = get_user(telegram_id)
    if not user:
        return None
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
        prog = get_today_progress(user["id"])
        if prog and not prog.get(field, False):
            return update_today_progress(user["id"], **{field: True})
    return None

def save_adhkar(telegram_id: int, adhkar_type: str):
    user = get_user(telegram_id)
    if user:
        field = f"{adhkar_type}_adhkar_done"
        return update_today_progress(user["id"], **{field: True})
    return None

def save_tasbih(telegram_id: int, dhikr_key: str, count: int):
    user = get_user(telegram_id)
    if user:
        prog = get_today_progress(user["id"])
        if prog:
            current = prog.get(dhikr_key, 0) or 0
            return update_today_progress(user["id"], **{dhikr_key: current + count})
    return None

def save_quran(telegram_id: int, pages: int):
    user = get_user(telegram_id)
    if user:
        prog = get_today_progress(user["id"])
        if prog:
            current = prog.get("quran_pages", 0) or 0
            total_pages = current + pages
            return update_today_progress(user["id"], quran_pages=total_pages, quran_done=True)
    return None

def save_activity(telegram_id: int, steps: int = 0):
    user = get_user(telegram_id)
    if user:
        prog = get_today_progress(user["id"])
        if prog:
            current = prog.get("activity_steps", 0) or 0
            return update_today_progress(user["id"], activity_steps=current + steps)
    return None

def save_reflection(telegram_id: int, reflection_text: str):
    user = get_user(telegram_id)
    if user:
        return update_today_progress(user["id"], reflection_text=reflection_text, knowledge_done=True)
    return None

def get_stats(telegram_id: int):
    user = get_user(telegram_id)
    if user:
        prog = get_today_progress(user["id"])
        return {"user": user, "progress": prog}
    return None

def get_streak(telegram_id: int):
    user = get_user(telegram_id)
    if user:
        return user.get("streak_days", 0)
    return 0

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
