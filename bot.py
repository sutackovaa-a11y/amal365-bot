# bot.py
import asyncio
import logging
import os
import sys
import random
import requests
from datetime import datetime, timezone, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from dotenv import load_dotenv
from aiohttp import web
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from database import (
    create_user, get_user, update_user, save_prayer,
    save_adhkar, save_tasbih, save_quran, save_books,
    save_activity, save_reflection, get_stats, pause_mode, resume_mode,
    get_all_active_users
)

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", 10000))

if not TOKEN:
    raise ValueError("BOT_TOKEN is missing in environment variables.")

bot = Bot(token=TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler(timezone="UTC")

class OnboardingStates(StatesGroup):
    waiting_for_language = State()
    waiting_for_city = State()
    waiting_for_mode = State()

class SettingsStates(StatesGroup):
    waiting_for_new_city = State()

class TasbihStates(StatesGroup):
    choosing_target = State()
    counting = State()

class QuranStates(StatesGroup):
    entering_pages = State()

class BooksStates(StatesGroup):
    entering_pages = State()

class ActivityStates(StatesGroup):
    entering_data = State()

HADITHS = {
    "Фаджр": [
        "Два раката Фаджра лучше мира и всего, что в нём. (Муслим)",
        "Тот, кто совершил утренний намаз, находится под защитой Аллаха. (Муслим)",
        "Ангелы ночи и дня сменяют друг друга во время утреннего и предвечернего намазов. (Бухари)"
    ],
    "Зухр": [
        "Поистине, врата небес открываются перед полуденным намазом. (Тирмизи)",
        "Совершайте намаз вовремя — это самое любимое деяние Аллаха. (Бухари)",
        "Тот, кто бережёт четыре раката до Зухра и четыре после, защищен от огня. (Абу Дауд)"
    ],
    "Аср": [
        "Тот, кто совершит намазы в прохладное время суток (Фаджр и Аср), войдёт в Рай. (Бухари)",
        "Не пропускайте предсказанный и благословенный предвечерний намаз.",
        "Тот, у кого пропадет Аср-намаз, словно лишился семьи и имущества. (Бухари)"
    ],
    "Магриб": [
        "Спешите совершить вечерний намаз до того, как появятся яркие звезды. (Абу Дауд)",
        "Магриб — время завершения дня в поминании Всевышнего.",
        "Мольба между Азаном и Икамой не отвергается."
    ],
    "Иша": [
        "Тот, кто совершил ночной намаз (Иша) с коллективом, словно выстаивал половину ночи. (Муслим)",
        "Иша дарует сердцу покой перед ночным отдыхом.",
        "Тяжелее всего лицемерам совершать Фаджр и Иша. (Бухари)"
    ],
    "Тахаджуд": [
        "Лучший намаз после обязательных — это ночной намаз. (Муслим)",
        "Господь наш нисходит каждую ночь к небесам ближним в последнюю треть ночи... (Бухари)",
        "Выстаивайте ночную молитву, ибо это путь праведников до вас. (Тирмизи)"
    ]
}

COMPANION_STORIES = [
    "1. Абу Бакр ас-Сиддик — сподвижник, который отдал всё своё имущество ради ислама и был назван самым верным другом Пророка ﷺ.",
    "2. Умар ибн аль-Хаттаб — символ справедливости, силы и твердости веры.",
    "3. Усман ибн Аффан — обладатель двух светочей, щедрейший благотворитель и собиратель Корана.",
    "4. Али ибн Абу Талиб — врата знаний, храбрости и преданности с юных лет.",
    "5. Билал ибн Рабах — муэдзин Посланника Аллаха ﷺ, выдержавший жесточайшие пытки ради единобожия.",
    "6. Му‘аз ибн Джабаль — сподвижник, которого Пророк ﷺ назвал лучшим знатоком дозволенного и запретного.",
    "7. Халид ибн аль-Валид — меч Аллаха разящий, великий полководец, принявший ислам сердцем.",
    "8. Са‘д ибн Абу Вакасс — сподвижник, чьи мольбы всегда принимались Всевышним.",
    "9. Абдуррахман ибн Ауф — один из богатейших торговцев Медины, отдававший всё ради довольства Аллаха.",
    "10. Зубайр ибн аль-Аввам — верный сподвижник, названный Пророком ﷺ своим сподвижником (Хавари).",
    "11. Тальха ибн Убайдуллах — живой мученик битвы при Ухуде, защищавший Пророка ﷺ своим телом.",
    "12. Абу Убайда ибн аль-Джаррах — доверенное лицо этой общины.",
    "13. Сальман аль-Фариси — искатель истинного света, предложивший вырыть ров при осаде Медины.",
    "14. Аммар ибн Ясир — терпеливый мученик, чьи родители первыми приняли мученическую смерть в исламе.",
    "15. Абу Зарр аль-Гифари — аскет, защищавший бедняков и живший в скромности.",
    "16. Абдуллах ибн Мас‘уд — знаток Корана, начавший читать его вслух открыто перед курайшитами.",
    "17. Анас ибн Малик — слуга Пророка ﷺ на протяжении 10 лет, проживший долгую благословенную жизнь.",
    "18. Абдуллах ибн Аббас — переводчик Корана и океан знаний этой общины благодаря мольбе Пророка ﷺ.",
    "19. Убай ибн Ка‘б — чтец Корана, которого Пророк ﷺ выделил за прекрасное знание Книги.",
    "20. Зайд ибн Сабит — главный писец откровений и составитель единого списка Корана."
]

def get_random_hadith(prayer_name: str) -> str:
    list_h = HADITHS.get(prayer_name, ["Поминайте Аллаха в любое время."])
    return random.choice(list_h)

def get_random_story() -> str:
    return random.choice(COMPANION_STORIES)

def get_prayer_times(city: str):
    try:
        url = f"https://api.aladhan.com/v1/timingsByCity?city={requests.utils.quote(city)}&country=&method=3"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            timings = data.get("data", {}).get("timings", {})
            return {
                "Фаджр": timings.get("Fajr", "05:00"),
                "Зухр": timings.get("Dhuhr", "13:00"),
                "Аср": timings.get("Asr", "16:30"),
                "Магриб": timings.get("Maghrib", "19:00"),
                "Иша": timings.get("Isha", "20:30")
            }
    except Exception as e:
        print(f"Error fetching prayer times: {e}")
    return {"Фаджр": "05:00", "Зухр": "13:00", "Аср": "16:30", "Магриб": "19:00", "Иша": "20:30"}

def calculate_time_left(target_time_str: str) -> str:
    try:
        now = datetime.now(timezone.utc)
        t_parts = target_time_str.split(":")
        target_hour = int(t_parts[0])
        target_minute = int(t_parts[1])
        
        target_dt = datetime.combine(now.date(), datetime.min.time(), tzinfo=timezone.utc).replace(hour=target_hour, minute=target_minute)
        if target_dt < now:
            target_dt += timedelta(days=1)
            
        diff = target_dt - now
        hours = int(diff.seconds // 3600)
        minutes = int((diff.seconds % 3600) // 60)
        return f"{hours} ч. {minutes} мин."
    except Exception:
        return "несколько часов"

def get_next_prayer_info(times: dict):
    now = datetime.now(timezone.utc).time()
    prayer_order = [("Фаджр", times["Фаджр"]), ("Зухр", times["Зухр"]), ("Аср", times["Аср"]), ("Магриб", times["Магриб"]), ("Иша", times["Иша"])]
    
    for name, t_str in prayer_order:
        try:
            parts = t_str.split(":")
            t_obj = datetime.strptime(f"{parts[0]}:{parts[1]}", "%H:%M").time()
            if now < t_obj:
                time_left = calculate_time_left(t_str)
                return name, t_str, time_left
        except Exception:
            continue
    # Если все прошли, то следующий Фаджр завтра
    return "Фаджр", times["Фаджр"], calculate_time_left(times["Фаджр"])

# --- KEYBOARDS ---
def kb_onboard_start():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤲 Начать", callback_data="onboard_step_2")]
    ])

def kb_onboard_bismillah():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤲 Продолжить с Бисмиллях", callback_data="onboard_lang")]
    ])

def kb_languages():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang_ru")],
        [InlineKeyboardButton(text="🇬🇧 English", callback_data="lang_en")]
    ])

def kb_modes():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌱 Аль-Фард (Обязательное)", callback_data="mode_alfard")],
        [InlineKeyboardButton(text="🌿 Аль-Истикама (Постоянство)", callback_data="mode_alistikama")],
        [InlineKeyboardButton(text="📖 Ат-Тазкия (Очищение души)", callback_data="mode_attazkiya")],
        [InlineKeyboardButton(text="⭐ Аль-Ихсан (Совершенствование)", callback_data="mode_alihsan")]
    ])

def kb_main_menu(mode: str = "alfard"):
    buttons = [
        [InlineKeyboardButton(text="✨ Шаг дня", callback_data="menu_daily_step"),
         InlineKeyboardButton(text="📿 Тасбих и Салават", callback_data="menu_tasbih")],
        [InlineKeyboardButton(text="⏰ Время намаза", callback_data="menu_prayers"),
         InlineKeyboardButton(text="🌅 Азкары", callback_data="menu_adhkar")],
        [InlineKeyboardButton(text="📖 Истории сподвижников", callback_data="menu_stories"),
         InlineKeyboardButton(text="📊 Мой путь", callback_data="menu_path")],
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data="menu_settings")]
    ]
    if mode in ["attazkiya", "alihsan"]:
        buttons.insert(3, [InlineKeyboardButton(text="📖 Чтение Корана", callback_data="menu_quran")])
    if mode == "alihsan":
        buttons.insert(4, [InlineKeyboardButton(text="📚 Чтение книг", callback_data="menu_books"),
                            InlineKeyboardButton(text="🏃 Активность", callback_data="menu_activity")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# --- HANDLERS: ONBOARDING ---
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    create_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    text = (
        "✨ <b>Амаль 365</b>\n\n"
        "Ваш личный спутник на пути благих дел.\n\n"
        "Каждый день — маленький шаг ради довольства Аллаха."
    )
    await message.answer(text, reply_markup=kb_onboard_start(), parse_mode="HTML")

@dp.callback_query(F.data == "onboard_step_2")
async def onboard_2(callback: CallbackQuery):
    text = (
        "Ассаляму алейкум ва рахматуллахи ва баракятух.\n\n"
        "Этот бот создан для того, чтобы помогать Вам сохранять связь со Всевышним, укреплять полезные привычки и двигаться вперёд шаг за шагом.\n\n"
        "Ваши данные используются только для работы бота и не передаются третьим лицам."
    )
    await callback.message.edit_text(text, reply_markup=kb_onboard_bismillah(), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "onboard_lang")
async def onboard_lang(callback: CallbackQuery, state: FSMContext):
    await state.set_state(OnboardingStates.waiting_for_language)
    await callback.message.edit_text("Выберите язык / Choose language:", reply_markup=kb_languages(), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.startswith("lang_"))
async def process_lang(callback: CallbackQuery, state: FSMContext):
    lang = callback.data.split("_")[1]
    update_user(callback.from_user.id, language=lang)
    await state.set_state(OnboardingStates.waiting_for_city)
    text = "📍 Напишите название вашего города текстом (например: <i>Москва, Казань, Алматы, Бишкек, Нерюнгри</i>):"
    await callback.message.edit_text(text, parse_mode="HTML")
    await callback.answer()

@dp.message(OnboardingStates.waiting_for_city)
async def process_city(message: Message, state: FSMContext):
    city = message.text.strip()
    update_user(message.from_user.id, city=city)
    await state.set_state(OnboardingStates.waiting_for_mode)
    text = (
        f"Город <b>{city}</b> успешно сохранен! 📍\n\n"
        "<b>Выберите режим развития:</b>\n\n"
        "🌱 <b>Аль-Фард (Обязательное)</b> — 5 намазов, салават, зикр.\n"
        "🌿 <b>Аль-Истикама (Постоянство)</b> — 5 намазов, тахаджуд, салават, зикр.\n"
        "📖 <b>Ат-Тазкия (Очищение души)</b> — 5 намазов, тахаджуд, Коран, салават, зикр.\n"
        "⭐ <b>Аль-Ихсан (Совершенствование)</b> — полная практика, книги, активность."
    )
    await message.answer(text, reply_markup=kb_modes(), parse_mode="HTML")

@dp.callback_query(F.data.startswith("mode_"))
async def process_mode_callback(callback: CallbackQuery, state: FSMContext):
    try:
        mode_map = {
            "mode_alfard": "alfard",
            "mode_alistikama": "alistikama",
            "mode_attazkiya": "attazkiya",
            "mode_alihsan": "alihsan"
        }
        selected_mode = mode_map.get(callback.data, "alfard")
        update_user(callback.from_user.id, mode=selected_mode, current_level=selected_mode)
        await state.clear()
        
        user = get_user(callback.from_user.id)
        user_mode = user.get("mode", "alfard") if user else selected_mode
        text = "Альхамдулиллях! Регистрация завершена. Ваш путь начался 🤍"
        await callback.message.edit_text(text, reply_markup=kb_main_menu(user_mode), parse_mode="HTML")
        await callback.answer()
    except Exception as e:
        print(f"Error in process_mode_callback: {e}")
        await callback.message.answer("Произошла ошибка при сохранении режима. Пожалуйста, попробуйте еще раз.")

@dp.message(OnboardingStates.waiting_for_mode)
async def process_mode_text(message: Message, state: FSMContext):
    try:
        text_lower = message.text.lower()
        mode = "alfard"
        if "истикама" in text_lower:
            mode = "alistikama"
        elif "тазкия" in text_lower:
            mode = "attazkiya"
        elif "ихсан" in text_lower:
            mode = "alihsan"

        update_user(message.from_user.id, mode=mode, current_level=mode)
        await state.clear()
        
        user = get_user(message.from_user.id)
        user_mode = user.get("mode", "alfard") if user else mode
        text = "Альхамдулиллях! Регистрация завершена. Ваш путь начался 🤍"
        await message.answer(text, reply_markup=kb_main_menu(user_mode), parse_mode="HTML")
    except Exception as e:
        print(f"Error in process_mode_text: {e}")
        await message.answer("Произошла ошибка при сохранении режима. Пожалуйста, попробуйте еще раз.")

# --- MAIN MENU & SECTIONS ---
@dp.callback_query(F.data == "go_to_main")
async def go_to_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user = get_user(callback.from_user.id)
    mode = user.get("mode", "alfard") if user else "alfard"
    streak = user.get("streak_days", 1) if user else 1
    text = (
        f"Главное меню 🌙\n\n"
        f"🔥 Текущая серия: <b>{streak} дней</b>\n"
        f"🌱 Режим: <b>{mode.upper()}</b>"
    )
    await callback.message.edit_text(text, reply_markup=kb_main_menu(mode), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "menu_daily_step")
async def menu_daily_step(callback: CallbackQuery):
    text = (
        "✨ <b>Шаг дня</b>\n\n"
        "«Самые любимые деяния перед Аллахом — это те, которые совершаются постоянно, даже если они малы.» (Бухари)\n\n"
        "Совершите сегодня чуть больше в благих делах и уделите время сердцу."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="go_to_main")]])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "menu_prayers")
async def menu_prayers(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    city = user.get("city", "Москва") if user else "Москва"
    times = get_prayer_times(city)
    
    next_name, next_t, time_left = get_next_prayer_info(times)
    
    fajr = "✓" if user and user.get("fajr_done") else "⏳"
    dhuhr = "✓" if user and user.get("dhuhr_done") else "⏳"
    asr = "✓" if user and user.get("asr_done") else "⏳"
    maghrib = "✓" if user and user.get("maghrib_done") else "⏳"
    isha = "✓" if user and user.get("isha_done") else "⏳"
    tahajjud = "✓" if user and user.get("tahajjud_done") else "⏳"
    
    text = (
        f"⏰ <b>Время намаза ({city})</b>\n\n"
        f"🌅 Фаджр ({times['Фаджр']}) — {fajr}\n"
        f"☀️ Зухр ({times['Зухр']}) — {dhuhr}\n"
        f"💧 Аср ({times['Аср']}) — {asr}\n"
        f"🌇 Магриб ({times['Магриб']}) — {maghrib}\n"
        f"🌙 Иша ({times['Иша']}) — {isha}\n"
        f"🌌 Тахаджуд — {tahajjud}\n\n"
        f"⏳ <b>До намаза ({next_name}) осталось:</b> {time_left}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Фаджр", callback_data="mark_p_Фаджр"),
         InlineKeyboardButton(text="✅ Зухр", callback_data="mark_p_Зухр")],
        [InlineKeyboardButton(text="✅ Аср", callback_data="mark_p_Аср"),
         InlineKeyboardButton(text="✅ Магриб", callback_data="mark_p_Магриб")],
        [InlineKeyboardButton(text="✅ Иша", callback_data="mark_p_Иша"),
         InlineKeyboardButton(text="✅ Тахаджуд", callback_data="mark_p_Тахаджуд")],
        [InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="go_to_main")]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.startswith("mark_p_"))
async def mark_prayer_action(callback: CallbackQuery):
    prayer_name = callback.data.split("_")[2]
    save_prayer(callback.from_user.id, prayer_name)
    hadith = get_random_hadith(prayer_name)
    user = get_user(callback.from_user.id)
    city = user.get("city", "Москва") if user else "Москва"
    times = get_prayer_times(city)
    
    _, _, time_left = get_next_prayer_info(times)
    
    text = (
        f"МашаАллах 🤍\n\n"
        f"Пусть Аллах примет Ваш намаз: <b>{prayer_name}</b>.\n\n"
        f"📖 <i>{hadith}</i>\n\n"
        f"До следующего намаза осталось примерно: <b>{time_left}</b>."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🕌 К намазам", callback_data="menu_prayers")],
        [InlineKeyboardButton(text="🌙 В меню", callback_data="go_to_main")]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer("Намаз успешно отмечен!")

# --- TASBIH ---
@dp.callback_query(F.data == "menu_tasbih")
async def menu_tasbih(callback: CallbackQuery):
    text = (
        "📿 <b>Тасбих и Салават</b>\n\n"
        "Выберите желаемую цель для поминания:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="33 раза", callback_data="tasbih_target_33"),
         InlineKeyboardButton(text="100 раз", callback_data="tasbih_target_100")],
        [InlineKeyboardButton(text="500 раз", callback_data="tasbih_target_500"),
         InlineKeyboardButton(text="1000 раз", callback_data="tasbih_target_1000")],
        [InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="go_to_main")]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.startswith("tasbih_target_"))
async def tasbih_target_selected(callback: CallbackQuery):
    target = int(callback.data.split("_")[2])
    text = (
        f"📿 <b>Тасбих (Цель: {target})</b>\n\n"
        "Поминайте Аллаха сердцем и языком.\n"
        "Нажимайте на кнопку ниже, чтобы считать:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"➕ Сделать зикр (0 / {target})", callback_data=f"t_count_{target}_0")],
        [InlineKeyboardButton(text="⬅️ В меню", callback_data="go_to_main")]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.startswith("t_count_"))
async def tasbih_counter(callback: CallbackQuery):
    _, _, target_str, current_str = callback.data.split("_")
    target = int(target_str)
    current = int(current_str) + 1
    
    if current >= target:
        save_tasbih(callback.from_user.id, target)
        text = f"🎉 МашаАллах! Вы выполнили цель в {target} раз(а).\nПусть Аллах примет ваше поминание 🤍"
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🌙 В меню", callback_data="go_to_main")]])
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    else:
        text = (
            f"📿 <b>Тасбих (Цель: {target})</b>\n\n"
            f"Прогресс: <b>{current} / {target}</b>"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"➕ Сделать зикр ({current} / {target})", callback_data=f"t_count_{target}_{current}")],
            [InlineKeyboardButton(text="⬅️ В меню", callback_data="go_to_main")]
        ])
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

# --- ADHKAR ---
@dp.callback_query(F.data == "menu_adhkar")
async def menu_adhkar(callback: CallbackQuery):
    text = (
        "🌅 <b>Азкары дня</b>\n\n"
        "Выберите раздел для чтения:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌅 Утренние азкары", callback_data="adhkar_morning"),
         InlineKeyboardButton(text="🌙 Вечерние азкары", callback_data="adhkar_evening")],
        [InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="go_to_main")]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.in_({"adhkar_morning", "adhkar_evening"}))
async def adhkar_read(callback: CallbackQuery):
    a_type = "morning" if "morning" in callback.data else "evening"
    save_adhkar(callback.from_user.id, a_type)
    text = (
        f"🤍 <b>{'Утренние' if a_type == 'morning' else 'Вечерние'} азкары успешно прочитаны и сохранены!</b>\n\n"
        "Пусть они станут защитой и светом для Вашего сердца."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🌙 В меню", callback_data="go_to_main")]])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer("Сохранено!")

# --- QURAN ---
@dp.callback_query(F.data == "menu_quran")
async def menu_quran(callback: CallbackQuery, state: FSMContext):
    await state.set_state(QuranStates.entering_pages)
    text = "📖 <b>Чтение Корана</b>\n\nВведите количество прочитанных страниц за сегодня цифрой:"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data="go_to_main")]])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.message(QuranStates.entering_pages)
async def process_quran_pages(message: Message, state: FSMContext):
    try:
        pages = int(message.text.strip())
        save_quran(message.from_user.id, pages)
        await state.clear()
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🌙 В меню", callback_data="go_to_main")]])
        await message.answer(f"Альхамдулиллях! Добавлено {pages} страниц Корана 🤍", reply_markup=kb, parse_mode="HTML")
    except ValueError:
        await message.answer("Пожалуйста, введите корректное число страниц цифрой.")

# --- BOOKS ---
@dp.callback_query(F.data == "menu_books")
async def menu_books(callback: CallbackQuery, state: FSMContext):
    await state.set_state(BooksStates.entering_pages)
    text = "📚 <b>Чтение исламских книг</b>\n\nВведите количество прочитанных страниц цифрой:"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data="go_to_main")]])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.message(BooksStates.entering_pages)
async def process_books_pages(message: Message, state: FSMContext):
    try:
        pages = int(message.text.strip())
        save_books(message.from_user.id, pages)
        await state.clear()
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🌙 В меню", callback_data="go_to_main")]])
        await message.answer(f"Альхамдулиллях! Записано {pages} страниц книг 🤍", reply_markup=kb, parse_mode="HTML")
    except ValueError:
        await message.answer("Пожалуйста, введите число страниц цифрой.")

# --- ACTIVITY ---
@dp.callback_query(F.data == "menu_activity")
async def menu_activity(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ActivityStates.entering_data)
    text = "🏃 <b>Физическая активность</b>\n\nВведите количество пройденных шагов за сегодня цифрой:"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data="go_to_main")]])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.message(ActivityStates.entering_data)
async def process_activity(message: Message, state: FSMContext):
    try:
        steps = int(message.text.strip())
        save_activity(message.from_user.id, steps=steps)
        await state.clear()
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🌙 В меню", callback_data="go_to_main")]])
        await message.answer(f"Альхамдулиллях! Записано {steps} шагов 🤍", reply_markup=kb, parse_mode="HTML")
    except ValueError:
        await message.answer("Пожалуйста, введите корректное число шагов.")

# --- COMPANION STORIES ---
@dp.callback_query(F.data == "menu_stories")
async def menu_stories(callback: CallbackQuery):
    story = get_random_story()
    text = f"📖 <b>Истории сподвижников</b>\n\n{story}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Другая история", callback_data="menu_stories")],
        [InlineKeyboardButton(text="⬅️ В меню", callback_data="go_to_main")]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

# --- PATH / STATS ---
@dp.callback_query(F.data == "menu_path")
async def menu_path(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    streak = user.get("streak_days", 1) if user else 1
    mode = user.get("mode", "alfard") if user else "alfard"
    quran = user.get("quran_pages", 0) if user else 0
    books = user.get("books_pages", 0) if user else 0
    steps = user.get("activity_steps", 0) if user else 0
    tasbih = user.get("tasbih_count", 0) if user else 0
    
    text = (
        f"📊 <b>Мой путь</b>\n\n"
        f"🔥 Серия: <b>{streak} дней</b>\n"
        f"🌱 Режим: <b>{mode.upper()}</b>\n"
        f"📖 Страниц Корана: {quran}\n"
        f"📚 Страниц книг: {books}\n"
        f"🏃 Шаги: {steps}\n"
        f"📿 Зикры и салават: {tasbih}\n\n"
        "<i>«Каждый шаг на пути к Аллаху приближает к милости Его.»</i>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="go_to_main")]])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

# --- SETTINGS & PAUSE & CITY CHANGE ---
@dp.callback_query(F.data == "menu_settings")
async def menu_settings(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    paused = user.get("pause_mode", False) if user else False
    city = user.get("city", "Москва") if user else "Москва"
    pause_text = "🟢 Активен" if not paused else "🌷 На паузе"
    
    text = (
        f"⚙️ <b>Настройки</b>\n\n"
        f"📍 Город: <b>{city}</b>\n"
        f"Статус: {pause_text}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📍 Изменить город", callback_data="settings_change_city")],
        [InlineKeyboardButton(text="🌷 Включить деликатную паузу" if not paused else "🌿 Выключить паузу", callback_data="toggle_pause")],
        [InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="go_to_main")]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "settings_change_city")
async def settings_change_city(callback: CallbackQuery, state: FSMContext):
    await state.set_state(SettingsStates.waiting_for_new_city)
    text = "📍 Напишите новый город текстом (например: <i>Нерюнгри, Санкт-Петербург, Казань</i>):"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад в настройки", callback_data="menu_settings")]])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.message(SettingsStates.waiting_for_new_city)
async def process_new_city(message: Message, state: FSMContext):
    new_city = message.text.strip()
    update_user(message.from_user.id, city=new_city)
    await state.clear()
    
    user = get_user(message.from_user.id)
    mode = user.get("mode", "alfard") if user else "alfard"
    text = f"Альхамдулиллях! Город успешно изменен на <b>{new_city}</b> 🤍"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🌙 В меню", callback_data="go_to_main")]])
    await message.answer(text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data == "toggle_pause")
async def toggle_pause(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    paused = user.get("pause_mode", False) if user else False
    if paused:
        resume_mode(callback.from_user.id)
        msg = "Деликатная пауза выключена. Добро пожаловать обратно! 🤍"
    else:
        pause_mode(callback.from_user.id, reason="Пользователь включил паузу")
        msg = "Деликатная пауза включена. Ваши серии и прогресс сохранены, уведомления приостановлены. Отдыхайте 🌷"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🌙 В меню", callback_data="go_to_main")]])
    await callback.message.edit_text(msg, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

# --- EVENING REFLECTION HANDLERS ---
@dp.callback_query(F.data.startswith("mood_"))
async def process_mood(callback: CallbackQuery):
    mood = callback.data.split("_")[1]
    save_reflection(callback.from_user.id, mood)
    text = "Альхамдулиллях за каждый прожитый день. Пусть Аллах дарует вам благословенную ночь 🤍"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🌙 В меню", callback_data="go_to_main")]])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer("Спасибо за ответ!")

# --- ADAPTIVE GROWTH & INACTIVITY TASKS ---
async def check_adaptive_milestones():
    users = get_all_active_users()
    for user in users:
        streak = user.get("streak_days", 1)
        level = user.get("current_level", "alfard")
        telegram_id = user.get("telegram_id")
        
        if streak == 40 and level == "alfard":
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➡️ Перейти на Истикама", callback_data="upgrade_alistikama")],
                [InlineKeyboardButton(text="🕊 Остаться здесь", callback_data="stay_here")]
            ])
            try:
                await bot.send_message(telegram_id, "МашаАллах. Вы сохраняете постоянство уже 40 дней.\nЕсли чувствуете готовность, можете перейти на уровень: <b>Аль-Истикама</b>.", reply_markup=kb, parse_mode="HTML")
            except Exception as e:
                print(f"Error sending milestone message: {e}")
        elif streak == 90 and level == "alistikama":
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➡️ Перейти на Ат-Тазкия", callback_data="upgrade_attazkiya")],
                [InlineKeyboardButton(text="🕊 Остаться здесь", callback_data="stay_here")]
            ])
            try:
                await bot.send_message(telegram_id, "МашаАллах. Вы уже 90 дней на пути постоянства.\nПредлагаем перейти на уровень очищения души: <b>Ат-Тазкия</b>.", reply_markup=kb, parse_mode="HTML")
            except Exception as e:
                print(f"Error sending milestone message: {e}")
        elif streak == 365 and level == "attazkiya":
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➡️ Перейти на Аль-Ихсан", callback_data="upgrade_alihsan")],
                [InlineKeyboardButton(text="🕊 Остаться здесь", callback_data="stay_here")]
            ])
            try:
                await bot.send_message(telegram_id, "МашаАллах! Целый год вместе. Вы достигли вершины.\nПредлагаем перейти на уровень: <b>Аль-Ихсан</b>.", reply_markup=kb, parse_mode="HTML")
            except Exception as e:
                print(f"Error sending milestone message: {e}")

@dp.callback_query(F.data.startswith("upgrade_"))
async def upgrade_mode(callback: CallbackQuery):
    new_mode = callback.data.split("_")[1]
    update_user(callback.from_user.id, mode=new_mode, current_level=new_mode)
    text = f"Поздравляем! Ваш режим успешно изменен на <b>{new_mode.upper()}</b> 🤍"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🌙 В меню", callback_data="go_to_main")]])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "stay_here")
async def stay_mode(callback: CallbackQuery):
    text = "Хорошо, продолжайте в вашем комфортном темпе 🤍"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🌙 В меню", callback_data="go_to_main")]])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

async def check_inactivity():
    users = get_all_active_users()
    now = datetime.now(timezone.utc)
    for user in users:
        last_active_str = user.get("last_active")
        if last_active_str:
            try:
                last_active = datetime.fromisoformat(last_active_str)
                if (now - last_active) > timedelta(days=3):
                    telegram_id = user.get("telegram_id")
                    kb = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🌿 Не было времени", callback_data="inact_time")],
                        [InlineKeyboardButton(text="😔 Было тяжело", callback_data="inact_hard")],
                        [InlineKeyboardButton(text="🤲 Нужна пауза", callback_data="inact_pause")],
                        [InlineKeyboardButton(text="❤️ Просто вернуться", callback_data="go_to_main")]
                    ])
                    await bot.send_message(telegram_id, "Ассаляму алейкум.\nМы заметили, что Вас давно не было. Надеемся, что у Вас всё хорошо.\nХотите рассказать, что стало причиной паузы?", reply_markup=kb, parse_mode="HTML")
            except Exception as e:
                print(f"Error checking inactivity: {e}")

@dp.callback_query(F.data.startswith("inact_"))
async def process_inactivity_response(callback: CallbackQuery):
    reason = callback.data.split("_")[1]
    reasons_map = {
        "time": "Не было времени",
        "hard": "Было тяжело",
        "pause": "Нужна пауза"
    }
    if reason in reasons_map:
        pause_mode(callback.from_user.id, reason=reasons_map[reason])
    text = "Мы всегда рядом и ждем вас в любое время. Пусть всё у вас складывается наилучшим образом 🤍"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🌙 В меню", callback_data="go_to_main")]])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

# --- EVENING REFLECTION TRIGGER JOB ---
async def send_evening_reflections():
    users = get_all_active_users()
    for user in users:
        telegram_id = user.get("telegram_id")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="😊 Хорошо", callback_data="mood_good"),
             InlineKeyboardButton(text="😐 Обычно", callback_data="mood_normal")],
            [InlineKeyboardButton(text="😔 Тяжело", callback_data="mood_hard")]
        ])
        try:
            await bot.send_message(telegram_id, "Как прошёл Ваш сегодняшний день?", reply_markup=kb, parse_mode="HTML")
        except Exception as e:
            print(f"Error sending reflection trigger: {e}")

# --- WEB SERVER FOR RENDER ---
async def handle(request):
    return web.Response(text="Amal365 Production Bot is running successfully!")

async def run_web_server():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

async def main():
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    print("Запуск бота Amal365 в продакшн-режиме...")
    
    scheduler.add_job(check_adaptive_milestones, "cron", hour=9, minute=0)
    scheduler.add_job(check_inactivity, "cron", hour=10, minute=0)
    scheduler.add_job(send_evening_reflections, "cron", hour=21, minute=0)
    scheduler.start()
    
    await asyncio.gather(
        run_web_server(),
        dp.start_polling(bot, drop_pending_updates=True)
    )

if __name__ == "__main__":
    asyncio.run(main())
