import telebot
from telebot import types
import threading
import time
import json
import os
from datetime import datetime, timedelta

# ==========================================
# ⚙️ СИСТЕМНЫЕ НАСТРОЙКИ
# ==========================================

TOKEN = '8255305162:AAFpTnNV_tcKwmX4m9a3Um-9m8HWGbq5arE'
ADMIN_ID = 1151803777  # Твой ID

bot = telebot.TeleBot(TOKEN)
DB_FILE = "students_db.json" # Файл, где будем хранить базу

# ==========================================
# 💾 СИСТЕМА СОХРАНЕНИЯ (ЧТОБЫ НЕ ЗАБЫВАЛ)
# ==========================================

def load_db():
    """Загружает базу из файла при запуске"""
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # JSON хранит ключи как строки, нам нужны числа (ID)
                return {int(k): v for k, v in data.items()}
        except:
            return {}
    return {}

def save_db():
    """Сохраняет базу в файл"""
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(users_db, f, ensure_ascii=False, indent=4)

# Загружаем базу сразу при запуске
users_db = load_db()
print(f"Загружено пользователей из базы: {len(users_db)}")

# ==========================================
# 🧠 ЛОГИКА БОТА
# ==========================================

BUTTONS = ["🔔 Настроить оповещение", "📅 Посмотреть расписание", 
           "🚩 Контрольные точки", "🏠 Домашние работы"]

@bot.message_handler(commands=['start'])
def start_command(message):
    user_id = message.chat.id
    
    # Если новенький - добавляем и сохраняем
    if user_id not in users_db:
        users_db[user_id] = {"notify": True, "time": 10}
        save_db() # <--- СОХРАНЯЕМ В ФАЙЛ
        print(f"Новый пользователь: {message.from_user.first_name} ({user_id})")
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(*[types.KeyboardButton(btn) for btn in BUTTONS])

    bot.send_message(
        user_id, 
        "Привет! Я тебя запомнил. Теперь я буду присылать расписание.",
        reply_markup=markup
    )

# --- 1. ОБРАБОТКА КНОПОК МЕНЮ ---
@bot.message_handler(func=lambda message: message.text in BUTTONS)
def menu_handler(message):
    user_id = message.chat.id
    text = message.text

    if text == "🔔 Настроить оповещение":
        send_settings_menu(user_id)
    elif text == "📅 Посмотреть расписание":
        bot.send_message(user_id, format_schedule(), parse_mode='HTML', disable_web_page_preview=True)
    elif text == "🚩 Контрольные точки":
        bot.send_message(user_id, INFO_CT, parse_mode='HTML')
    elif text == "🏠 Домашние работы":
        bot.send_message(user_id, INFO_HW, parse_mode='HTML')

# --- 2. УНИВЕРСАЛЬНАЯ РАССЫЛКА (АДМИН) ---
@bot.message_handler(content_types=['text', 'photo', 'video', 'document'])
def admin_broadcast(message):
    if message.chat.id == ADMIN_ID:
        
        bot.reply_to(message, f"🫡 Начинаю рассылку... (В базе: {len(users_db)} чел.)")
        count = 0
        caption_text = message.caption if message.caption else ""
        caption_full = f"📢 <b>ОБЪЯВЛЕНИЕ:</b>\n\n{caption_text}"

        # Проходимся по всем студентам
        for user_id in list(users_db.keys()):
            if user_id == ADMIN_ID: continue 
            
            try:
                if message.content_type == 'text':
                    bot.send_message(user_id, f"📢 <b>ОБЪЯВЛЕНИЕ:</b>\n\n{message.text}", parse_mode='HTML')
                elif message.content_type == 'photo':
                    bot.send_photo(user_id, message.photo[-1].file_id, caption=caption_full, parse_mode='HTML')
                elif message.content_type == 'video':
                    bot.send_video(user_id, message.video.file_id, caption=caption_full, parse_mode='HTML')
                elif message.content_type == 'document':
                    bot.send_document(user_id, message.document.file_id, caption=caption_full, parse_mode='HTML')
                count += 1
            except Exception as e:
                print(f"Не удалось отправить {user_id}: {e}")
        
        bot.send_message(ADMIN_ID, f"✅ Рассылка завершена. Доставлено: {count}")
    else:
        bot.send_message(message.chat.id, "Я понимаю только нажатия на кнопки меню 🤖")

# --- НАСТРОЙКИ И SCHEDULE ---

def send_settings_menu(user_id):
    settings = users_db.get(user_id, {"notify": True, "time": 10})
    status = "✅ Вкл" if settings['notify'] else "❌ Выкл"
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(f"Статус: {status}", callback_data="toggle_notify"))
    markup.add(types.InlineKeyboardButton(f"Время: {settings['time']} мин ⏳", callback_data="change_time"))
    bot.send_message(user_id, "⚙️ <b>Настройки:</b>", reply_markup=markup, parse_mode='HTML')

@bot.callback_query_handler(func=lambda call: True)
def callback_settings(call):
    user_id = call.message.chat.id
    if user_id not in users_db: 
        users_db[user_id] = {"notify": True, "time": 10}
        save_db()
        
    s = users_db[user_id]
    if call.data == "toggle_notify": s['notify'] = not s['notify']
    elif call.data == "change_time": s['time'] = 10 if s['time'] == 5 else (60 if s['time'] == 10 else 5)
    
    save_db() # Сохраняем изменения настроек
    
    status = "✅ Вкл" if s['notify'] else "❌ Выкл"
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(f"Статус: {status}", callback_data="toggle_notify"),
               types.InlineKeyboardButton(f"Время: {s['time']} мин ⏳", callback_data="change_time"))
    try: bot.edit_message_reply_markup(user_id, call.message.message_id, reply_markup=markup)
    except: pass

def format_schedule():
    text = "<b>🎓 РАСПИСАНИЕ:</b>\n\n"
    ru_days = {"Monday": "Понедельник", "Tuesday": "Вторник", "Wednesday": "Среда", "Thursday": "Четверг", "Friday": "Пятница"}
    for day, lessons in SCHEDULE.items():
        if not lessons: continue
        text += f"🗓 <b>{ru_days.get(day, day)}</b>\n"
        for l in lessons:
            ct = "🔴 КТ!" if l['ct'] else ""
            text += f"🕒 {l['time']} — {l['name']} {ct}\n🔗 <a href='{l['link']}'>Ссылка</a>\n\n"
    return text

def notification_loop():
    while True:
        try:
            now = datetime.now()
            day = now.strftime("%A")
            if day in SCHEDULE:
                for l in SCHEDULE[day]:
                    h, m = map(int, l['time'].split(":"))
                    start = now.replace(hour=h, minute=m, second=0, microsecond=0)
                    for uid, s in users_db.items():
                        if s['notify']:
                            notify_time = start - timedelta(minutes=s['time'])
                            if now.hour == notify_time.hour and now.minute == notify_time.minute:
                                bot.send_message(uid, f"⏰ <b>Пара через {s['time']} мин!</b>\n{l['name']}\n<a href='{l['link']}'>Ссылка</a>", parse_mode='HTML')
            time.sleep(60)
        except: time.sleep(60)

# ==========================================
# 📝 ДАННЫЕ
# ==========================================

INFO_HW = "<b>ДЗ:</b> <a href='https://google.com'>Таблица</a>"
INFO_CT = "<b>КТ:</b>\n15.10 - История"

SCHEDULE = {
    "Monday": [
        {"time": "12:30", "name": "Motion design", "link": "https://zoom.us/...", "ct": False},
        {"time": "14:40", "name": "Дизайн проектирование", "link": "https://zoom.us/...", "ct": True}
    ],
    "Tuesday": [
        {"time": "09:00", "name": "Высшая математика", "link": "https://meet.google.com/...", "ct": False}
    ],
    "Wednesday": [], "Thursday": [], "Friday": [], "Saturday": [], "Sunday": []
}

if __name__ == "__main__":
    t1 = threading.Thread(target=notification_loop, daemon=True)
    t1.start()
    
    print("Бот запущен! База данных сохраняется в файл students_db.json")
    try:
        bot.infinity_polling()
    except KeyboardInterrupt:
        print("\nБот остановлен.")
