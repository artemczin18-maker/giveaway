import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import sqlite3
from datetime import datetime, timedelta
import threading
import os
import time
from flask import Flask

# ========== НАСТРОЙКИ (ЗАМЕНИ НА СВОИ) ==========
BOT_TOKEN = "8860815149:AAHxT1zo5jT1Grnf2fJXVn9sD9kUQcH_Fy4"
ADMIN_ID = 8691263721
# ================================================

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# ========== БАЗА ДАННЫХ ==========
conn = sqlite3.connect('giveaways.db', check_same_thread=False)
c = conn.cursor()

c.execute('''CREATE TABLE IF NOT EXISTS giveaways (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER,
    message_id INTEGER,
    description TEXT,
    winners_count INTEGER,
    end_time TEXT,
    status TEXT DEFAULT 'active'
)''')

c.execute('''CREATE TABLE IF NOT EXISTS participants (
    giveaway_id INTEGER,
    user_id INTEGER,
    username TEXT,
    first_name TEXT
)''')

c.execute('''CREATE TABLE IF NOT EXISTS force_winner (
    giveaway_id INTEGER PRIMARY KEY,
    user_id INTEGER
)''')
conn.commit()

# ========== КЛАВИАТУРЫ ==========
def admin_keyboard():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("➕ СОЗДАТЬ РОЗЫГРЫШ", callback_data="create_giveaway"),
        InlineKeyboardButton("📋 СПИСОК РОЗЫГРЫШЕЙ", callback_data="list_giveaways"),
        InlineKeyboardButton("🏆 НАЗНАЧИТЬ ПОБЕДИТЕЛЯ", callback_data="force_winner"),
        InlineKeyboardButton("👥 УЧАСТНИКИ", callback_data="participants_list"),
        InlineKeyboardButton("❌ ЗАВЕРШИТЬ РОЗЫГРЫШ", callback_data="end_giveaway")
    )
    return kb

# ========== АДМИН-ПАНЕЛЬ ==========
@bot.message_handler(commands=['start'])
def start_cmd(message):
    bot.send_message(message.chat.id, "🤖 Бот для розыгрышей\n\nАдмин: /admin")

@bot.message_handler(commands=['admin'])
def admin_cmd(message):
    if message.chat.id != ADMIN_ID:
        bot.reply_to(message, "⛔ Нет доступа")
        return
    bot.send_message(ADMIN_ID, "🔧 **АДМИН-ПАНЕЛЬ**", reply_markup=admin_keyboard(), parse_mode='Markdown')

# ========== 1. СОЗДАНИЕ РОЗЫГРЫША ==========
@bot.callback_query_handler(func=lambda call: call.data == "create_giveaway")
def create_step1(call):
    bot.send_message(ADMIN_ID, "📝 Введите **описание** розыгрыша (что разыгрывается, условия):")
    bot.register_next_step_handler_by_chat_id(ADMIN_ID, create_step2)

def create_step2(message):
    desc = message.text
    bot.send_message(ADMIN_ID, "👥 Введите **количество победителей** (цифрой):")
    bot.register_next_step_handler_by_chat_id(ADMIN_ID, lambda m: create_step3(m, desc))

def create_step3(message, desc):
    try:
        winners = int(message.text)
    except:
        bot.send_message(ADMIN_ID, "❌ Ошибка! Нужно число. Отмена.")
        return
    bot.send_message(ADMIN_ID, "⏰ Введите **время в минутах** (например 60 для 1 часа):")
    bot.register_next_step_handler_by_chat_id(ADMIN_ID, lambda m: create_step4(m, desc, winners))

def create_step4(message, desc, winners):
    try:
        minutes = int(message.text)
    except:
        bot.send_message(ADMIN_ID, "❌ Ошибка! Отмена.")
        return
    
    end_time = datetime.now() + timedelta(minutes=minutes)
    end_str = end_time.strftime("%Y-%m-%d %H:%M:%S")
    end_readable = end_time.strftime("%d.%m.%Y в %H:%M")
    
    # Отправляем сообщение в чат (сейчас в личку админа, можешь заменить на группу)
    chat_id = ADMIN_ID
    msg_text = f"🎁 **РОЗЫГРЫШ** 🎁\n\n{desc}\n\n👥 Победителей: {winners}\n⏰ Завершится: {end_readable}\n\n👇 Нажми «Участвовать»"
    
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🎲 УЧАСТВОВАТЬ", callback_data="temp_join"))
    
    msg = bot.send_message(chat_id, msg_text, parse_mode='Markdown', reply_markup=kb)
    
    # Сохраняем в БД
    c.execute("INSERT INTO giveaways (chat_id, message_id, description, winners_count, end_time) VALUES (?, ?, ?, ?, ?)",
              (chat_id, msg.message_id, desc, winners, end_str))
    conn.commit()
    giveaway_id = c.lastrowid
    
    # Обновляем кнопку с ID розыгрыша
    kb2 = InlineKeyboardMarkup()
    kb2.add(InlineKeyboardButton("🎲 УЧАСТВОВАТЬ", callback_data=f"join_{giveaway_id}"))
    bot.edit_message_reply_markup(chat_id, msg.message_id, reply_markup=kb2)
    
    bot.send_message(ADMIN_ID, f"✅ Розыгрыш #{giveaway_id} создан!\nЗакончится в {end_readable}")

# ========== 2. УЧАСТИЕ В РОЗЫГРЫШЕ ==========
@bot.callback_query_handler(func=lambda call: call.data.startswith("join_"))
def join_giveaway(call):
    giveaway_id = int(call.data.split("_")[1])
    user_id = call.from_user.id
    username = call.from_user.username or ""
    first_name = call.from_user.first_name
    
    # Проверяем активность розыгрыша
    c.execute("SELECT status, end_time, chat_id, message_id FROM giveaways WHERE id = ?", (giveaway_id,))
    row = c.fetchone()
    if not row:
        bot.answer_callback_query(call.id, "❌ Розыгрыш не найден")
        return
    status, end_time_str, chat_id, msg_id = row
    
    if status != 'active':
        bot.answer_callback_query(call.id, "❌ Розыгрыш уже закончен")
        return
    
    if datetime.now() > datetime.strptime(end_time_str, "%Y-%m-%d %H:%M:%S"):
        bot.answer_callback_query(call.id, "❌ Время розыгрыша истекло")
        return
    
    # Проверяем, не участвовал ли уже
    c.execute("SELECT 1 FROM participants WHERE giveaway_id = ? AND user_id = ?", (giveaway_id, user_id))
    if c.fetchone():
        bot.answer_callback_query(call.id, "✅ Вы уже участвуете!")
        return
    
    # Добавляем участника
    c.execute("INSERT INTO participants (giveaway_id, user_id, username, first_name) VALUES (?, ?, ?, ?)",
              (giveaway_id, user_id, username, first_name))
    conn.commit()
    bot.answer_callback_query(call.id, "✅ Вы участвуете в розыгрыше!")
    
    # Обновляем счётчик
    c.execute("SELECT COUNT(*) FROM participants WHERE giveaway_id = ?", (giveaway_id,))
    count = c.fetchone()[0]
    
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(f"🎲 УЧАСТНИКОВ: {count}", callback_data="noop"))
    kb.add(InlineKeyboardButton("🎲 УЧАСТВОВАТЬ", callback_data=f"join_{giveaway_id}"))
    bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=kb)

@bot.callback_query_handler(func=lambda call: call.data == "noop")
def noop(call):
    bot.answer_callback_query(call.id)

# ========== 3. СПИСОК РОЗЫГРЫШЕЙ ==========
@bot.callback_query_handler(func=lambda call: call.data == "list_giveaways")
def list_giveaways(call):
    c.execute("SELECT id, description, status, end_time FROM giveaways ORDER BY id DESC")
    rows = c.fetchall()
    if not rows:
        bot.send_message(ADMIN_ID, "📭 Нет ни одного розыгрыша")
        return
    
    text = "📋 **ВСЕ РОЗЫГРЫШИ**\n\n"
    for row in rows:
        status_emoji = "🟢" if row[2] == 'active' else "🔴"
        text += f"{status_emoji} #{row[0]}: {row[1][:40]}\n   Статус: {row[2]}, до {row[3][:16]}\n\n"
    
    bot.send_message(ADMIN_ID, text, parse_mode='Markdown')

# ========== 4. ПРИНУДИТЕЛЬНЫЙ ПОБЕДИТЕЛЬ ==========
@bot.callback_query_handler(func=lambda call: call.data == "force_winner")
def force_winner_menu(call):
    c.execute("SELECT id, description FROM giveaways WHERE status = 'active'")
    rows = c.fetchall()
    if not rows:
        bot.send_message(ADMIN_ID, "❌ Нет активных розыгрышей")
        return
    
    kb = InlineKeyboardMarkup(row_width=1)
    for row in rows:
        kb.add(InlineKeyboardButton(f"#{row[0]}: {row[1][:30]}", callback_data=f"force_select_{row[0]}"))
    bot.send_message(ADMIN_ID, "🎯 Выберите розыгрыш:", reply_markup=kb)

@bot.callback_query_handler(func=lambda call: call.data.startswith("force_select_"))
def force_select_giveaway(call):
    giveaway_id = int(call.data.split("_")[2])
    bot.send_message(ADMIN_ID, "👤 Введите **username** (без @) или **user_id** победителя:")
    bot.register_next_step_handler_by_chat_id(ADMIN_ID, lambda m: force_set_winner(m, giveaway_id))

def force_set_winner(message, giveaway_id):
    identifier = message.text.strip()
    
    # Ищем участника
    if identifier.isdigit():
        user_id = int(identifier)
        c.execute("SELECT user_id, first_name, username FROM participants WHERE giveaway_id = ? AND user_id = ?", (giveaway_id, user_id))
        winner = c.fetchone()
    else:
        c.execute("SELECT user_id, first_name, username FROM participants WHERE giveaway_id = ? AND username = ?", (giveaway_id, identifier))
        winner = c.fetchone()
    
    if not winner:
        bot.send_message(ADMIN_ID, f"❌ Участник '{identifier}' не найден в этом розыгрыше")
        return
    
    user_id, first_name, username = winner
    winner_display = f"{first_name} (@{username})" if username else first_name
    
    # Получаем данные розыгрыша
    c.execute("SELECT chat_id, message_id, description FROM giveaways WHERE id = ?", (giveaway_id,))
    chat_id, msg_id, desc = c.fetchone()
    
    # Объявляем победителя
    result_text = f"🏆 **ИТОГИ РОЗЫГРЫША** 🏆\n\n{desc}\n\n🎉 **ПОБЕДИТЕЛЬ:** {winner_display}\n\nПоздравляем!"
    bot.send_message(chat_id, result_text, parse_mode='Markdown')
    
    # Завершаем розыгрыш
    c.execute("UPDATE giveaways SET status = 'finished' WHERE id = ?", (giveaway_id,))
    c.execute("INSERT OR REPLACE INTO force_winner (giveaway_id, user_id) VALUES (?, ?)", (giveaway_id, user_id))
    conn.commit()
    
    bot.send_message(ADMIN_ID, f"✅ Победитель розыгрыша #{giveaway_id} назначен: {winner_display}")

# ========== 5. СПИСОК УЧАСТНИКОВ ==========
@bot.callback_query_handler(func=lambda call: call.data == "participants_list")
def participants_list_menu(call):
    c.execute("SELECT id, description FROM giveaways WHERE status = 'active'")
    rows = c.fetchall()
    if not rows:
        bot.send_message(ADMIN_ID, "❌ Нет активных розыгрышей")
        return
    
    kb = InlineKeyboardMarkup(row_width=1)
    for row in rows:
        kb.add(InlineKeyboardButton(f"#{row[0]}: {row[1][:30]}", callback_data=f"parts_{row[0]}"))
    bot.send_message(ADMIN_ID, "👥 Выберите розыгрыш:", reply_markup=kb)

@bot.callback_query_handler(func=lambda call: call.data.startswith("parts_"))
def show_participants(call):
    giveaway_id = int(call.data.split("_")[1])
    c.execute("SELECT user_id, username, first_name FROM participants WHERE giveaway_id = ?", (giveaway_id,))
    parts = c.fetchall()
    
    if not parts:
        bot.send_message(ADMIN_ID, f"📭 В розыгрыше #{giveaway_id} нет участников")
        return
    
    text = f"👥 **УЧАСТНИКИ РОЗЫГРЫША #{giveaway_id}**\n\n"
    for idx, p in enumerate(parts, 1):
        user_id, username, first_name = p
        name_display = f"{first_name} (@{username})" if username else first_name
        text += f"{idx}. {name_display} — ID {user_id}\n"
        
        if len(text) > 3500:
            bot.send_message(ADMIN_ID, text, parse_mode='Markdown')
            text = ""
    
    if text:
        bot.send_message(ADMIN_ID, text, parse_mode='Markdown')

# ========== 6. ЗАВЕРШИТЬ РОЗЫГРЫШ ==========
@bot.callback_query_handler(func=lambda call: call.data == "end_giveaway")
def end_giveaway_menu(call):
    c.execute("SELECT id, description FROM giveaways WHERE status = 'active'")
    rows = c.fetchall()
    if not rows:
        bot.send_message(ADMIN_ID, "❌ Нет активных розыгрышей")
        return
    
    kb = InlineKeyboardMarkup(row_width=1)
    for row in rows:
        kb.add(InlineKeyboardButton(f"#{row[0]}: {row[1][:30]}", callback_data=f"end_{row[0]}"))
    bot.send_message(ADMIN_ID, "🔚 Какой розыгрыш завершить?", reply_markup=kb)

@bot.callback_query_handler(func=lambda call: call.data.startswith("end_"))
def end_giveaway(call):
    giveaway_id = int(call.data.split("_")[1])
    c.execute("UPDATE giveaways SET status = 'finished' WHERE id = ?", (giveaway_id,))
    conn.commit()
    bot.send_message(ADMIN_ID, f"✅ Розыгрыш #{giveaway_id} завершён (без объявления победителя)")

# ========== FLASK ДЛЯ RENDER ==========
@app.route('/')
def home():
    return "Бот для розыгрышей работает"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# ========== ЗАПУСК ==========
if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    print("✅ Бот запущен!")
    bot.infinity_polling()
