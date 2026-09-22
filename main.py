import asyncio
import logging
import sqlite3
import os
import re
from aiohttp import web  # Render'da portni eshitib turish uchun
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    ContentType
)

# --- XAVFSIZ SOZLAMALAR (Environment Variables) ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID_RAW = os.getenv("ADMIN_ID", "8371392099")

if not BOT_TOKEN:
    raise ValueError("⚠️ BOT_TOKEN topilmadi! Iltimos, atrof-muhit o'zgaruvchisini (Environment Variable) sozlang.")

ADMIN_ID = int(ADMIN_ID_RAW)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

# --- MA'LUMOTLAR BAZASI (SQLite) ---
def init_db():
    conn = sqlite3.connect("history_bot.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            grade TEXT,
            topic TEXT,
            question_text TEXT,
            option_a TEXT,
            option_b TEXT,
            option_c TEXT,
            option_d TEXT,
            correct_option TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

# --- FSM (HOLATLAR) ---
class QuizState(StatesGroup):
    answering = State()

class AdminState(StatesGroup):
    waiting_for_file = State()
    delete_waiting_for_grade = State()
    delete_waiting_for_topic = State()

# --- KLAVIATURALAR ---
def get_main_menu(user_id: int):
    keyboard_buttons = [
        [KeyboardButton(text="8-sinf O'zbekiston tarixi"), KeyboardButton(text="9-sinf O'zbekiston tarixi")],
        [KeyboardButton(text="10-sinf O'zbekiston tarixi"), KeyboardButton(text="11-sinf O'zbekiston tarixi")]
    ]
    if user_id == ADMIN_ID:
        keyboard_buttons.append([KeyboardButton(text="⚙️ Admin Paneli")])

    return ReplyKeyboardMarkup(keyboard=keyboard_buttons, resize_keyboard=True)

def get_admin_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📁 TXT fayl orqali test yuklash")],
            [KeyboardButton(text="🗑 Mavzuni o'chirish"), KeyboardButton(text="📊 Statistika")],
            [KeyboardButton(text="⬅️ Bosh menyu")]
        ],
        resize_keyboard=True
    )

def get_topics_keyboard(grade: str):
    conn = sqlite3.connect("history_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT topic FROM questions WHERE grade = ?", (grade,))
    topics = cursor.fetchall()
    conn.close()

    buttons = []
    for t in topics:
        buttons.append([KeyboardButton(text=t[0])])
    buttons.append([KeyboardButton(text="⬅️ Bosh menyu")])
    
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

# --- BOSH MENYU HANDLERLARI ---

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Assalomu alaykum! O'zbekiston tarixi fanidan test botiga xush kelibsiz.\n\nSinfni tanlang:",
        reply_markup=get_main_menu(message.from_user.id)
    )

@router.message(F.text == "⬅️ Bosh menyu")
async def back_to_main(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Bosh menyu:", reply_markup=get_main_menu(message.from_user.id))

# --- ADMIN PANEL ---

@router.message(F.text == "⚙️ Admin Paneli")
async def admin_panel(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await message.answer("Siz admin emassiz!")
        return
    await state.clear()
    await message.answer("🛠 Admin paneliga xush kelibsiz!", reply_markup=get_admin_menu())

@router.message(F.text == "📊 Statistika")
async def show_stats(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    conn = sqlite3.connect("history_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM questions")
    total_q = cursor.fetchone()[0]
    
    cursor.execute("SELECT grade, COUNT(DISTINCT topic) FROM questions GROUP BY grade")
    by_grade = cursor.fetchall()
    conn.close()

    text = f"📊 **Bot statistikasi:**\n\nJami savollar soni: {total_q} ta\n\n**Sinflar va mavzular:**\n"
    for item in by_grade:
        text += f"• {item[0]}: {item[1]} ta mavzu bor\n"
    
    await message.answer(text, reply_markup=get_admin_menu(), parse_mode="Markdown")

# --- MAVZUNI O'CHIRISH FUNKSIYASI ---

@router.message(F.text == "🗑 Mavzuni o'chirish")
async def start_delete_topic(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    
    await state.set_state(AdminState.delete_waiting_for_grade)
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="8-sinf O'zbekiston tarixi"), KeyboardButton(text="9-sinf O'zbekiston tarixi")],
            [KeyboardButton(text="10-sinf O'zbekiston tarixi"), KeyboardButton(text="11-sinf O'zbekiston tarixi")],
            [KeyboardButton(text="⬅️ Bosh menyu")]
        ],
        resize_keyboard=True
    )
    await message.answer("Qaysi sinfga tegishli mavzuni o'chirmoqchisiz?", reply_markup=kb)

@router.message(AdminState.delete_waiting_for_grade)
async def delete_get_grade(message: Message, state: FSMContext):
    grade = message.text
    if grade == "⬅️ Bosh menyu":
        await state.clear()
        await message.answer("Bosh menyu:", reply_markup=get_main_menu(message.from_user.id))
        return

    kb = get_topics_keyboard(grade)
    
    conn = sqlite3.connect("history_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(DISTINCT topic) FROM questions WHERE grade = ?", (grade,))
    count = cursor.fetchone()[0]
    conn.close()

    if count == 0:
        await message.answer(f"{grade}da o'chirish uchun mavzular topilmadi.", reply_markup=get_admin_menu())
        await state.clear()
    else:
        await state.update_data(grade=grade)
        await state.set_state(AdminState.delete_waiting_for_topic)
        await message.answer("O'chirmoqchi bo'lgan mavzuni tanlang:", reply_markup=kb)

@router.message(AdminState.delete_waiting_for_topic)
async def delete_confirm_topic(message: Message, state: FSMContext):
    topic = message.text
    if topic == "⬅️ Bosh menyu":
        await state.clear()
        await message.answer("Bosh menyu:", reply_markup=get_main_menu(message.from_user.id))
        return

    conn = sqlite3.connect("history_bot.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM questions WHERE topic = ?", (topic,))
    conn.commit()
    conn.close()

    await message.answer(f"🗑 **'{topic}'** mavzusi va unga tegishli barcha savollar bazadan o'chirib tashlandi!", reply_markup=get_admin_menu(), parse_mode="Markdown")
    await state.clear()

# --- TXT FAYL ORQALI TEST YUKLASH ---

@router.message(F.text == "📁 TXT fayl orqali test yuklash")
async def start_file_upload(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    
    await state.set_state(AdminState.waiting_for_file)
    instruction = (
        "📥 **Test yuklash uchun `.txt` fayl yuboring.**\n\n"
        "**To'g'ri fayl ko'rinishi:**\n\n"
        "Sinf: 9-sinf O'zbekiston tarixi\n"
        "Mavzu: Abulxayrxon va Boburiylar davri\n\n"
        "Savol: Abulxayrxon qaysi yili xon bo'lgan?\n"
        "A) 1412-yil\n"
        "B) 1428-yil\n"
        "C) 1430-yil\n"
        "D) 1446-yil\n"
        "Javob: B\n\n"
        "Savol: Keyingi savol matni...\n"
        "A) Variant 1\n"
        "..."
    )
    await message.answer(instruction, reply_markup=get_admin_menu(), parse_mode="Markdown")

@router.message(AdminState.waiting_for_file, F.content_type == ContentType.DOCUMENT)
async def process_txt_file(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return

    document = message.document
    if not document.file_name.endswith('.txt'):
        await message.answer("⚠️ Iltimos, faqat **.txt** formatidagi fayl yuboring!")
        return

    file_path = f"temp_{document.file_name}"
    await bot.download(document, destination=file_path)

    try:
        try:
            with open(file_path, "r", encoding="utf-8-sig") as f:
                content = f.read()
        except UnicodeDecodeError:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

        grade = ""
        topic = ""

        grade_match = re.search(r"(?i)^sinf\s*:\s*(.+)$", content, re.MULTILINE)
        topic_match = re.search(r"(?i)^mavzu\s*:\s*(.+)$", content, re.MULTILINE)

        if grade_match:
            grade = grade_match.group(1).strip()
        if topic_match:
            topic = topic_match.group(1).strip()

        if not grade or not topic:
            await message.answer("⚠️ Fayl boshida **Sinf:** va **Mavzu:** ko'rsatilmagan! Tekshirib qayta yuboring.")
            return

        raw_questions = re.split(r"(?i)\n(?=Savol\s*:)", content)
        questions_to_insert = []

        for raw_q in raw_questions:
            q_lines = [l.strip() for l in raw_q.strip().split("\n") if l.strip()]
            
            q_text = ""
            opt_a, opt_b, opt_c, opt_d = "", "", "", ""
            correct = ""

            for l in q_lines:
                if re.search(r"(?i)^savol\s*:", l):
                    q_text = re.sub(r"(?i)^savol\s*:\s*", "", l).strip()
                elif re.search(r"(?i)^a[\).]", l):
                    opt_a = re.sub(r"(?i)^a[\).]\s*", "", l).strip()
                elif re.search(r"(?i)^b[\).]", l):
                    opt_b = re.sub(r"(?i)^b[\).]\s*", "", l).strip()
                elif re.search(r"(?i)^c[\).]", l):
                    opt_c = re.sub(r"(?i)^c[\).]\s*", "", l).strip()
                elif re.search(r"(?i)^d[\).]", l):
                    opt_d = re.sub(r"(?i)^d[\).]\s*", "", l).strip()
                elif re.search(r"(?i)^javob\s*:", l):
                    correct = re.sub(r"(?i)^javob\s*:\s*", "", l).strip().upper()

            if q_text and opt_a and opt_b and opt_c and opt_d and correct:
                questions_to_insert.append((grade, topic, q_text, opt_a, opt_b, opt_c, opt_d, correct))

        if questions_to_insert:
            conn = sqlite3.connect("history_bot.db")
            cursor = conn.cursor()
            cursor.executemany("""
                INSERT INTO questions (grade, topic, question_text, option_a, option_b, option_c, option_d, correct_option)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, questions_to_insert)
            conn.commit()
            conn.close()

            await message.answer(
                f"🎉 **Muvaffaqiyatli saqlandi!**\n\n"
                f"📌 **Sinf:** {grade}\n"
                f"📌 **Mavzu:** {topic}\n"
                f"📊 **Bitta mavzuga biriktirilgan savollar:** {len(questions_to_insert)} ta",
                reply_markup=get_admin_menu(),
                parse_mode="Markdown"
            )
        else:
            await message.answer("⚠️ Fayldan savollarni ajratib bo'lmadi. Format to'g'riligini tekshiring.")

    except Exception as e:
        await message.answer(f"❌ Faylni o'qishda xatolik: {e}")

    finally:
        if os.path.exists(file_path):
            os.remove(file_path)
        await state.clear()

# --- FOYDALANUVCHI QISMI (TEST YECHISH) ---

@router.message(F.text.in_([
    "8-sinf O'zbekiston tarixi", 
    "9-sinf O'zbekiston tarixi", 
    "10-sinf O'zbekiston tarixi", 
    "11-sinf O'zbekiston tarixi"
]))
async def select_grade(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is not None:
        return

    grade = message.text
    keyboard = get_topics_keyboard(grade)
    
    conn = sqlite3.connect("history_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(DISTINCT topic) FROM questions WHERE grade = ?", (grade,))
    count = cursor.fetchone()[0]
    conn.close()

    if count == 0:
        await message.answer(f"{grade} bo'yicha hozircha mavzular kiritilmagan.", reply_markup=get_main_menu(message.from_user.id))
    else:
        await message.answer(f"{grade}ni tanladingiz. Mavzuni tanlang:", reply_markup=keyboard)

@router.message(QuizState.answering)
async def process_quiz_answer(message: Message, state: FSMContext):
    user_answer = message.text.upper().strip()
    if user_answer not in ["A", "B", "C", "D"]:
        await message.answer("Iltimos, faqat A, B, C yoki D variantlaridan birini tanlang.")
        return

    data = await state.get_data()
    questions = data["questions"]
    current_index = data["current_index"]
    score = data["score"]

    correct_option = questions[current_index][8]
    if user_answer == correct_option:
        score += 1

    current_index += 1

    if current_index < len(questions):
        await state.update_data(current_index=current_index, score=score)
        await send_question(message, questions[current_index], current_index + 1, len(questions))
    else:
        total = len(questions)
        await message.answer(f"🏁 Test yakunlandi!\n\nNatijangiz: {total} ta savoldan {score} ta to'g'ri javob topdingiz.", reply_markup=get_main_menu(message.from_user.id))
        await state.clear()

async def send_question(message: Message, q_data, q_num, total_q):
    q_text = (
        f"❓ Savol {q_num}/{total_q}:\n\n"
        f"{q_data[3]}\n\n"
        f"A) {q_data[4]}\n"
        f"B) {q_data[5]}\n"
        f"C) {q_data[6]}\n"
        f"D) {q_data[7]}"
    )
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="A"), KeyboardButton(text="B")], [KeyboardButton(text="C"), KeyboardButton(text="D")]],
        resize_keyboard=True
    )
    await message.answer(q_text, reply_markup=kb)

# --- MAVZU TANLAGANDA TESTNI BOSHLASH ---

@router.message()
async def start_topic_quiz(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is not None:
        return

    topic = message.text
    conn = sqlite3.connect("history_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM questions WHERE topic = ? LIMIT 20", (topic,))
    questions = cursor.fetchall()
    conn.close()

    if not questions:
        await message.answer("Bunday mavzu yoki buyruq topilmadi. Bosh menyudan foydalaning.", reply_markup=get_main_menu(message.from_user.id))
        return

    await state.set_state(QuizState.answering)
    await state.update_data(questions=questions, current_index=0, score=0)
    await message.answer(f"🚀 '{topic}' mavzusi bo'yicha test boshlandi! Omad!", reply_markup=ReplyKeyboardRemove())
    await send_question(message, questions[0], 1, len(questions))

# --- RENDER PORTINI ESHITISH UCHUN DUMMY WEB SERVER ---
async def handle_ping(request):
    return web.Response(text="Bot runs live successfully!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    
    # Render avtomatik beradigan PORT o'zgaruvchisini olamiz (odatiy 8080)
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

# --- ISHGA TUSHIRISH ---
async def main():
    # Render uchun web serverni orqa fonda yurgizamiz
    await start_web_server()
    # Polling orqali botni ishga tushiramiz
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
