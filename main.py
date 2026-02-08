import telebot
from telebot import types
import threading
import time
import json
import os
from datetime import datetime, timedelta

# ==========================================
# ⚙️ НАСТРОЙКИ
# ==========================================

TOKEN = '8502946152:AAFjl9jbD-iqYbx3aCp3BcXBTWNT0O4DQIw'
ADMIN_ID = 1151803777  # Твой ID

bot = telebot.TeleBot(TOKEN)

FILES = {
    "users": "students_db.json",
    "content": "content.json"
}

# Временное хранилище для процесса редактирования
# admin_state[ADMIN_ID] = { "day": "Monday", "count": 2, "current": 0, "lessons": [] }
edit_cache = {}

DEFAULT_CONTENT = {
    "hw": "<b>ДЗ:</b> Пока пусто.",
    "ct": "<b>КТ:</b> Информации нет.",
    "schedule": {
        "Monday": [], "Tuesday": [], "Wednesday": [], 
        "Thursday": [], "Friday": [], "Saturday": [], "Sunday": []
    }
}

# ==========================================
# 💾 РАБОТА С ФАЙЛАМИ
# ==========================================

def load_json(filename, default=None):
    if os.path.exists(filename):
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if filename == FILES["users"]:
                    return {int(k): v for k, v in data.items()}
                return data
        except:
            return default if default else {}
    return default if default else {}

def save_json(filename, data):
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

users_db = load_json(FILES["users"], {})
content_db = load_json(FILES["content"], DEFAULT_CONTENT)

# ==========================================
# 🧠 ЛОГИКА МЕНЮ
# ==========================================

USER_BUTTONS = ["📅 Расписание", "🚩 Контрольные точки", "🏠 Домашние работы", "🔔 Настройки"]
ADMIN_BUTTONS = ["✏️ Ред. ДЗ", "✏️ Ред. КТ", "✏️ Ред. Расписание"]

@bot.message_handler(commands=['start'])
def start_command(message):
    user_id = message.chat.id
    if user_id not in users_db:
        users_db[user_id] = {"notify": True, "time": 10}
        save_json(FILES["users"], users_db)
    show_main_menu(user_id)

def show_main_menu(user_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("📅 Расписание", "🏠 Домашние работы", "🚩 Контрольные точки", "🔔 Настройки")
    
    if user_id == ADMIN_ID:
        markup.add("✏️ Ред. ДЗ", "✏️ Ред. КТ")
        markup.add("✏️ Ред. Расписание")

    bot.send_message(user_id, "Главное меню:", reply_markup=markup)

# --- ОБРАБОТКА ПОЛЬЗОВАТЕЛЬСКИХ КНОПОК ---
@bot.message_handler(func=lambda m: m.text in USER_BUTTONS)
def user_menu(message):
    text = message.text
    user_id = message.chat.id

    if text == "📅 Расписание":
        bot.send_message(user_id, format_schedule(), parse_mode='HTML', disable_web_page_preview=True)
    elif text == "🏠 Домашние работы":
        bot.send_message(user_id, content_db["hw"], parse_mode='HTML')
    elif text == "🚩 Контрольные точки":
        bot.send_message(user_id, content_db["ct"], parse_mode='HTML')
    elif text == "🔔 Настройки":
        send_settings_menu(user_id)

# ==========================================
# 🛠 РЕДАКТИРОВАНИЕ РАСПИСАНИЯ (НОВАЯ ЛОГИКА)
# ==========================================

@bot.message_handler(func=lambda m: m.text == "✏️ Ред. Расписание" and m.chat.id == ADMIN_ID)
def start_edit_schedule(message):
    # Шаг 1: Выбор дня
    markup = types.InlineKeyboardMarkup(row_width=2)
    days = [("Понедельник", "Monday"), ("Вторник", "Tuesday"), ("Среда", "Wednesday"),
            ("Четверг", "Thursday"), ("Пятница", "Friday"), ("Суббота", "Saturday"), ("Воскресенье", "Sunday")]
    
    buttons = [types.InlineKeyboardButton(text, callback_data=f"edit_day_{code}") for text, code in days]
    markup.add(*buttons)
    markup.add(types.InlineKeyboardButton("❌ Отмена", callback_data="edit_cancel"))
    
    bot.send_message(ADMIN_ID, "🗓 <b>Выбери день недели для редактирования:</b>", reply_markup=markup, parse_mode='HTML')

@bot.callback_query_handler(func=lambda call: call.data.startswith('edit_'))
def callback_edit_schedule(call):
    if call.message.chat.id != ADMIN_ID: return
    action = call.data.split('_')[1]

    if action == "cancel":
        bot.delete_message(ADMIN_ID, call.message.message_id)
        bot.send_message(ADMIN_ID, "Редактирование отменено.")
        edit_cache.pop(ADMIN_ID, None)
        return

    if action == "day":
        # Шаг 2: Выбор количества пар
        day_code = call.data.split('_')[2]
        edit_cache[ADMIN_ID] = {"day": day_code, "lessons": []} # Инициализируем кэш
        
        markup = types.Inline
