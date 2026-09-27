import os
import logging
from datetime import datetime, timezone, timedelta
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
    """Вычисляет текущую локальную дату пользователя на основе его IANA таймзоны."""
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
    """Создает пользователя в базе данных."""
    try:
        existing = get_user(telegram_id)
        if not existing:
            user_data = {
                "telegram_id": telegram_id,
                "username": username,
                "first_name": first_name,
                "language": "ru",
                "city": None,
                "timezone": None,
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
                "fajr": False,
                "dhuhr": False,
                "asr": False,
                "maghrib": False,
                "isha": False,
                "tahajjud": False,
                "morning_adhkar": False,
                "evening_adhkar": False,
                "salawat_count": 0,
                "subhanallah_count": 0,
                "alhamdulillah_count": 0,
                "allahuakbar_count": 0,
                "astaghfirullah_count": 0,
                "la_ilaha_illallah_count": 0,
                "active_tasbih_type": None,
                "active_tasbih_count": 0,
                "quran_pages": 0,
                "knowledge": False,
                "activity_steps": 0,
                "reflection_text": None,
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            ins = supabase.table("daily_progress").insert(new_prog).execute()
            if ins.data:
                return ins.data[0]
    except Exception as e:
        logging.error(f"Error getting/creating daily progress for user_id {user_id}: {e}")
    return None


def update_today_progress(user: Dict[str, Any], **kwargs: Any) -> Optional[List[Dict[str, Any]]]:
    """Обновляет дневной прогресс пользователя."""
    user_id = user["id"]
    local_date_str = get_user_local_date(user)
    try:
        get_today_progress(user)
        response = supabase.table("daily_progress").update(kwargs).eq("user_id", user_id).eq("date", local_date_str).execute()
        return response.data
    except Exception as e:
        logging.error(f"Error updating daily progress for user_id {user_id}: {e}")
    return None


def check_daily_minimum_met(prog: Optional[Dict[str, Any]], level: str) -> bool:
    """Проверяет, выполнен ли дневной минимум выбранного этапа для защиты серии дней."""
    if not prog:
        return False
    base_met = bool(prog.get("fajr") and prog.get("dhuhr") and prog.get("asr") and prog.get("maghrib") and prog.get("isha"))
    return base_met


def check_and_bump_streak(telegram_id: int) -> None:
    """Правильный подсчет серий: +1 день только если выполнен дневной минимум."""
    user = get_user(telegram_id)
    if not user or not user.get("timezone"):
        return
    user_id = user["id"]
    prog = get_today_progress(user)
    level = user.get("current_level", "alfard")
    
    if check_daily_minimum_met(prog, level):
        local_today_str = get_user_local_date(user)
        local_today = datetime.strptime(local_today_str, "%Y-%m-%d").date()
        yesterday_str = (local_today - timedelta(days=1)).isoformat()
        
        try:
            resp = supabase.table("daily_progress").select("*").eq("user_id", user_id).eq("date", yesterday_str).execute()
            yesterday_prog = resp.data[0] if resp.data else None
        except Exception as e:
            logging.error(f"Error fetching yesterday progress for streak check: {e}")
            yesterday_prog = None
            
        current_streak = user.get("streak_days", 0) or 0
        pass


def save_prayer(telegram_id: int, prayer_name: str) -> Optional[List[Dict[str, Any]]]:
    """Отмечает намаз выполненным."""
    user = get_user(telegram_id)
    if not user or not user.get("city"):
        return None
    field_map = {
        "Фаджр": "fajr",
        "Зухр": "dhuhr",
        "Аср": "asr",
        "Магриб": "maghrib",
        "Иша": "isha",
        "Тахаджуд": "tahajjud"
    }
    field = field_map.get(prayer_name)
    if field:
        prog = get_today_progress(user)
        if prog and not prog.get(field, False):
            res = update_today_progress(user, **{field: True})
            updated_prog = get_today_progress(user)
            if check_daily_minimum_met(updated_prog, user.get("current_level", "alfard")):
                current_streak = user.get("streak_days", 0) or 0
                update_user(telegram_id, streak_days=max(current_streak, 1))
            return res
    return None


def save_adhkar(telegram_id: int, adhkar_type: str) -> Optional[List[Dict[str, Any]]]:
    """Отмечает азкары выполненными."""
    user = get_user(telegram_id)
    if user and user.get("city"):
        field = f"{adhkar_type}_adhkar"
        return update_today_progress(user, **{field: True})
    return None


def save_tasbih(telegram_id: int, dhikr_key: str, count: int) -> Optional[List[Dict[str, Any]]]:
    """Сохраняет счетчики тасбиха."""
    user = get_user(telegram_id)
    if user and user.get("city"):
        prog = get_today_progress(user)
        if prog:
            current = prog.get(dhikr_key, 0) or 0
            return update_today_progress(user, **{dhikr_key: current + count})
    return None


def save_active_tasbih_state(telegram_id: int, tasbih_type: str, count: int) -> Optional[List[Dict[str, Any]]]:
    """Сохраняет незавершенное состояние зикра."""
    user = get_user(telegram_id)
    if user:
        return update_today_progress(user, active_tasbih_type=tasbih_type, active_tasbih_count=count)


def clear_active_tasbih_state(telegram_id: int) -> Optional[List[Dict[str, Any]]]:
    """Очищает состояние незавершенного зикра при завершении."""
    user = get_user(telegram_id)
    if user:
        return update_today_progress(user, active_tasbih_type=None, active_tasbih_count=0)


def save_quran(telegram_id: int, pages: int) -> Optional[List[Dict[str, Any]]]:
    """Сохраняет прочитанные страницы Корана."""
    user = get_user(telegram_id)
    if user and user.get("city"):
        prog = get_today_progress(user)
        if prog:
            current = prog.get("quran_pages", 0) or 0
            return update_today_progress(user, quran_pages=current + pages)
    return None


def save_activity(telegram_id: int, steps: int = 0) -> Optional[List[Dict[str, Any]]]:
    """Сохраняет шаги физической активности."""
    user = get_user(telegram_id)
    if user and user.get("city"):
        prog = get_today_progress(user)
        if prog:
            current = prog.get("activity_steps", 0) or 0
            return update_today_progress(user, activity_steps=current + steps)
    return None


def save_knowledge(telegram_id: int) -> Optional[List[Dict[str, Any]]]:
    """Отмечает получение знаний."""
    user = get_user(telegram_id)
    if user and user.get("city"):
        return update_today_progress(user, knowledge=True)
    return None


def save_reflection(telegram_id: int, reflection_text: str) -> Optional[List[Dict[str, Any]]]:
    """Сохраняет вечернюю рефлексию."""
    user = get_user(telegram_id)
    if user and user.get("city"):
        return update_today_progress(user, reflection_text=reflection_text, knowledge=True)
    return None


def get_stats(telegram_id: int) -> Optional[Dict[str, Any]]:
    """Возвращает статистику пользователя и прогресс за текущий локальный день."""
    user = get_user(telegram_id)
    if user and user.get("city"):
        prog = get_today_progress(user)
        return {"user": user, "progress": prog}
    return None


def pause_mode(telegram_id: int, reason: Optional[str] = None) -> Optional[List[Dict[str, Any]]]:
    """Включает режим паузы."""
    return update_user(telegram_id, pause_mode=True, pause_reason=reason)


def resume_mode(telegram_id: int) -> Optional[List[Dict[str, Any]]]:
    """Отключает режим паузы."""
    return update_user(telegram_id, pause_mode=False, pause_reason=None)


def get_all_active_users() -> List[Dict[str, Any]]:
    """Получает всех активных пользователей, у которых завершен онбординг."""
    try:
        response = supabase.table("users").select("*").eq("pause_mode", False).not_.is_("city", "null").execute()
        return response.data if response.data else []
    except Exception as e:
        logging.error(f"Error getting active users: {e}")
        return []


def get_cached_prayer_times(city: str, date_str: str) -> Optional[Dict[str, Any]]:
    """Получает кэш расписания намазов из базы данных."""
    try:
        resp = supabase.table("prayer_times_cache").select("*").eq("city", city).eq("date", date_str).execute()
        if resp.data:
            return resp.data[0]
    except Exception as e:
        logging.error(f"Error getting prayer times cache for {city} on {date_str}: {e}")
    return None


def save_cached_prayer_times(city: str, date_str: str, timings: Dict[str, str], meta: Dict[str, Any]) -> None:
    """Сохраняет расписание намазов в кэш."""
    try:
        payload = {
            "city": city,
            "date": date_str,
            "timings": timings,
            "meta": meta,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        supabase.table("prayer_times_cache").upsert(payload, on_conflict="city,date").execute()
    except Exception as e:
        logging.error(f"Error saving prayer times cache for {city} on {date_str}: {e}")
