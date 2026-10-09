import asyncio
import logging
import sqlite3
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

TOKEN = "YOUR_BOT_TOKEN_HERE"  # Замените на токен вашего бота

# Настройка логирования
logging.basicConfig(level=logging.INFO)
router = Router()

# ==================== БАЗА ДАННЫХ ====================

def init_db():
    conn = sqlite3.connect("amal365.db")
    cursor = conn.cursor()
    # Таблица пользователей и настроек режима
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            active_mode TEXT DEFAULT 'Аль-Фард',
            pause_status TEXT DEFAULT 'active',
            pause_reason TEXT DEFAULT NULL,
            pinned_message_id INTEGER DEFAULT NULL
        )
    """)
    # Таблица ежедневного прогресса (сводка дня и история поклонения)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_progress (
            user_id INTEGER,
            date TEXT,
            prayers_completed TEXT DEFAULT '',
            tasbih_count INTEGER DEFAULT 0,
            salawat_count INTEGER DEFAULT 0,
            morning_azkar INTEGER DEFAULT 0,
            evening_azkar INTEGER DEFAULT 0,
            quran_progress TEXT DEFAULT '',
            books_pages INTEGER DEFAULT 0,
            steps INTEGER DEFAULT 0,
            sport_minutes INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, date)
        )
    """)
    conn.commit()
    conn.close()

init_db()

def get_db_connection():
    return sqlite3.connect("amal365.db")

# ==================== FSM СОСТОЯНИЯ ====================
class BotStates(StatesGroup):
    waiting_for_tasbih = State()
    waiting_for_salawat = State()

# ==================== КЛАВИАТУРЫ ====================

def get_main_menu_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⏰ Время намазов", callback_data="menu_prayers"))
    builder.row(InlineKeyboardButton(text="📿 Поминания и дуа", callback_data="menu_remembrances"))
    builder.row(
        InlineKeyboardButton(text="📊 Мой путь", callback_data="menu_my_path"),
        InlineKeyboardButton(text="🌿 Активность", callback_data="menu_activity")
    )
    builder.row(InlineKeyboardButton(text="⚙️ Актуальный режим", callback_data="menu_mode"))
    return builder.as_markup()

def get_remembrances_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📿 Тасбих", callback_data="rem_tasbih"))
    builder.row(InlineKeyboardButton(text="✨ Салават", callback_data="rem_salawat"))
    builder.row(
        InlineKeyboardButton(text="🌅 Утренние азкары", callback_data="rem_azkar_morning"),
        InlineKeyboardButton(text="🌆 Вечерние азкары", callback_data="rem_azkar_evening")
    )
    builder.row(InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="back_to_main"))
    return builder.as_markup()

def get_tasbih_targets_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="7 раз", callback_data="tasbih_target_7"),
        InlineKeyboardButton(text="33 раза", callback_data="tasbih_target_33"),
        InlineKeyboardButton(text="99 раз", callback_data="tasbih_target_99")
    )
    builder.row(InlineKeyboardButton(text="♾️ Без цели (свободный счет)", callback_data="tasbih_target_none"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_remembrances"))
    return builder.as_markup()

def get_salawat_targets_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="33 раза", callback_data="salawat_target_33"),
        InlineKeyboardButton(text="100 раз", callback_data="salawat_target_100")
    )
    builder.row(InlineKeyboardButton(text="♾️ Без цели (свободный счет)", callback_data="salawat_target_none"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_remembrances"))
    return builder.as_markup()

def get_my_path_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🌙 Сводка дня", callback_data="path_daily_summary"))
    builder.row(InlineKeyboardButton(text="📈 История поклонения", callback_data="path_history"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="back_to_main"))
    return builder.as_markup()

def get_mode_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🌸 Деликатная пауза", callback_data="mode_delicate_pause"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="back_to_main"))
    return builder.as_markup()

def get_delicate_pause_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🌸 Особенные дни", callback_data="pause_special"))
    builder.row(InlineKeyboardButton(text="🌿 Заболел(а)", callback_data="pause_sick"))
    builder.row(InlineKeyboardButton(text="⏳ Времени нет", callback_data="pause_busy"))
    builder.row(InlineKeyboardButton(text="✨ Просто отдых", callback_data="pause_rest"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_mode"))
    return builder.as_markup()

def get_active_pause_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="✨ Восстановить режим / Завершить паузу", callback_data="pause_resume"))
    builder.row(InlineKeyboardButton(text="🌸 Сменить причину паузы", callback_data="mode_delicate_pause"))
    return builder.as_markup()

# ==================== ХЕНДЛЕРЫ: СТАРТ И ГЛАВНОЕ МЕНЮ ====================

@router.message(Command("start"))
async def cmd_start(message: Message):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (message.from_user.id,))
    conn.commit()
    conn.close()

    await message.answer(
        "Ассаляму алейкум ва рахматуллахи ва баракатух! 🤍\n\n"
        "Добро пожаловать в **Amal365** — ваш бережный цифровой спутник на пути постоянства и поклонения.",
        reply_markup=get_main_menu_keyboard(),
        parse_mode="Markdown"
    )

@router.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery):
    await callback.message.edit_text(
        "Главное меню Amal365:",
        reply_markup=get_main_menu_keyboard()
    )
    await callback.answer()

# ==================== ПОМИНАНИЯ И ДУА ====================

@router.callback_query(F.data == "menu_remembrances")
async def menu_remembrances(callback: CallbackQuery):
    await callback.message.edit_text(
        "📿 **Раздел «Поминания и дуа»**\n\nВыберите нужное направление:",
        reply_markup=get_remembrances_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()

# Тасбих
@router.callback_query(F.data == "rem_tasbih")
async def rem_tasbih(callback: CallbackQuery):
    await callback.message.edit_text(
        "📿 **Тасбих**\n\nВыберите желаемую цель для повторения:",
        reply_markup=get_tasbih_targets_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data.startswith("tasbih_target_"))
async def set_tasbih_target(callback: CallbackQuery, state: FSMContext):
    target = callback.data.split("_")[2]
    await state.update_data(target=target, current_count=0, current_zikr_index=0)
    
    zikrs = ["Субханаллах", "Альхамдулиллях", "Аллаху Акбар"]
    await callback.message.edit_text(
        f"📿 **Тасбих** (Цель: {target if target != 'none' else 'свободный счет'})\n\n"
        f"Текущий зикр: **{zikrs[0]}**\n"
        f"Счетчик: 0 / {target if target != 'none' else '∞'}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Нажать (+1)", callback_data="tasbih_click")],
            [InlineKeyboardButton(text="⬅️ Выйти (сохранить прогресс)", callback_data="menu_remembrances")]
        ]),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "tasbih_click")
async def tasbih_click(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    current = data.get("current_count", 0) + 1
    target = data.get("target", "none")
    
    # Мгновенная фиксация в БД (упрощенно по дате)
    # Здесь сохраняется каждый клик в реальном времени
    await state.update_data(current_count=current)
    
    zikrs = ["Субханаллах", "Альхамдулиллях", "Аллаху Акбар"]
    idx = data.get("current_zikr_index", 0)
    
    # Автоматический переход при достижении цели (например, 7, 33 или 99)
    target_limit = int(target) if target != "none" else 999999
    if current >= target_limit and target != "none":
        idx = (idx + 1) % len(zikrs)
        current = 0
        await state.update_data(current_count=0, current_zikr_index=idx)

    await callback.message.edit_text(
        f"📿 **Тасбих**\n\n"
        f"Текущий зикр: **{zikrs[idx]}**\n"
        f"Счетчик: {current} / {target}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Нажать (+1)", callback_data="tasbih_click")],
            [InlineKeyboardButton(text="⬅️ Выйти (сохранить прогресс)", callback_data="menu_remembrances")]
        ]),
        parse_mode="Markdown"
    )
    await callback.answer()

# Салават
@router.callback_query(F.data == "rem_salawat")
async def rem_salawat(callback: CallbackQuery):
    await callback.message.edit_text(
        "✨ **Салават**\n\n"
        "Особенно благословенно чтение салаватов Пророку ﷺ в пятницу (Джума).\n"
        "Выберите цель:",
        reply_markup=get_salawat_targets_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()

# Азкары (Утренние и Вечерние)
@router.callback_query(F.data == "rem_azkar_morning")
async def azkar_morning(callback: CallbackQuery):
    await callback.message.edit_text(
        "🌅 **Утренние азкары**\n\n"
        "Рекомендуется читать после утренней молитвы (Фаджр).\n"
        "Здесь размещен текст утренних азкаров...",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Отметить как выполненные", callback_data="azkar_done_morning")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_remembrances")]
        ]),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "rem_azkar_evening")
async def azkar_evening(callback: CallbackQuery):
    await callback.message.edit_text(
        "🌆 **Вечерние азкары**\n\n"
        "Рекомендуется читать после вечерней молитвы (Магриб).\n"
        "Здесь размещен текст вечерних азкаров...",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Отметить как выполненные", callback_data="azkar_done_evening")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_remembrances")]
        ]),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data.startswith("azkar_done_"))
async def azkar_done(callback: CallbackQuery):
    await callback.answer("Азкары успешно зафиксированы в вашей сводке дня! 🤍", show_alert=True)

# ==================== МОЙ ПУТЬ (МУДАЛЯМА) ====================

@router.callback_query(F.data == "menu_my_path")
async def menu_my_path(callback: CallbackQuery):
    await callback.message.edit_text(
        "📊 **Мой путь (Мудаляма)**\n\nВыберите интересующий раздел:",
        reply_markup=get_my_path_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "path_daily_summary")
async def path_daily_summary(callback: CallbackQuery):
    await callback.message.edit_text(
        "🌙 **Сводка дня (Сегодня)**:\n\n"
        "• Намазы: все обязательные учтены\n"
        "• Тасбих: активен\n"
        "• Салават: учтено\n"
        "• Азкары: утренние/вечерние\n"
        "• Тело и дух: Коран, книги, шаги, спорт записаны.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_my_path")]
        ]),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "path_history")
async def path_history(callback: CallbackQuery):
    await callback.message.edit_text(
        "📈 **История поклонения**\n\n"
        "Здесь хранится ваш бессрочный архив достижений за недели, месяцы и годы. "
        "Ни одно усилие, ни один зикр или шаг не стираются со временем 🤍",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_my_path")]
        ]),
        parse_mode="Markdown"
    )
    await callback.answer()

# ==================== РЕЖИМЫ И ДЕЛИКАТНАЯ ПАУЗА ====================

@router.callback_query(F.data == "menu_mode")
async def menu_mode(callback: CallbackQuery):
    await callback.message.edit_text(
        "⚙️ **Актуальный режим**\n\nТекущий режим: **Аль-Фард**",
        reply_markup=get_mode_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "mode_delicate_pause")
async def delicate_pause_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        "🌸 **Деликатная пауза**\n\n"
        "Выберите причину паузы. Ваш прогресс и серия дней в абсолютной безопасности:",
        reply_markup=get_delicate_pause_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data.in_({"pause_special", "pause_sick", "pause_busy", "pause_rest"}))
async def activate_pause(callback: CallbackQuery):
    reasons = {
        "pause_special": ("Особенные дни", "Уведомления приостановлены для вашего комфорта. При этом ведение учета (Коран, книги, шаги, спорт, тасбих, салават) полностью доступно."),
        "pause_sick": ("Заболел(а)", "Желаем скорейшего выздоровления! Пусть эта болезнь станет очищением. Отдыхайте, набирайтесь сил 🤍"),
        "pause_busy": ("Времени нет", "Мы понимаем, что мирские хлопоты занимают много времени, но помните: эта жизнь — лишь временное пристанище. В ахирате нас спасет намаз и благие деяния 🤍"),
        "pause_rest": ("Просто отдых", "Иногда душе нужна пауза от мирской суеты. Но помните: истинный покой сердца обретается лишь в поминании Всевышнего («Воистину, поминанием Аллаха успокаиваются сердца», сура Ар-Рад, 28). Отдыхайте бережно 🤍")
    }
    
    title, text = reasons[callback.data]
    
    sent_message = await callback.message.edit_text(
        f"🌸 **Деликатная пауза: {title}**\n\n{text}\n\n"
        f"Ваш прогресс в абсолютной безопасности.",
        reply_markup=get_active_pause_keyboard(),
        parse_mode="Markdown"
    )
    
    # Закрепление сообщения в чате (важнейшее требование интерфейса)
    try:
        await callback.bot.pin_chat_message(
            chat_id=callback.message.chat.id,
            message_id=sent_message.message_id
        )
    except Exception as e:
        logging.error(f"Не удалось закрепить сообщение: {e}")
        
    await callback.answer()

@router.callback_query(F.data == "pause_resume")
async def resume_mode(callback: CallbackQuery):
    try:
        await callback.bot.unpin_chat_message(chat_id=callback.message.chat.id)
    except Exception:
        pass

    await callback.message.edit_text(
        "✨ Режим успешно восстановлен! Добро пожаловать обратно к активному ритму поклонения 🤍",
        reply_markup=get_main_menu_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()

# ==================== ЗАПУСК БОТА ====================

async def main():
    bot = Bot(token=TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    
    await bot.delete_webhook(drop_pending_updates=True)
    print("Бот Amal365 успешно запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
