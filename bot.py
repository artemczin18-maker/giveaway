import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import sqlite3
from datetime import datetime, timedelta
import threading
import os
from flask import Flask
import time

# ===== ТВОИ ДАННЫЕ =====
BOT_TOKEN = "8860815149:AAF5wrXT0e4up4BZeHdsL4vcfIIsRlIjp5s"
ADMIN_ID = 8691263721
# =======================

bot = telebot.TeleBot(BOT_TOKEN)

# Flask для Render
app = Flask(__name__)

@app.route('/')
def home():
    return "Бот работает"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# База данных
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

def admin_keyboard():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("➕ Создать розыгрыш", callback_data="create"),
        InlineKeyboardButton("📋 Список розыгрышей", callback_data="list"),
        InlineKeyboardButton("🏆 Назначить победителя", callback_data="force"),
        InlineKeyboardButton("👥 Список участников", callback_data="participants")
    )
    return kb

@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.chat.id != ADMIN_ID:
        bot.reply_to(message, "⛔ Нет доступа")
        return
    bot.send_message(ADMIN_ID, "🔧 **Админ-панель**", reply_markup=admin_keyboard(), parse_mode='Markdown')

# Создание розыгрыша
@bot.callback_query_handler(func=lambda call: call.data == "create")
def create_step1(call):
    bot.send_message(ADMIN_ID, "📝 Введите **описание** розыгрыша:")
    bot.register_next_step_handler_by_chat_id(ADMIN_ID, create_step2)

def create_step2(message):
    desc = message.text
    bot.send_message(ADMIN_ID, "👥 Введите **количество победителей** (цифрой):")
    bot.register_next_step_handler_by_chat_id(ADMIN_ID, lambda m: create_step3(m, desc))

def create_step3(message, desc):
    try:
        winners = int(message.text)
    except:
        bot.send_message(ADMIN_ID, "❌ Ошибка. Отмена.")
        return
    bot.send_message(ADMIN_ID, "⏰ Введите **время в минутах** (например 60):")
    bot.register_next_step_handler_by_chat_id(ADMIN_ID, lambda m: create_step4(m, desc, winners))

def create_step4(message, desc, winners):
    try:
        minutes = int(message.text)
    except:
        bot.send_message(ADMIN_ID, "❌ Ошибка. Отмена.")
        return
    end_time = datetime.now() + timedelta(minutes=minutes)
    end_str = end_time.strftime("%Y-%m-%d %H:%M:%S")
    
    # Отправляем сообщение в чат с админом (можно потом изменить chat_id)
    chat_id = ADMIN_ID
    msg_text = f"🎁 **НОВЫЙ РОЗЫГРЫШ** 🎁\n\n{desc}\n\n👥 Победителей: {winners}\n⏰ До: {end_time.strftime('%H:%M %d.%m')}\n\n👇 Нажми УЧАСТВОВАТЬ"
    msg = bot.send_message(chat_id, msg_text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🎲 Участвовать", callback_data="temp")))
    
    c.execute("INSERT INTO giveaways (chat_id, message_id, description, winners_count, end_time) VALUES (?, ?, ?, ?, ?)",
              (chat_id, msg.message_id, desc, winners, end_str))
    conn.commit()
    giveaway_id = c.lastrowid
    
    # Обновляем кнопку с ID розыгрыша
    kb = InlineKeyboardMarkup().add(InlineKeyboardButton("🎲 Участвовать", callback_data=f"join_{giveaway_id}"))
    bot.edit_message_reply_markup(chat_id, msg.message_id, reply_markup=kb)
    
    bot.send_message(ADMIN_ID, f"✅ Розыгрыш #{giveaway_id} создан!")

# Участие
@bot.callback_query_handler(func=lambda call: call.data.startswith("join_"))
def join_giveaway(call):
    giveaway_id = int(call.data.split("_")[1])
    user_id = call.from_user.id
    username = call.from_user.username or ""
    first_name = call.from_user.first_name
    
    # Проверка активности
    c.execute("SELECT status, end_time FROM giveaways WHERE id = ?", (giveaway_id,))
    row = c.fetchone()
    if not row or row[0] != 'active':
        bot.answer_callback_query(call.id, "❌ Розыгрыш закончен")
        return
    if datetime.now() > datetime.strptime(row[1], "%Y-%m-%d %H:%M:%S"):
        bot.answer_callback_query(call.id, "❌ Время вышло")
        return
    
    # Проверка повторного участия
    c.execute("SELECT 1 FROM participants WHERE giveaway_id = ? AND user_id = ?", (giveaway_id, user_id))
    if c.fetchone():
        bot.answer_callback_query(call.id, "✅ Вы уже участвуете!")
        return
    
    c.execute("INSERT INTO participants (giveaway_id, user_id, username, first_name) VALUES (?, ?, ?, ?)",
              (giveaway_id, user_id, username, first_name))
    conn.commit()
    bot.answer_callback_query(call.id, "✅ Вы участвуете в розыгрыше!")
    
    # Обновляем счётчик
    c.execute("SELECT COUNT(*) FROM participants WHERE giveaway_id = ?", (giveaway_id,))
    count = c.fetchone()[0]
    c.execute("SELECT chat_id, message_id FROM giveaways WHERE id = ?", (giveaway_id,))
    chat_id, msg_id = c.fetchone()
    try:
        kb = InlineKeyboardMarkup().add(InlineKeyboardButton(f"🎲 Участников: {count}", callback_data="noop"))
        kb.add(InlineKeyboardButton("🎲 Участвовать", callback_data=f"join_{giveaway_id}"))
        bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=kb)
    except:
        pass

@bot.callback_query_handler(func=lambda call: call.data == "noop")
def noop(call):
    bot.answer_callback_query(call.id)

# Список розыгрышей (админ)
@bot.callback_query_handler(func=lambda call: call.data == "list")
def list_giveaways(call):
    c.execute("SELECT id, description, status, end_time FROM giveaways")
    rows = c.fetchall()
    if not rows:
        bot.send_message(ADMIN_ID, "Нет розыгрышей")
        return
    text = "📋 **Розыгрыши**\n\n"
    for r in rows:
        text += f"#{r[0]}: {r[1][:40]} | {r[2]} | до {r[3]}\n"
    bot.send_message(ADMIN_ID, text, parse_mode='Markdown')

# Принудительный победитель
@bot.callback_query_handler(func=lambda call: call.data == "force")
def force_menu(call):
    c.execute("SELECT id, description FROM giveaways WHERE status = 'active'")
    rows = c.fetchall()
    if not rows:
        bot.send_message(ADMIN_ID, "Нет активных розыгрышей")
        return
    kb = InlineKeyboardMarkup(row_width=1)
    for r in rows:
        kb.add(InlineKeyboardButton(f"#{r[0]}: {r[1][:30]}", callback_data=f"force_select_{r[0]}"))
    bot.send_message(ADMIN_ID, "Выберите розыгрыш:", reply_markup=kb)

@bot.callback_query_handler(func=lambda call: call.data.startswith("force_select_"))
def force_select(call):
    giveaway_id = int(call.data.split("_")[2])
    bot.send_message(ADMIN_ID, "Введите **username** (без @) или **user_id** победителя:")
    bot.register_next_step_handler_by_chat_id(ADMIN_ID, lambda m: force_set_winner(m, giveaway_id))

def force_set_winner(message, giveaway_id):
    identifier = message.text.strip()
    if identifier.isdigit():
        user_id = int(identifier)
        c.execute("SELECT first_name, username FROM participants WHERE giveaway_id = ? AND user_id = ?", (giveaway_id, user_id))
        winner = c.fetchone()
    else:
        c.execute("SELECT user_id, first_name FROM participants WHERE giveaway_id = ? AND username = ?", (giveaway_id, identifier))
        winner = c.fetchone()
    if not winner:
        bot.send_message(ADMIN_ID, "❌ Участник не найден")
        return
    user_id = winner[0]
    name = winner[1]
    
    c.execute("REPLACE INTO force_winner (giveaway_id, user_id) VALUES (?, ?)", (giveaway_id, user_id))
    conn.commit()
    
    # Завершаем розыгрыш
    c.execute("SELECT chat_id, message_id, description FROM giveaways WHERE id = ?", (giveaway_id,))
    chat_id, msg_id, desc = c.fetchone()
    
    winner_username = ""
    c.execute("SELECT username FROM participants WHERE giveaway_id = ? AND user_id = ?", (giveaway_id, user_id))
    row = c.fetchone()
    if row and row[0]:
        winner_username = f" @{row[0]}"
    
    result_text = f"🏆 **ИТОГИ РОЗЫГРЫША** 🏆\n\n{desc}\n\nПобедитель: {name}{winner_username}\n\nПоздравляем!"
    bot.send_message(chat_id, result_text, parse_mode='Markdown')
    c.execute("UPDATE giveaways SET status = 'finished' WHERE id = ?", (giveaway_id,))
    conn.commit()
    bot.send_message(ADMIN_ID, f"✅ Победитель назначен: {name}")

# Список участников
@bot.callback_query_handler(func=lambda call: call.data == "participants")
def participants_menu(call):
    c.execute("SELECT id, description FROM giveaways WHERE status = 'active'")
    rows = c.fetchall()
    if not rows:
        bot.send_message(ADMIN_ID, "Нет активных розыгрышей")
        return
    kb = InlineKeyboardMarkup(row_width=1)
    for r in rows:
        kb.add(InlineKeyboardButton(f"#{r[0]}: {r[1][:30]}", callback_data=f"parts_{r[0]}"))
    bot.send_message(ADMIN_ID, "Выберите розыгрыш:", reply_markup=kb)

@bot.callback_query_handler(func=lambda call: call.data.startswith("parts_"))
def show_participants(call):
    giveaway_id = int(call.data.split("_")[1])
    c.execute("SELECT user_id, username, first_name FROM participants WHERE giveaway_id = ?", (giveaway_id,))
    parts = c.fetchall()
    if not parts:
        bot.send_message(ADMIN_ID, "Нет участников")
        return
    text = f"📋 **Участники #{giveaway_id}**\n\n"
    for p in parts:
        text += f"• {p[2]} (@{p[1] or 'нет'}) — ID {p[0]}\n"
        if len(text) > 3500:
            bot.send_message(ADMIN_ID, text)
            text = ""
    if text:
        bot.send_message(ADMIN_ID, text, parse_mode='Markdown')

# Завершить розыгрыш
@bot.callback_query_handler(func=lambda call: call.data == "admin_end")
def end_menu(call):
    c.execute("SELECT id, description FROM giveaways WHERE status = 'active'")
    rows = c.fetchall()
    if not rows:
        bot.send_message(ADMIN_ID, "Нет активных розыгрышей")
        return
    kb = InlineKeyboardMarkup(row_width=1)
    for r in rows:
        kb.add(InlineKeyboardButton(f"#{r[0]}: {r[1][:30]}", callback_data=f"end_{r[0]}"))
    bot.send_message(ADMIN_ID, "Какой розыгрыш завершить?", reply_markup=kb)

@bot.callback_query_handler(func=lambda call: call.data.startswith("end_"))
def end_giveaway(call):
    giveaway_id = int(call.data.split("_")[1])
    c.execute("UPDATE giveaways SET status = 'finished' WHERE id = ?", (giveaway_id,))
    conn.commit()
    bot.send_message(ADMIN_ID, f"✅ Розыгрыш #{giveaway_id} завершён")

# Запуск
if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    print("✅ Бот запущен")
    bot.infinity_polling()
