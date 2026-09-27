import os
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Any, Optional, Dict, List
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Supabase URL and Key must be set in environment variables.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


def get_user_local_date(user: Dict[str, Any]) -> str:
    """Вычисляет локальную дату пользователя на основе его таймзоны."""
    tz_str = user.get("timezone")
    if not tz_str:
        return datetime.now(timezone.utc).date().isoformat()
    try:
        local_tz = ZoneInfo(tz_str)
    except Exception as e:
        logging.error(f"Invalid timezone string '{tz_str}': {e}. Falling back to UTC.")
        local_tz = timezone.utc
    return datetime.now(local_tz).date().isoformat()


def create_user(telegram_id: int, username: Optional[str] = None, first_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Создает или возвращает существующего пользователя."""
    try:
        existing = get_user(telegram_id)
        if not existing:
            user_data = {
                "telegram_id": telegram_id,
                "username": username,
                "first_name": first_name,
                "language": "ru",
                "city": None,
                "timezone": "Europe/Moscow",
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
        logging.error(f"Error creating user {telegram_id}: {e}")
        return None


def get_user(telegram_id: int) -> Optional[Dict[str, Any]]:
    """Получает пользователя по telegram_id."""
    try:
        response = supabase.table("users").select("*").eq("telegram_id", telegram_id).execute()
        if response.data:
            return response.data[0]
    except Exception as e:
        logging.error(f"Error getting user {telegram_id}: {e}")
    return None


def update_user(telegram_id: int, **kwargs: Any) -> Optional[List[Dict[str, Any]]]:
    """Обновляет данные пользователя."""
    try:
        kwargs["last_active"] = datetime.now(timezone.utc).isoformat()
        response = supabase.table("users").update(kwargs).eq("telegram_id", telegram_id).execute()
        return response.data
    except Exception as e:
        logging.error(f"Error updating user {telegram_id}: {e}")
    return None


def get_today_progress(user: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Получает или создает запись ежедневного прогресса за локальный день пользователя."""
    user_id = user["id"]
    local_date_str = get_user_local_date(user)
    try:
        response = supabase.table("daily_progress").select("*").eq("user_id", user_id).eq("date", local_date_str).execute()
        if response.data:
            return response.data[0]
        else:
            new_prog = {
                "user_id": user_id,
                "date": local_date_str,
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
                "active_tasbih_type": None,
                "active_tasbih_progress": 0,
                "quran_done": False,
                "quran_pages": 0,
                "activity_steps": 0,
                "knowledge_done": False,
                "reflection": None,
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            ins = supabase.table("daily_progress").insert(new_prog).execute()
            if ins.data:
                return ins.data[0]
    except Exception as e:
        logging.error(f"Error getting/creating daily progress for user_id {user_id}: {e}")
    return None


def update_today_progress(user: Dict[str, Any], **kwargs: Any) -> Optional[List[Dict[str, Any]]]:
    """Обновляет прогресс текущего дня."""
    user_id = user["id"]
    local_date_str = get_user_local_date(user)
    try:
        get_today_progress(user)
        response = supabase.table("daily_progress").update(kwargs).eq("user_id", user_id).eq("date", local_date_str).execute()
        return response.data
    except Exception as e:
        logging.error(f"Error updating daily progress for user_id {user_id}: {e}")
    return None


def save_prayer(telegram_id: int, prayer_name: str) -> Optional[List[Dict[str, Any]]]:
    """Отмечает намаз выполненным и обновляет стрик при выполнении обязательного минимума."""
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
        prog = get_today_progress(user)
        if prog and not prog.get(field, False):
            res = update_today_progress(user, **{field: True})
            updated_prog = get_today_progress(user)
            # Проверка обязательных 5 намазов для поддержания серии дней
            if updated_prog and updated_prog.get("fajr_done") and updated_prog.get("dhuhr_done") and updated_prog.get("asr_done") and updated_prog.get("maghrib_done") and updated_prog.get("isha_done"):
                current_streak = user.get("streak_days", 0) or 0
                update_user(telegram_id, streak_days=max(current_streak, 1))
            return res
    return None


def save_adhkar(telegram_id: int, adhkar_type: str) -> Optional[List[Dict[str, Any]]]:
    """Сохраняет статус утренних или вечерних азкаров."""
    user = get_user(telegram_id)
    if user:
        field = f"morning_adhkar_done" if adhkar_type == "morning" else "evening_adhkar_done"
        return update_today_progress(user, **{field: True})
    return None


def save_tasbih_progress(telegram_id: int, dhikr_field: str, count: int, active_type: Optional[str] = None, active_progress: int = 0) -> Optional[List[Dict[str, Any]]]:
    """Сохраняет прогресс умного тасбиха и общие счетчики зикров."""
    user = get_user(telegram_id)
    if user:
        prog = get_today_progress(user)
        if prog:
            current = prog.get(dhikr_field, 0) or 0
            updates = {
                dhikr_field: current + count,
                "active_tasbih_type": active_type,
                "active_tasbih_progress": active_progress
            }
            return update_today_progress(user, **updates)
    return None


def save_quran(telegram_id: int, pages: int) -> Optional[List[Dict[str, Any]]]:
    """Сохраняет прочитанные страницы Корана."""
    user = get_user(telegram_id)
    if user:
        prog = get_today_progress(user)
        if prog:
            current = prog.get("quran_pages", 0) or 0
            return update_today_progress(user, quran_pages=current + pages, quran_done=True)
    return None


def save_activity(telegram_id: int, steps_or_minutes: int) -> Optional[List[Dict[str, Any]]]:
    """Сохраняет физическую активность (шаги или спорт)."""
    user = get_user(telegram_id)
    if user:
        prog = get_today_progress(user)
        if prog:
            current = prog.get("activity_steps", 0) or 0
            return update_today_progress(user, activity_steps=current + steps_or_minutes)
    return None


def get_stats(telegram_id: int) -> Optional[Dict[str, Any]]:
    """Возвращает статистику пользователя и прогресс за текущий день."""
    user = get_user(telegram_id)
    if user:
        prog = get_today_progress(user)
        return {"user": user, "progress": prog}
    return None
