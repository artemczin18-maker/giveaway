import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import sqlite3
from datetime import datetime, timedelta
import threading
import os
import pytz
from flask import Flask

# ========== ТВОИ ДАННЫЕ ==========
BOT_TOKEN = "8860815149:AAGzuTErMgko8lTE6iFTlW4Mt3yTfxOS09A"
ADMIN_ID = 8691263721
CHANNEL_ID = -1003709110970
TIMEZONE = pytz.timezone("Europe/Moscow")  # московское время
# =================================

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# База данных
conn = sqlite3.connect('giveaways.db', check_same_thread=False)
c = conn.cursor()

c.execute('''CREATE TABLE IF NOT EXISTS giveaways (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_message_id INTEGER,
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
conn.commit()

def admin_keyboard():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("➕ СОЗДАТЬ РОЗЫГРЫШ", callback_data="create_giveaway"),
        InlineKeyboardButton("📋 СПИСОК", callback_data="list_giveaways"),
        InlineKeyboardButton("🏆 НАЗНАЧИТЬ ПОБЕДИТЕЛЯ", callback_data="force_winner"),
        InlineKeyboardButton("👥 УЧАСТНИКИ", callback_data="participants_list")
    )
    return kb

@bot.message_handler(commands=['admin'])
def admin_cmd(message):
    if message.chat.id != ADMIN_ID:
        bot.reply_to(message, "⛔ Нет доступа")
        return
    bot.send_message(ADMIN_ID, "🔧 **АДМИН-ПАНЕЛЬ**", reply_markup=admin_keyboard(), parse_mode='Markdown')

# ========== 1. СОЗДАНИЕ РОЗЫГРЫША ==========
@bot.callback_query_handler(func=lambda call: call.data == "create_giveaway")
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
    
    now = datetime.now(TIMEZONE)
    end_time = now + timedelta(minutes=minutes)
    end_str = end_time.strftime("%Y-%m-%d %H:%M:%S")
    end_readable = end_time.strftime("%d.%m.%Y в %H:%M")
    
    msg_text = f"🎁 **РОЗЫГРЫШ** 🎁\n\n{desc}\n\n👥 Победителей: {winners}\n⏰ Завершится: {end_readable}\n\n👇 Нажми «Участвовать»"
    
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🎲 УЧАСТВОВАТЬ", callback_data="temp_join"))
    
    channel_msg = bot.send_message(CHANNEL_ID, msg_text, parse_mode='Markdown', reply_markup=kb)
    
    c.execute("INSERT INTO giveaways (channel_message_id, description, winners_count, end_time) VALUES (?, ?, ?, ?)",
              (channel_msg.message_id, desc, winners, end_str))
    conn.commit()
    giveaway_id = c.lastrowid
    
    kb2 = InlineKeyboardMarkup()
    kb2.add(InlineKeyboardButton("🎲 УЧАСТВОВАТЬ", callback_data=f"join_{giveaway_id}"))
    bot.edit_message_reply_markup(CHANNEL_ID, channel_msg.message_id, reply_markup=kb2)
    
    bot.send_message(ADMIN_ID, f"✅ Розыгрыш #{giveaway_id} опубликован\nЗавершится {end_readable}")

# ========== 2. УЧАСТИЕ ==========
@bot.callback_query_handler(func=lambda call: call.data.startswith("join_"))
def join_giveaway(call):
    giveaway_id = int(call.data.split("_")[1])
    user_id = call.from_user.id
    username = call.from_user.username or ""
    first_name = call.from_user.first_name
    
    c.execute("SELECT status, end_time FROM giveaways WHERE id = ?", (giveaway_id,))
    row = c.fetchone()
    if not row:
        bot.answer_callback_query(call.id, "❌ Розыгрыш не найден")
        return
    
    status, end_time_str = row
    end_time = datetime.strptime(end_time_str, "%Y-%m-%d %H:%M:%S")
    end_time = TIMEZONE.localize(end_time) if not end_time.tzinfo else end_time
    
    if status != 'active':
        bot.answer_callback_query(call.id, "❌ Розыгрыш закончен")
        return
    if datetime.now(TIMEZONE) > end_time:
        bot.answer_callback_query(call.id, "❌ Время вышло")
        return
    
    c.execute("SELECT 1 FROM participants WHERE giveaway_id = ? AND user_id = ?", (giveaway_id, user_id))
    if c.fetchone():
        bot.answer_callback_query(call.id, "✅ Вы уже участвуете!")
        return
    
    c.execute("INSERT INTO participants (giveaway_id, user_id, username, first_name) VALUES (?, ?, ?, ?)",
              (giveaway_id, user_id, username, first_name))
    conn.commit()
    bot.answer_callback_query(call.id, "✅ Вы участвуете!")
    
    c.execute("SELECT COUNT(*) FROM participants WHERE giveaway_id = ?", (giveaway_id,))
    count = c.fetchone()[0]
    c.execute("SELECT channel_message_id FROM giveaways WHERE id = ?", (giveaway_id,))
    msg_id = c.fetchone()[0]
    
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(f"🎲 УЧАСТНИКОВ: {count}", callback_data="noop"))
    kb.add(InlineKeyboardButton("🎲 УЧАСТВОВАТЬ", callback_data=f"join_{giveaway_id}"))
    bot.edit_message_reply_markup(CHANNEL_ID, msg_id, reply_markup=kb)

@bot.callback_query_handler(func=lambda call: call.data == "noop")
def noop(call):
    bot.answer_callback_query(call.id)

# ========== 3. ПРИНУДИТЕЛЬНЫЙ ПОБЕДИТЕЛЬ (ИСПРАВЛЕНО) ==========
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
def force_select(call):
    giveaway_id = int(call.data.split("_")[2])
    bot.send_message(ADMIN_ID, "👤 Введите **username** (без @) или **user_id** победителя:")
    bot.register_next_step_handler_by_chat_id(ADMIN_ID, lambda m: force_set_winner(m, giveaway_id))

def force_set_winner(message, giveaway_id):
    identifier = message.text.strip()
    
    # ПОИСК УЧАСТНИКА — ИСПРАВЛЕНО
    c.execute("SELECT user_id, first_name, username FROM participants WHERE giveaway_id = ?", (giveaway_id,))
    all_participants = c.fetchall()
    
    winner = None
    for p in all_participants:
        user_id, first_name, username = p
        if identifier.isdigit() and str(user_id) == identifier:
            winner = (user_id, first_name, username)
            break
        elif username and username.lower() == identifier.lower():
            winner = (user_id, first_name, username)
            break
        elif first_name.lower() == identifier.lower():
            winner = (user_id, first_name, username)
            break
    
    if not winner:
        bot.send_message(ADMIN_ID, f"❌ Участник '{identifier}' не найден. Участники этого розыгрыша:")
        for p in all_participants:
            uid, fname, uname = p
            bot.send_message(ADMIN_ID, f"• {fname} (@{uname}) — ID {uid}")
        return
    
    user_id, first_name, username = winner
    winner_display = f"{first_name} (@{username})" if username else first_name
    
    c.execute("SELECT description, channel_message_id FROM giveaways WHERE id = ?", (giveaway_id,))
    desc, msg_id = c.fetchone()
    
    result_text = f"🏆 **ИТОГИ РОЗЫГРЫША** 🏆\n\n{desc}\n\n🎉 **ПОБЕДИТЕЛЬ:** {winner_display}\n\nПоздравляем!"
    bot.send_message(CHANNEL_ID, result_text, parse_mode='Markdown')
    
    c.execute("UPDATE giveaways SET status = 'finished' WHERE id = ?", (giveaway_id,))
    conn.commit()
    bot.send_message(ADMIN_ID, f"✅ Победитель назначен: {winner_display}")

# ========== 4. АВТОМАТИЧЕСКОЕ ЗАВЕРШЕНИЕ ПО ВРЕМЕНИ (ФИКС) ==========
def check_expired_giveaways():
    while True:
        try:
            now = datetime.now(TIMEZONE)
            c.execute("SELECT id, channel_message_id, end_time FROM giveaways WHERE status = 'active'")
            rows = c.fetchall()
            for row in rows:
                giveaway_id, msg_id, end_time_str = row
                end_time = datetime.strptime(end_time_str, "%Y-%m-%d %H:%M:%S")
                end_time = TIMEZONE.localize(end_time)
                if now >= end_time:
                    c.execute("UPDATE giveaways SET status = 'finished' WHERE id = ?", (giveaway_id,))
                    conn.commit()
                    bot.edit_message_reply_markup(CHANNEL_ID, msg_id, reply_markup=None)
                    bot.send_message(CHANNEL_ID, f"⏰ Розыгрыш #{giveaway_id} завершён по времени. Победитель не был выбран.")
        except Exception as e:
            print(f"Ошибка проверки: {e}")
        time.sleep(60)

# ========== 5. ОСТАЛЬНЫЕ ФУНКЦИИ ==========
@bot.callback_query_handler(func=lambda call: call.data == "participants_list")
def participants_menu(call):
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
        bot.send_message(ADMIN_ID, "📭 Нет участников")
        return
    text = f"👥 **УЧАСТНИКИ #{giveaway_id}**\n\n"
    for p in parts:
        text += f"• {p[2]} (@{p[1] or 'нет'}) — ID {p[0]}\n"
    bot.send_message(ADMIN_ID, text, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data == "list_giveaways")
def list_giveaways(call):
    c.execute("SELECT id, description, status, end_time FROM giveaways")
    rows = c.fetchall()
    if not rows:
        bot.send_message(ADMIN_ID, "Нет розыгрышей")
        return
    text = "📋 **РОЗЫГРЫШИ**\n\n"
    for r in rows:
        text += f"#{r[0]}: {r[1][:40]} | {r[2]} | до {r[3][:16]}\n"
    bot.send_message(ADMIN_ID, text, parse_mode='Markdown')

# ========== ЗАПУСК ==========
@app.route('/')
def home():
    return "Бот работает"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=check_expired_giveaways, daemon=True).start()
    print("✅ Бот запущен, всё исправлено")
    bot.infinity_polling()
