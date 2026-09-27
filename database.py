import os
import logging
from datetime import datetime, timezone
from typing import Any, Optional, Dict, List
from dotenv import load_dotenv
from supabase import create_client, Client

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    logging.error("CRITICAL: SUPABASE_URL or SUPABASE_KEY is missing in environment variables!")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None


def get_user_local_date(user: Dict[str, Any]) -> str:
    """Вычисляет локальную дату пользователя на основе таймзоны."""
    tz_str = user.get("timezone")
    if not tz_str or ZoneInfo is None:
        return datetime.now(timezone.utc).date().isoformat()
    try:
        local_tz = ZoneInfo(tz_str)
    except Exception as e:
        local_tz = timezone.utc
    return datetime.now(local_tz).date().isoformat()


def get_or_create_user(telegram_id: int, username: str = None, first_name: str = None) -> Dict[str, Any]:
    """Получает пользователя из базы или создает нового при первом старте."""
    if not supabase:
        return {}
    try:
        res = supabase.table("users").select("*").eq("telegram_id", telegram_id).execute()
        if res.data:
            return res.data[0]
        
        new_user = {
            "telegram_id": telegram_id,
            "username": username,
            "first_name": first_name,
            "streak_days": 0,
            "pause_mode": False,
            "city": "Не указан",
            "current_level": "Аль-Фард",
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        ins = supabase.table("users").insert(new_user).execute()
        return ins.data[0] if ins.data else {}
    except Exception as e:
        logging.error(f"Error in get_or_create_user: {e}")
        return {}


def update_user(telegram_id: int, data: Dict[str, Any]) -> bool:
    """Обновляет данные пользователя."""
    if not supabase:
        return False
    try:
        supabase.table("users").update(data).eq("telegram_id", telegram_id).execute()
        return True
    except Exception as e:
        logging.error(f"Error updating user {telegram_id}: {e}")
        return False


def get_today_progress(user_id: int, date_str: str) -> Dict[str, Any]:
    """Получает или создает запись прогресса за текущий день."""
    if not supabase:
        return {}
    try:
        res = supabase.table("daily_progress").select("*").eq("user_id", user_id).eq("date", date_str).execute()
        if res.data:
            return res.data[0]
        
        new_prog = {
            "user_id": user_id,
            "date": date_str,
            "morning_adhkar_done": False,
            "evening_adhkar_done": False,
            "zikr_count": 0,
            "activity_steps": 0,
            "sport_minutes": 0
        }
        ins = supabase.table("daily_progress").insert(new_prog).execute()
        return ins.data[0] if ins.data else {}
    except Exception as e:
        logging.error(f"Error getting daily progress: {e}")
        return {}


def update_daily_progress(user_id: int, date_str: str, data: Dict[str, Any]) -> bool:
    """Обновляет дневной прогресс пользователя."""
    if not supabase:
        return False
    try:
        supabase.table("daily_progress").update(data).eq("user_id", user_id).eq("date", date_str).execute()
        return True
    except Exception as e:
        logging.error(f"Error updating daily progress: {e}")
        return False
