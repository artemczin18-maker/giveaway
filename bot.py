import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import sqlite3
import json
from datetime import datetime, timedelta
import threading
import time

# ===== НАСТРОЙКИ (ЗАМЕНИ НА СВОИ) =====
BOT_TOKEN = "8989367067:AAF20yXLVkqvNY0pAjlVTku43HoBubQuBYM"
ADMIN_ID = 8691263721 # ТВОЙ ID (узнай)
# =======================================

bot = telebot.TeleBot(BOT_TOKEN)

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

c.execute('''CREATE TABLE IF NOT EXISTS winners_override (
    giveaway_id INTEGER PRIMARY KEY,
    forced_user_id INTEGER
)''')
conn.commit()

def admin_keyboard():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton("📋 Список розыгрышей", callback_data="admin_list"))
    kb.add(InlineKeyboardButton("➕ Создать розыгрыш", callback_data="admin_create"))
    kb.add(InlineKeyboardButton("🏆 Принудительный победитель", callback_data="admin_force_winner"))
    kb.add(InlineKeyboardButton("📊 Участники розыгрыша", callback_data="admin_participants"))
    return kb

@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.chat.id != ADMIN_ID:
        bot.reply_to(message, "⛔ Нет доступа")
        return
    bot.send_message(ADMIN_ID, "🔧 **Админ-панель**", reply_markup=admin_keyboard(), parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data == "admin_create")
def create_giveaway_start(call):
    bot.send_message(ADMIN_ID, "📝 Введите **описание** розыгрыша:")
    bot.register_next_step_handler_by_chat_id(ADMIN_ID, get_description)

def get_description(message):
    bot.send_message(ADMIN_ID, "👥 Введите **количество победителей**:")
    bot.register_next_step_handler_by_chat_id(ADMIN_ID, lambda m: get_winners_count(m, message.text))

def get_winners_count(message, description):
    try:
        winners = int(message.text)
    except:
        bot.send_message(ADMIN_ID, "❌ Введите число. Отмена.")
        return
    bot.send_message(ADMIN_ID, "⏰ Введите **время окончания** (в минутах от текущего момента, например 60):")
    bot.register_next_step_handler_by_chat_id(ADMIN_ID, lambda m: create_giveaway_final(m, description, winners))

def create_giveaway_final(message, description, winners_count):
    try:
        minutes = int(message.text)
    except:
        bot.send_message(ADMIN_ID, "❌ Ошибка. Отмена.")
        return
    end_time = datetime.now() + timedelta(minutes=minutes)
    end_str = end_time.strftime("%Y-%m-%d %H:%M:%S")
    
    chat_id = ADMIN_ID
    msg = bot.send_message(chat_id, f"🎁 **РОЗЫГРЫШ** 🎁\n\n{description}\n\n👥 Победителей: {winners_count}\n⏰ До: {end_str}\n\n👇 Нажми УЧАСТВОВАТЬ", parse_mode='Markdown', reply_markup=participate_keyboard())
    
    c.execute("INSERT INTO giveaways (chat_id, message_id, description, winners_count, end_time) VALUES (?, ?, ?, ?, ?)",
              (chat_id, msg.message_id, description, winners_count, end_str))
    conn.commit()
    giveaway_id = c.lastrowid
    bot.send_message(ADMIN_ID, f"✅ Розыгрыш #{giveaway_id} создан!")

def participate_keyboard():
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🎲 Участвовать", callback_data="participate"))
    return kb

@bot.callback_query_handler(func=lambda call: call.data == "participate")
def participate(call):
    c.execute("SELECT id FROM giveaways WHERE chat_id = ? AND status = 'active' AND datetime(end_time) > datetime('now')", (call.message.chat.id,))
    row = c.fetchone()
    if not row:
        bot.answer_callback_query(call.id, "Нет активных розыгрышей")
        return
    giveaway_id = row[0]
    
    c.execute("SELECT 1 FROM participants WHERE giveaway_id = ? AND user_id = ?", (giveaway_id, call.from_user.id))
    if c.fetchone():
        bot.answer_callback_query(call.id, "Вы уже участвуете!")
        return
    
    c.execute("INSERT INTO participants (giveaway_id, user_id, username, first_name) VALUES (?, ?, ?, ?)",
              (giveaway_id, call.from_user.id, call.from_user.username, call.from_user.first_name))
    conn.commit()
    bot.answer_callback_query(call.id, "✅ Вы участвуете в розыгрыше!")
    
    c.execute("SELECT COUNT(*) FROM participants WHERE giveaway_id = ?", (giveaway_id,))
    count = c.fetchone()[0]
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=participate_keyboard_with_count(count))

def participate_keyboard_with_count(count):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(f"🎲 Участников: {count}", callback_data="noop"))
    kb.add(InlineKeyboardButton("🎲 Участвовать", callback_data="participate"))
    return kb

@bot.callback_query_handler(func=lambda call: call.data == "noop")
def noop(call):
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "admin_force_winner")
def force_winner_menu(call):
    c.execute("SELECT id, description FROM giveaways WHERE status = 'active'")
    giveaways = c.fetchall()
    if not giveaways:
        bot.send_message(ADMIN_ID, "Нет активных розыгрышей")
        return
    kb = InlineKeyboardMarkup(row_width=1)
    for g in giveaways:
        kb.add(InlineKeyboardButton(f"#{g[0]}: {g[1][:30]}", callback_data=f"select_giveaway_{g[0]}"))
    bot.send_message(ADMIN_ID, "Выберите розыгрыш:", reply_markup=kb)

@bot.callback_query_handler(func=lambda call: call.data.startswith("select_giveaway_"))
def select_giveaway(call):
    giveaway_id = int(call.data.split("_")[2])
    bot.send_message(ADMIN_ID, "Введите **username** (без @) или **user_id** победителя:")
    bot.register_next_step_handler_by_chat_id(ADMIN_ID, lambda m: set_winner(m, giveaway_id))

def set_winner(message, giveaway_id):
    identifier = message.text.strip()
    if identifier.isdigit():
        user_id = int(identifier)
        c.execute("SELECT first_name, username FROM participants WHERE giveaway_id = ? AND user_id = ?", (giveaway_id, user_id))
        winner = c.fetchone()
    else:
        c.execute("SELECT user_id, first_name FROM participants WHERE giveaway_id = ? AND username = ?", (giveaway_id, identifier))
        winner = c.fetchone()
    if not winner:
        bot.send_message(ADMIN_ID, "❌ Такой участник не найден в этом розыгрыше")
        return
    user_id = winner[0]
    name = winner[1]
    
    c.execute("REPLACE INTO winners_override (giveaway_id, forced_user_id) VALUES (?, ?)", (giveaway_id, user_id))
    conn.commit()
    bot.send_message(ADMIN_ID, f"✅ Победитель розыгрыша #{giveaway_id} принудительно назначен: {name} (ID {user_id})")
    end_giveaway(giveaway_id, user_id)

def end_giveaway(giveaway_id, winner_id):
    c.execute("SELECT chat_id, message_id FROM giveaways WHERE id = ?", (giveaway_id,))
    chat_id, msg_id = c.fetchone()
    c.execute("SELECT first_name, username FROM participants WHERE giveaway_id = ? AND user_id = ?", (giveaway_id, winner_id))
    winner_data = c.fetchone()
    if winner_data:
        winner_name = winner_data[0]
        winner_username = "@" + winner_data[1] if winner_data[1] else f"ID {winner_id}"
    else:
        winner_name = f"Пользователь {winner_id}"
        winner_username = f"ID {winner_id}"
    
    text = f"🏆 **ИТОГИ РОЗЫГРЫША** 🏆\n\nПобедитель: {winner_name} {winner_username}\n\nПоздравляем!"
    bot.send_message(chat_id, text, parse_mode='Markdown')
    c.execute("UPDATE giveaways SET status = 'finished' WHERE id = ?", (giveaway_id,))
    conn.commit()
    bot.send_message(ADMIN_ID, f"✅ Розыгрыш #{giveaway_id} завершён. Победитель: {winner_name}")

@bot.callback_query_handler(func=lambda call: call.data == "admin_participants")
def list_participants_menu(call):
    c.execute("SELECT id, description FROM giveaways WHERE status = 'active'")
    giveaways = c.fetchall()
    if not giveaways:
        bot.send_message(ADMIN_ID, "Нет активных розыгрышей")
        return
    kb = InlineKeyboardMarkup(row_width=1)
    for g in giveaways:
        kb.add(InlineKeyboardButton(f"#{g[0]}: {g[1][:30]}", callback_data=f"parts_giveaway_{g[0]}"))
    bot.send_message(ADMIN_ID, "Выберите розыгрыш:", reply_markup=kb)

@bot.callback_query_handler(func=lambda call: call.data.startswith("parts_giveaway_"))
def show_participants(call):
    giveaway_id = int(call.data.split("_")[2])
    c.execute("SELECT user_id, username, first_name FROM participants WHERE giveaway_id = ?", (giveaway_id,))
    parts = c.fetchall()
    if not parts:
        bot.send_message(ADMIN_ID, "Участников нет")
        return
    text = f"📋 **Участники розыгрыша #{giveaway_id}**\n\n"
    for p in parts:
        text += f"• {p[2]} (@{p[1] or 'нет'}) — ID {p[0]}\n"
    bot.send_message(ADMIN_ID, text, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data == "admin_list")
def list_giveaways(call):
    c.execute("SELECT id, description, status, end_time FROM giveaways")
    rows = c.fetchall()
    if not rows:
        bot.send_message(ADMIN_ID, "Нет розыгрышей")
        return
    text = "📋 **Все розыгрыши**\n\n"
    for r in rows:
        text += f"#{r[0]}: {r[1][:40]}... | {r[2]} | до {r[3]}\n"
    bot.send_message(ADMIN_ID, text, parse_mode='Markdown')

print("✅ Бот запущен")
bot.infinity_polling()
