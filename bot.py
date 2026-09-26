import os
import logging
import random
import asyncio
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from typing import Dict, Any, Optional
import aiohttp
from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

from database import (
    create_user, get_user, update_user, save_prayer, save_adhkar,
    save_tasbih, save_quran, save_activity, save_reflection,
    get_stats, get_streak, pause_mode, resume_mode, get_all_active_users,
    get_today_progress, get_cached_prayer_times, save_cached_prayer_times,
    get_user_local_date
)

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise ValueError("BOT_TOKEN must be set in environment variables.")

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler(timezone="UTC")

class OnboardingState(StatesGroup):
    waiting_for_city = State()

class QuranState(StatesGroup):
    waiting_for_pages = State()

class ActivityState(StatesGroup):
    waiting_for_steps = State()

class ReflectionState(StatesGroup):
    waiting_for_text = State()

class SettingsState(StatesGroup):
    waiting_for_city = State()

# Справочник точных таймзон для городов на кириллице, чтобы не зависеть от API Aladhan
CITY_TIMEZONES = {
    "нерюнгри": "Asia/Yakutsk",
    "якутск": "Asia/Yakutsk",
    "москва": "Europe/Moscow",
    "санкт-петербург": "Europe/Moscow",
    "казань": "Europe/Moscow",
    "уфа": "Asia/Yekaterinburg",
    "екатеринбург": "Asia/Yekaterinburg",
    "новосибирск": "Asia/Novosibirsk",
    "алматы": "Asia/Almaty",
    "астана": "Asia/Almaty",
    "бишкек": "Asia/Bishkek",
    "ташкент": "Asia/Tashkent",
    "грозный": "Europe/Moscow",
    "махачкала": "Europe/Moscow"
}

STORIES = [
    "История Абу Бакра (да будет доволен им Аллах): его щедрость не знала границ, он отдал всё своё имущество на пути Аллаха.",
    "История Умара ибн аль-Хаттаба (да будет доволен им Аллах): пример справедливости, силы духа и заботы об умме.",
    "История Усмана ибн Аффана (да будет доволен им Аллах): человек величайшей скромности и обладатель двух светлых лучей.",
    "История Али ибн Абу Талиба (да будет доволен им Аллах): мудрость, преданность и отвага с ранних лет ислама.",
    "История Биляла ибн Рабаха (да будет доволен им Аллах): стойкость в вере несмотря на жестокие испытания и пытки."
]

user_last_story: Dict[int, int] = {}
inactivity_notified = set()


def reset_inactivity_flag(telegram_id: int) -> None:
    if telegram_id in inactivity_notified:
        inactivity_notified.remove(telegram_id)


def get_user_random_story(telegram_id: int) -> str:
    if len(STORIES) <= 1:
        return STORIES[0]
    last_idx = user_last_story.get(telegram_id)
    while True:
        idx = random.randint(0, len(STORIES) - 1)
        if idx != last_idx:
            user_last_story[telegram_id] = idx
            return STORIES[idx]


def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Все функции доступны любому пользователю всегда."""
    kb = [
        [InlineKeyboardButton(text="🕌 Время намазов", callback_data="menu_prayers"),
         InlineKeyboardButton(text="📿 Тасбих и Салават", callback_data="menu_tasbih")],
        [InlineKeyboardButton(text="🌅 Азкары", callback_data="menu_adhkar"),
         InlineKeyboardButton(text="🏃 Активность", callback_data="menu_activity")],
        [InlineKeyboardButton(text="📖 Коран", callback_data="menu_quran"),
         InlineKeyboardButton(text="🌙 Тахаджуд", callback_data="pr_tahajjud")],
        [InlineKeyboardButton(text="📖 Истории сподвижников", callback_data="menu_stories")],
        [InlineKeyboardButton(text="📈 Мой путь", callback_data="menu_path"),
         InlineKeyboardButton(text="⚙️ Настройки", callback_data="menu_settings")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


async def fetch_prayer_data(city: str, date_str: str) -> Dict[str, Any]:
    """Получает расписание намазов через кэш prayer_times_cache или Aladhan API."""
    cached = get_cached_prayer_times(city, date_str)
    if cached:
        return {"timings": cached["timings"], "meta": cached["meta"]}

    parts = date_str.split("-")
    formatted_date = f"{parts[2]}-{parts[1]}-{parts[0]}"
    url = f"https://api.aladhan.com/v1/timingsByCity/{formatted_date}?city={city}&country=&method=3"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    res_data = data.get("data", {})
                    timings = res_data.get("timings", {})
                    meta = res_data.get("meta", {})
                    if timings:
                        save_cached_prayer_times(city, date_str, timings, meta)
                    return {"timings": timings, "meta": meta}
    except Exception as e:
        logging.error(f"Error fetching prayer data for {city}: {e}")
    return {}


async def send_prayer_reminder(chat_id: int, text: str, reply_markup: InlineKeyboardMarkup) -> None:
    try:
        await bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode="HTML")
    except Exception as ex:
        logging.error(f"Error sending scheduled reminder to {chat_id}: {ex}")


async def check_and_remind(t_id: int, u_id: int, p_n: str, p_c: str) -> None:
    user = get_user(t_id)
    if not user:
        return
    prog = get_today_progress(user)
    field_map = {
        "Фаджр": "fajr_done",
        "Зухр": "dhuhr_done",
        "Аср": "asr_done",
        "Магриб": "maghrib_done",
        "Иша": "isha_done"
    }
    f = field_map.get(p_n)
    if prog and f and not prog.get(f, False):
        kb_after = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"✅ Отметить {p_n}", callback_data=f"notif_pr_{p_c}")]
        ])
        try:
            await bot.send_message(t_id, f"💡 Прошло 20 минут с момента намаза <b>{p_n}</b>. Если вы уже совершили его, отметьте в боте:", reply_markup=kb_after, parse_mode="HTML")
        except Exception as ex:
            logging.error(f"Error sending soft reminder: {ex}")


async def ensure_onboarded_callback(callback: types.CallbackQuery) -> bool:
    user = get_user(callback.from_user.id)
    if not user or not user.get("city") or not user.get("timezone"):
        await callback.message.edit_text("Пожалуйста, завершите онбординг и выберите город через команду /start")
        await callback.answer()
        return False
    return True


async def ensure_onboarded_message(message: types.Message) -> bool:
    user = get_user(message.from_user.id)
    if not user or not user.get("city") or not user.get("timezone"):
        await message.answer("Пожалуйста, завершите онбординг и выберите город через команду /start")
        return False
    return True


@dp.message(Command("start"))
async def cmd_start(message: types.Message) -> None:
    user = create_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    reset_inactivity_flag(message.from_user.id)
    
    if not user or not user.get("city") or not user.get("timezone"):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Продолжить с Бисмиллях", callback_data="onboard_start")]
        ])
        await message.answer(
            "Ассаляму алейкум! Добро пожаловать в <b>Amal365</b> — ваш личный спутник в духовном развитии.\n\n"
            "Бот предлагает, но не навязывает. Все практики всегда доступны для вас.",
            reply_markup=kb, parse_mode="HTML"
        )
    else:
        kb = get_main_menu_keyboard()
        await message.answer("С возвращением в главное меню:", reply_markup=kb)


@dp.callback_query(F.data == "onboard_start")
async def onboard_language(callback: types.CallbackQuery) -> None:
    reset_inactivity_flag(callback.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang_ru")]
    ])
    await callback.message.edit_text("Выберите язык интерфейса / Select language:", reply_markup=kb)
    await callback.answer()


@dp.callback_query(F.data.startswith("lang_"))
async def onboard_city(callback: types.CallbackQuery, state: FSMContext) -> None:
    reset_inactivity_flag(callback.from_user.id)
    lang = callback.data.split("_")[1]
    update_user(callback.from_user.id, language=lang)
    await callback.message.edit_text("Введите ваш город (например, Нерюнгри, Москва, Алматы, Бишкек):")
    await state.set_state(OnboardingState.waiting_for_city)
    await callback.answer()


@dp.message(OnboardingState.waiting_for_city)
async def process_city(message: types.Message, state: FSMContext) -> None:
    city_raw = message.text.strip()
    city_lower = city_raw.lower()
    
    tz_str = CITY_TIMEZONES.get(city_lower)
    
    if not tz_str:
        today_str = datetime.now(timezone.utc).strftime("%d-%m-%Y")
        url = f"https://api.aladhan.com/v1/timingsByCity/{today_str}?city={city_raw}&country=&method=3"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        meta = data.get("data", {}).get("meta", {})
                        tz_str = meta.get("timezone")
        except Exception as e:
            logging.error(f"Validation error for city {city_raw}: {e}")

    if not tz_str:
        await message.answer("Не удалось определить часовой пояс для этого города. Проверьте правильность написания или введите город на английском (например, Neryungri):")
        return

    update_user(message.from_user.id, city=city_raw, timezone=tz_str)
    reset_inactivity_flag(message.from_user.id)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌱 Аль-Фард (Базовый акцент)", callback_data="level_alfard")],
        [InlineKeyboardButton(text="🌿 Аль-Истикама (Постоянство)", callback_data="level_alistikama")],
        [InlineKeyboardButton(text="🌳 Ат-Тазаккия (Очищение)", callback_data="level_attazkiya")],
        [InlineKeyboardButton(text="🌟 Аль-Ихсан (Совершенство)", callback_data="level_alihsan")]
    ])
    await message.answer(
        f"Город сохранен: <b>{city_raw}</b> (Часовой пояс: {tz_str}).\n\nВыберите ваш текущий духовный фокус:",
        reply_markup=kb, parse_mode="HTML"
    )
    await state.clear()


@dp.callback_query(F.data.startswith("level_"))
async def process_level(callback: types.CallbackQuery) -> None:
    if not await ensure_onboarded_callback(callback):
        return
    reset_inactivity_flag(callback.from_user.id)
    level = callback.data.split("_")[1]
    update_user(callback.from_user.id, current_level=level)
    kb = get_main_menu_keyboard()
    await callback.message.edit_text(
        "Альхамдулиллах! Настройка завершена. Добро пожаловать в главное меню:",
        reply_markup=kb
    )
    await callback.answer()


@dp.callback_query(F.data == "go_to_main")
async def go_to_main(callback: types.CallbackQuery) -> None:
    if not await ensure_onboarded_callback(callback):
        return
    reset_inactivity_flag(callback.from_user.id)
    kb = get_main_menu_keyboard()
    await callback.message.edit_text("Главное меню:", reply_markup=kb)
    await callback.answer()


@dp.callback_query(F.data == "menu_prayers")
async def menu_prayers(callback: types.CallbackQuery) -> None:
    if not await ensure_onboarded_callback(callback):
        return
    reset_inactivity_flag(callback.from_user.id)
    user = get_user(callback.from_user.id)
    city = user.get("city")
    local_date_str = get_user_local_date(user)
    
    data = await fetch_prayer_data(city, local_date_str)
    timings = data.get("timings", {})
    prog = get_today_progress(user) or {}
    
    fajr_status = "✅" if prog.get("fajr_done") else "⬜️"
    dhuhr_status = "✅" if prog.get("dhuhr_done") else "⬜️"
    asr_status = "✅" if prog.get("asr_done") else "⬜️"
    maghrib_status = "✅" if prog.get("maghrib_done") else "⬜️"
    isha_status = "✅" if prog.get("isha_done") else "⬜️"
    tahajjud_status = "✅" if prog.get("tahajjud_done") else "⬜️"

    fajr_time = timings.get("Fajr", "--:--")
    dhuhr_time = timings.get("Dhuhr", "--:--")
    asr_time = timings.get("Asr", "--:--")
    maghrib_time = timings.get("Maghrib", "--:--")
    isha_time = timings.get("Isha", "--:--")

    text = (
        f"🕌 <b>Время намазов для г. {city}</b>\n\n"
        f"{fajr_status} Фаджр: {fajr_time}\n"
        f"{dhuhr_status} Зухр: {dhuhr_time}\n"
        f"{asr_status} Аср: {asr_time}\n"
        f"{maghrib_status} Магриб: {maghrib_time}\n"
        f"{isha_status} Иша: {isha_time}\n"
        f"{tahajjud_status} Тахаджуд (ночной)\n\n"
        "Отметьте выполненный намаз:"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{fajr_status} Фаджр", callback_data="pr_fajr"),
         InlineKeyboardButton(text=f"{dhuhr_status} Зухр", callback_data="pr_dhuhr")],
        [InlineKeyboardButton(text=f"{asr_status} Аср", callback_data="pr_asr"),
         InlineKeyboardButton(text=f"{maghrib_status} Магриб", callback_data="pr_maghrib")],
        [InlineKeyboardButton(text=f"{isha_status} Иша", callback_data="pr_isha"),
         InlineKeyboardButton(text=f"{tahajjud_status} Тахаджуд", callback_data="pr_tahajjud")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="go_to_main")]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data.startswith("pr_"))
async def prayer_done_handler(callback: types.CallbackQuery) -> None:
    if not await ensure_onboarded_callback(callback):
        return
    reset_inactivity_flag(callback.from_user.id)
    code_map = {
        "fajr": "Фаджр",
        "dhuhr": "Зухр",
        "asr": "Аср",
        "maghrib": "Магриб",
        "isha": "Иша",
        "tahajjud": "Тахаджуд"
    }
    key = callback.data.split("_")[1]
    prayer_name = code_map.get(key, "Фаджр")
    save_prayer(callback.from_user.id, prayer_name)
    await callback.answer(f"Намаз '{prayer_name}' отмечен!")
    await menu_prayers(callback)


@dp.callback_query(F.data == "menu_tasbih")
async def menu_tasbih(callback: types.CallbackQuery) -> None:
    if not await ensure_onboarded_callback(callback):
        return
    reset_inactivity_flag(callback.from_user.id)
    user = get_user(callback.from_user.id)
    prog = get_today_progress(user) or {}
    
    salawat = prog.get("salawat_count", 0)
    subhan = prog.get("subhanallah_count", 0)
    alhamdulillah = prog.get("alhamdulillah_count", 0)
    allahu = prog.get("allahuakbar_count", 0)
    astagh = prog.get("astaghfirullah_count", 0)
    la_ilaha = prog.get("la_ilaha_illallah_count", 0)

    text = (
        "📿 <b>Тасбих и Салават за сегодня</b>:\n\n"
        f"✨ Салават: {salawat}\n"
        f"📿 Субханаллах: {subhan}\n"
        f"🌿 Альхамдулиллах: {alhamdulillah}\n"
        f"🤲 Аллаху Акбар: {allahu}\n"
        f" استغفر الله Астагфируллах: {astagh}\n"
        f"🕊 Ла илаха илляллах: {la_ilaha}\n\n"
        "Добавить поминание:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="+10 Салават", callback_data="tas_salawat_10"),
         InlineKeyboardButton(text="+33 Субханаллах", callback_data="tas_subhanallah_33")],
        [InlineKeyboardButton(text="+33 Альхамдулиллах", callback_data="tas_alhamdulillah_33"),
         InlineKeyboardButton(text="+33 Аллаху Акбар", callback_data="tas_allahuakbar_33")],
        [InlineKeyboardButton(text="+33 Астагфируллах", callback_data="tas_astaghfirullah_33"),
         InlineKeyboardButton(text="+10 Ла илаха илляллах", callback_data="tas_la_ilaha_illallah_10")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="go_to_main")]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data.startswith("tas_"))
async def tasbih_add_handler(callback: types.CallbackQuery) -> None:
    if not await ensure_onboarded_callback(callback):
        return
    reset_inactivity_flag(callback.from_user.id)
    parts = callback.data.split("_")
    dhikr_key = f"{parts[1]}_count"
    count = int(parts[2])
    save_tasbih(callback.from_user.id, dhikr_key, count)
    await callback.answer(f"Добавлено +{count}!")
    await menu_tasbih(callback)


@dp.callback_query(F.data == "menu_adhkar")
async def menu_adhkar(callback: types.CallbackQuery) -> None:
    if not await ensure_onboarded_callback(callback):
        return
    reset_inactivity_flag(callback.from_user.id)
    user = get_user(callback.from_user.id)
    prog = get_today_progress(user) or {}
    
    m_done = "✅" if prog.get("morning_adhkar_done") else "⬜️"
    e_done = "✅" if prog.get("evening_adhkar_done") else "⬜️"

    text = "🌅 <b>Утренние и вечерние азкары</b>\n\nОтметьте выполненные азкары:"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{m_done} Утренние азкары", callback_data="adh_morning")],
        [InlineKeyboardButton(text=f"{e_done} Вечерние азкары", callback_data="adh_evening")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="go_to_main")]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data.startswith("adh_"))
async def adhkar_done_handler(callback: types.CallbackQuery) -> None:
    if not await ensure_onboarded_callback(callback):
        return
    reset_inactivity_flag(callback.from_user.id)
    atype = callback.data.split("_")[1]
    save_adhkar(callback.from_user.id, atype)
    await callback.answer("Азкары отмечены!")
    await menu_adhkar(callback)


@dp.callback_query(F.data == "menu_activity")
async def menu_activity(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not await ensure_onboarded_callback(callback):
        return
    reset_inactivity_flag(callback.from_user.id)
    user = get_user(callback.from_user.id)
    prog = get_today_progress(user) or {}
    steps = prog.get("activity_steps", 0)
    
    await callback.message.edit_text(
        f"🏃 <b>Физическая активность</b>\n\n"
        f"Пройдено шагов за сегодня: <b>{steps}</b>\n\n"
        f"Введите количество шагов, которые хотите добавить:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="go_to_main")]
        ]),
        parse_mode="HTML"
    )
    await state.set_state(ActivityState.waiting_for_steps)
    await callback.answer()


@dp.message(ActivityState.waiting_for_steps)
async def process_activity_steps(message: types.Message, state: FSMContext) -> None:
    if not await ensure_onboarded_message(message):
        return
    try:
        steps = int(message.text.strip())
        if steps < 0 or steps > 100000:
            raise ValueError()
        save_activity(message.from_user.id, steps)
        reset_inactivity_flag(message.from_user.id)
        kb = get_main_menu_keyboard()
        await message.answer(f"Альхамдулиллах! Добавлено шагов: {steps}", reply_markup=kb)
        await state.clear()
    except ValueError:
        await message.answer("Пожалуйста, введите корректное число шагов (например, 5000):")


@dp.callback_query(F.data == "menu_quran")
async def menu_quran(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not await ensure_onboarded_callback(callback):
        return
    reset_inactivity_flag(callback.from_user.id)
    user = get_user(callback.from_user.id)
    prog = get_today_progress(user) or {}
    pages = prog.get("quran_pages", 0)
    
    await callback.message.edit_text(
        f"📖 <b>Чтение Корана</b>\n\n"
        f"Прочитано страниц за сегодня: <b>{pages}</b>\n\n"
        f"Введите количество прочитанных страниц:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="go_to_main")]
        ]),
        parse_mode="HTML"
    )
    await state.set_state(QuranState.waiting_for_pages)
    await callback.answer()


@dp.message(QuranState.waiting_for_pages)
async def process_quran_pages(message: types.Message, state: FSMContext) -> None:
    if not await ensure_onboarded_message(message):
        return
    try:
        pages = int(message.text.strip())
        if pages < 0 or pages > 600:
            raise ValueError()
        save_quran(message.from_user.id, pages)
        reset_inactivity_flag(message.from_user.id)
        kb = get_main_menu_keyboard()
        await message.answer(f"Альхамдулиллах! Записано страниц Корана: {pages}", reply_markup=kb)
        await state.clear()
    except ValueError:
        await message.answer("Пожалуйста, введите корректное число страниц:")


@dp.callback_query(F.data == "menu_stories")
async def menu_stories(callback: types.CallbackQuery) -> None:
    if not await ensure_onboarded_callback(callback):
        return
    reset_inactivity_flag(callback.from_user.id)
    story = get_user_random_story(callback.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Ещё историю", callback_data="menu_stories")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="go_to_main")]
    ])
    await callback.message.edit_text(f"📖 <b>История сподвижников</b>\n\n{story}", reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data == "menu_path")
async def menu_path(callback: types.CallbackQuery) -> None:
    if not await ensure_onboarded_callback(callback):
        return
    reset_inactivity_flag(callback.from_user.id)
    user = get_user(callback.from_user.id)
    stats = get_stats(callback.from_user.id) or {}
    prog = stats.get("progress", {}) or {}
    
    level_names = {
        "alfard": "Аль-Фард (Базовый акцент)",
        "alistikama": "Аль-Истикама (Постоянство)",
        "attazkiya": "Ат-Тазаккия (Очищение)",
        "alihsan": "Аль-Ихсан (Совершенство)"
    }
    
    level_title = level_names.get(user.get("current_level", "alfard"), "Аль-Фард")
    streak = user.get("streak_days", 0)
    quran_pages = prog.get("quran_pages", 0)
    steps = prog.get("activity_steps", 0)
    salawat = prog.get("salawat_count", 0)

    text = (
        "📈 <b>Ваш духовный путь</b>\n\n"
        f"🌱 Фокус сопровождения: <b>{level_title}</b>\n"
        f"🔥 Серия дней: <b>{streak} дн.</b>\n"
        f"📖 Страниц Корана сегодня: <b>{quran_pages}</b>\n"
        f"🏃 Шагов сегодня: <b>{steps}</b>\n"
        f"✨ Салават сегодня: <b>{salawat}</b>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="go_to_main")]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data == "menu_settings")
async def menu_settings(callback: types.CallbackQuery) -> None:
    if not await ensure_onboarded_callback(callback):
        return
    reset_inactivity_flag(callback.from_user.id)
    user = get_user(callback.from_user.id)
    pause = "Включена ⏸" if user.get("pause_mode") else "Выключена ▶️"
    text = (
        "⚙️ <b>Настройки</b>\n\n"
        f"Город: <b>{user.get('city')}</b>\n"
        f"Фокус сопровождения: <b>{user.get('current_level', 'alfard')}</b>\n"
        f"Деликатная пауза: <b>{pause}</b>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏙 Изменить город", callback_data="set_city")],
        [InlineKeyboardButton(text="📊 Изменить фокус", callback_data="set_level")],
        [InlineKeyboardButton(text="🧘 Пауза / Возврат", callback_data="toggle_pause")],
        [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="go_to_main")]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data == "set_city")
async def set_city_start(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not await ensure_onboarded_callback(callback):
        return
    reset_inactivity_flag(callback.from_user.id)
    await callback.message.edit_text("Введите новый город:")
    await state.set_state(SettingsState.waiting_for_city)
    await callback.answer()


@dp.message(SettingsState.waiting_for_city)
async def set_city_finish(message: types.Message, state: FSMContext) -> None:
    if not await ensure_onboarded_message(message):
        return
    city_raw = message.text.strip()
    city_lower = city_raw.lower()
    
    tz_str = CITY_TIMEZONES.get(city_lower)
    
    if not tz_str:
        today_str = datetime.now(timezone.utc).strftime("%d-%m-%Y")
        url = f"https://api.aladhan.com/v1/timingsByCity/{today_str}?city={city_raw}&country=&method=3"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        meta = data.get("data", {}).get("meta", {})
                        tz_str = meta.get("timezone")
        except Exception as e:
            logging.error(f"Validation error for city {city_raw}: {e}")

    if not tz_str:
        await message.answer("Не удалось определить часовой пояс. Введите корректное название:")
        return

    update_user(message.from_user.id, city=city_raw, timezone=tz_str)
    reset_inactivity_flag(message.from_user.id)
    kb = get_main_menu_keyboard()
    await message.answer(f"Город успешно изменен на: <b>{city_raw}</b> (Часовой пояс: {tz_str})", reply_markup=kb, parse_mode="HTML")
    await state.clear()


@dp.callback_query(F.data == "set_level")
async def set_level_menu(callback: types.CallbackQuery) -> None:
    if not await ensure_onboarded_callback(callback):
        return
    reset_inactivity_flag(callback.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌱 Аль-Фард", callback_data="changelevel_alfard")],
        [InlineKeyboardButton(text="🌿 Аль-Истикама", callback_data="changelevel_alistikama")],
        [InlineKeyboardButton(text="🌳 Ат-Тазаккия", callback_data="changelevel_attazkiya")],
        [InlineKeyboardButton(text="🌟 Аль-Ихсан", callback_data="changelevel_alihsan")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_settings")]
    ])
    await callback.message.edit_text("Выберите фокус сопровождения:", reply_markup=kb)
    await callback.answer()


@dp.callback_query(F.data.startswith("changelevel_"))
async def change_level_finish(callback: types.CallbackQuery) -> None:
    if not await ensure_onboarded_callback(callback):
        return
    reset_inactivity_flag(callback.from_user.id)
    level = callback.data.split("_")[1]
    update_user(callback.from_user.id, current_level=level)
    kb = get_main_menu_keyboard()
    await callback.message.edit_text("Фокус сопровождения успешно изменен!", reply_markup=kb)
    await callback.answer()


@dp.callback_query(F.data == "toggle_pause")
async def toggle_pause_handler(callback: types.CallbackQuery) -> None:
    if not await ensure_onboarded_callback(callback):
        return
    reset_inactivity_flag(callback.from_user.id)
    user = get_user(callback.from_user.id)
    is_paused = user.get("pause_mode", False)
    if is_paused:
        resume_mode(callback.from_user.id)
        await callback.answer("Пауза отключена. С возвращением!")
    else:
        pause_mode(callback.from_user.id, reason="Пользовательская пауза")
        await callback.answer("Деликатная пауза включена.")
    await menu_settings(callback)


@dp.callback_query(F.data.in_({"inact_time", "inact_hard", "inact_pause"}))
async def inactivity_reason_callback(callback: types.CallbackQuery) -> None:
    if not await ensure_onboarded_callback(callback):
        return
    reset_inactivity_flag(callback.from_user.id)
    if callback.data == "inact_pause":
        pause_mode(callback.from_user.id, reason="Авто-пауза из-за неактивности")
    kb = get_main_menu_keyboard()
    await callback.message.edit_text("Спасибо, что поделились. Мы всегда рады вашему возвращению!", reply_markup=kb)
    await callback.answer()


@dp.callback_query(F.data.in_({"mood_good", "mood_normal", "mood_hard"}))
async def mood_selected(callback: types.CallbackQuery) -> None:
    if not await ensure_onboarded_callback(callback):
        return
    reset_inactivity_flag(callback.from_user.id)
    mood_texts = {
        "mood_good": "Хорошо",
        "mood_normal": "Обычно",
        "mood_hard": "Тяжело"
    }
    text = mood_texts.get(callback.data, "Обычно")
    save_reflection(callback.from_user.id, f"Настроение: {text}")
    kb = get_main_menu_keyboard()
    await callback.message.edit_text("Альхамдулиллах за каждый день. Ваша рефлексия сохранена.", reply_markup=kb)
    await callback.answer()


@dp.callback_query(F.data == "friday_kahf_done")
async def friday_kahf_done(callback: types.CallbackQuery) -> None:
    if not await ensure_onboarded_callback(callback):
        return
    save_quran(callback.from_user.id, 10)
    await callback.message.edit_text("МашаАллах! Пусть чтение суры Аль-Кахф принесет свет между двумя пятницами 🤍", reply_markup=get_main_menu_keyboard())
    await callback.answer("Принято!")


@dp.callback_query(F.data == "friday_salawat_done")
async def friday_salawat_done(callback: types.CallbackQuery) -> None:
    if not await ensure_onboarded_callback(callback):
        return
    save_tasbih(callback.from_user.id, "salawat_count", 100)
    await callback.message.edit_text("МашаАллах! Салаваты Пророку ﷺ записаны. Пусть они станут вашим заступником 🤍", reply_markup=get_main_menu_keyboard())
    await callback.answer("Салаваты сохранены!")


@dp.callback_query(F.data == "friday_later")
async def friday_later(callback: types.CallbackQuery) -> None:
    if not await ensure_onboarded_callback(callback):
        return
    await callback.message.edit_text("Хорошо. Главное — помните, что бот предлагает, но не навязывает. Возвращайтесь, когда будет удобно 🤍", reply_markup=get_main_menu_keyboard())
    await callback.answer()


@dp.callback_query(F.data.startswith("notif_pr_"))
async def notif_prayer_done(callback: types.CallbackQuery) -> None:
    if not await ensure_onboarded_callback(callback):
        return
    reset_inactivity_flag(callback.from_user.id)
    code_map = {
        "fajr": "Фаджр",
        "dhuhr": "Зухр",
        "asr": "Аср",
        "maghrib": "Магриб",
        "isha": "Иша",
        "tahajjud": "Тахаджуд"
    }
    key = callback.data.split("_")[2]
    prayer_name = code_map.get(key, "Намаз")
    save_prayer(callback.from_user.id, prayer_name)
    await callback.message.edit_text(f"МашаАллах! Намаз <b>{prayer_name}</b> отмечен как выполненный 🤍", parse_mode="HTML")
    await callback.answer("Сохранено!")


async def check_inactivity() -> None:
    users = get_all_active_users()
    now = datetime.now(timezone.utc)
    for user in users:
        telegram_id = user.get("telegram_id")
        last_active_str = user.get("last_active")
        if last_active_str:
            try:
                last_active = datetime.fromisoformat(last_active_str)
                if (now - last_active) > timedelta(days=3):
                    if telegram_id in inactivity_notified:
                        continue
                    inactivity_notified.add(telegram_id)
                    kb = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🌿 Не было времени", callback_data="inact_time")],
                        [InlineKeyboardButton(text="😔 Было тяжело", callback_data="inact_hard")],
                        [InlineKeyboardButton(text="🤲 Нужна пауза", callback_data="inact_pause")],
                        [InlineKeyboardButton(text="❤️ Просто вернуться", callback_data="go_to_main")]
                    ])
                    await bot.send_message(telegram_id, "Ассаляму алейкум.\nМы заметили, что Вас давно не было. Надеемся, что у Вас всё хорошо.\nХотите рассказать, что стало причиной паузы?", reply_markup=kb, parse_mode="HTML")
            except Exception as e:
                logging.error(f"Error checking inactivity: {e}")


async def send_evening_reflections() -> None:
    users = get_all_active_users()
    for user in users:
        tz_str = user.get("timezone")
        try:
            local_tz = ZoneInfo(tz_str) if tz_str else timezone.utc
        except Exception:
            local_tz = timezone.utc
        now_local = datetime.now(local_tz)
        
        if now_local.weekday() == 4:
            try:
                await bot.send_message(user.get("telegram_id"), "✨ <b>Благословенная пятница завершается.</b>\n\nПусть всё совершённое сегодня станет причиной довольства Аллаха и принесёт баракат в Вашу жизнь 🤍", parse_mode="HTML")
            except Exception:
                pass
            continue

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="😊 Хорошо", callback_data="mood_good"),
             InlineKeyboardButton(text="😐 Обычно", callback_data="mood_normal")],
            [InlineKeyboardButton(text="😔 Тяжело", callback_data="mood_hard")]
        ])
        try:
            await bot.send_message(user.get("telegram_id"), "Как прошёл Ваш сегодняшний день?", reply_markup=kb, parse_mode="HTML")
        except Exception as e:
            logging.error(f"Error sending reflection trigger: {e}")


async def schedule_daily_prayer_notifications() -> None:
    users = get_all_active_users()
    now_utc = datetime.now(timezone.utc)
    prayer_keys = [("Fajr", "Фаджр", "fajr"), ("Dhuhr", "Зухр", "dhuhr"), ("Asr", "Аср", "asr"), ("Maghrib", "Магриб", "maghrib"), ("Isha", "Иша", "isha")]
    
    for user in users:
        city = user.get("city")
        tz_str = user.get("timezone")
        if not city or not tz_str:
            continue
            
        telegram_id = user.get("telegram_id")
        user_id = user.get("id")
        level = user.get("current_level", "alfard")
        
        try:
            local_tz = ZoneInfo(tz_str)
        except Exception:
            local_tz = timezone.utc
            
        now_local = datetime.now(local_tz)
        local_date_str = now_local.date().isoformat()
        is_friday = (now_local.weekday() == 4)
        
        data = await fetch_prayer_data(city, local_date_str)
        timings = data.get("timings", {})
        if not timings:
            continue
            
        for api_key, p_name, p_code in prayer_keys:
            p_time_str = timings.get(api_key)
            if not p_time_str:
                continue
            try:
                p_hour, p_min = map(int, p_time_str.split(":"))
                prayer_local_dt = now_local.replace(hour=p_hour, minute=p_min, second=0, microsecond=0)
                prayer_utc_dt = prayer_local_dt.astimezone(timezone.utc)
                
                if prayer_utc_dt <= now_utc:
                    continue
                
                if is_friday and p_code == "fajr":
                    job_id_friday = f"friday_fajr_{telegram_id}"
                    friday_kb = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="📖 Читаю Аль-Кахф", callback_data="friday_kahf_done")],
                        [InlineKeyboardButton(text="🤍 Салават", callback_data="friday_salawat_done")],
                        [InlineKeyboardButton(text="➡️ Позже", callback_data="friday_later")]
                    ])
                    friday_text = (
                        "🌙 <b>Благословенная пятница</b>\n\n"
                        "Сегодня лучший день недели.\n"
                        "📖 Не забудьте прочитать или послушать суру Аль-Кахф.\n"
                        "🤍 Уделите больше времени салаватам Пророку ﷺ."
                    )
                    scheduler.add_job(
                        send_prayer_reminder,
                        "date",
                        run_date=prayer_utc_dt + timedelta(minutes=10),
                        args=[telegram_id, friday_text, friday_kb],
                        id=job_id_friday,
                        replace_existing=True
                    )

                if is_friday and p_code == "dhuhr":
                    job_id_jumuah = f"friday_jumuah_{telegram_id}"
                    jumuah_kb = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🕌 Отметить Зухр", callback_data="notif_pr_dhuhr")],
                        [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="go_to_main")]
                    ])
                    jumuah_text = (
                        "🕌 <b>Сегодня пятница.</b>\n\n"
                        "Постарайтесь воспользоваться благословением этого дня.\n"
                        "Пусть Аллах примет Ваши дуа и благие дела 🤍"
                    )
                    scheduler.add_job(
                        send_prayer_reminder,
                        "date",
                        run_date=prayer_utc_dt - timedelta(minutes=15),
                        args=[telegram_id, jumuah_text, jumuah_kb],
                        id=job_id_jumuah,
                        replace_existing=True
                    )

                job_id_before = f"p_before_{telegram_id}_{p_code}"
                kb_before = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text=f"✅ Отметить {p_name}", callback_data=f"notif_pr_{p_code}")]
                ])
                reminder_text = f"⏰ Скоро наступит время намаза: <b>{p_name}</b> (через 5 минут). Подготовьтесь к омовению."
                
                if level == "alistikama" and p_code == "fajr":
                    reminder_text += "\n🌿 *Аль-Истикама:* Постоянство — ключ к довольству Аллаха."
                elif level == "attazkiya" and p_code == "asr":
                    reminder_text += "\n🌳 *Ат-Тазаккия:* Уделите минуту очищению сердца и поминанию."
                elif level == "alihsan" and p_code == "isha":
                    reminder_text += "\n🌟 *Аль-Ихсан:* Предстаньте перед Аллахом так, будто видите Его."

                scheduler.add_job(
                    send_prayer_reminder,
                    "date",
                    run_date=prayer_utc_dt - timedelta(minutes=5),
                    args=[telegram_id, reminder_text, kb_before],
                    id=job_id_before,
                    replace_existing=True
                )
                
                job_id_after = f"p_after_{telegram_id}_{p_code}"
                scheduler.add_job(
                    check_and_remind,
                    "date",
                    run_date=prayer_utc_dt + timedelta(minutes=20),
                    args=[telegram_id, user_id, p_name, p_code],
                    id=job_id_after,
                    replace_existing=True
                )
            except Exception as e:
                logging.error(f"Error scheduling prayer notification for user {telegram_id}: {e}")


async def handle_health(request):
    return web.Response(text="Amal365 Bot is running 🤍")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_health)
    app.router.add_get("/health", handle_health)
    
    port = int(os.getenv("PORT", 10000))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"Web server started successfully on port {port}")


async def main() -> None:
    await start_web_server()

    scheduler.add_job(check_inactivity, "cron", hour=10, minute=0)
    scheduler.add_job(send_evening_reflections, "cron", hour=21, minute=0)
    scheduler.add_job(schedule_daily_prayer_notifications, "cron", hour=1, minute=0)
    
    scheduler.add_job(schedule_daily_prayer_notifications, "date", run_date=datetime.now(timezone.utc) + timedelta(seconds=5))
    
    scheduler.start()
    
    logging.info("Bot started successfully...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
