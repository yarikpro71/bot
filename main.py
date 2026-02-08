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

# Шаблон контента по умолчанию (если файла нет)
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
                # Если читаем юзеров, ключи должны быть int
                if filename == FILES["users"]:
                    return {int(k): v for k, v in data.items()}
                return data
        except:
            return default if default else {}
    return default if default else {}

def save_json(filename, data):
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

# Загружаем данные при старте
users_db = load_json(FILES["users"], {})
content_db = load_json(FILES["content"], DEFAULT_CONTENT)

# ==========================================
# 🧠 ЛОГИКА БОТА
# ==========================================

USER_BUTTONS = ["📅 Расписание", "🚩 Контрольные точки", "🏠 Домашние работы", "🔔 Настройки"]
ADMIN_BUTTONS = ["✏️ Ред. ДЗ", "✏️ Ред. КТ", "📥 Загрузить Расписание (JSON)"]

@bot.message_handler(commands=['start'])
def start_command(message):
    user_id = message.chat.id
    if user_id not in users_db:
        users_db[user_id] = {"notify": True, "time": 10}
        save_json(FILES["users"], users_db)
    
    show_main_menu(user_id)

def show_main_menu(user_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    # Кнопки для всех
    markup.add(types.KeyboardButton("📅 Расписание"), types.KeyboardButton("🏠 Домашние работы"))
    markup.add(types.KeyboardButton("🚩 Контрольные точки"), types.KeyboardButton("🔔 Настройки"))
    
    # Кнопки только для Админа
    if user_id == ADMIN_ID:
        markup.add(types.KeyboardButton("✏️ Ред. ДЗ"), types.KeyboardButton("✏️ Ред. КТ"))
        markup.add(types.KeyboardButton("📥 Загрузить Расписание (JSON)"))

    bot.send_message(user_id, "Меню:", reply_markup=markup)

# --- ОБРАБОТКА ОБЫЧНЫХ КНОПОК ---
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
# 🛠 АДМИН-ПАНЕЛЬ (РЕДАКТИРОВАНИЕ)
# ==========================================

@bot.message_handler(func=lambda m: m.text in ADMIN_BUTTONS and m.chat.id == ADMIN_ID)
def admin_menu(message):
    text = message.text
    
    if text == "✏️ Ред. ДЗ":
        msg = bot.send_message(ADMIN_ID, "✍️ <b>Введи новый текст для Домашних заданий:</b>\n(Можно кинуть ссылку или картинку с подписью)", parse_mode='HTML')
        bot.register_next_step_handler(msg, process_update_hw) # Ждем следующего сообщения
        
    elif text == "✏️ Ред. КТ":
        msg = bot.send_message(ADMIN_ID, "✍️ <b>Введи список Контрольных точек:</b>", parse_mode='HTML')
        bot.register_next_step_handler(msg, process_update_ct)

    elif text == "📥 Загрузить Расписание (JSON)":
        # Создаем пример файла, чтобы админ знал формат
        example = json.dumps(content_db["schedule"], ensure_ascii=False, indent=4)
        with open("schedule_example.json", "w", encoding="utf-8") as f:
            f.write(example)
        
        with open("schedule_example.json", "rb") as f:
            bot.send_document(ADMIN_ID, f, caption="📂 Пришли мне .json файл с новым расписанием.\nВот пример текущего формата (открой, отредактируй и пришли назад).")
        
        bot.register_next_step_handler(message, process_update_schedule)

# --- ФУНКЦИИ СОХРАНЕНИЯ (СЛЕДУЮЩИЙ ШАГ) ---

def process_update_hw(message):
    if message.content_type == 'text':
        content_db["hw"] = message.text
        save_json(FILES["content"], content_db)
        bot.send_message(ADMIN_ID, "✅ Информация о ДЗ обновлена!")
    else:
        bot.send_message(ADMIN_ID, "❌ Пришли мне именно текст (или текст со ссылкой).")

def process_update_ct(message):
    if message.content_type == 'text':
        content_db["ct"] = message.text
        save_json(FILES["content"], content_db)
        bot.send_message(ADMIN_ID, "✅ Информация о КТ обновлена!")
    else:
        bot.send_message(ADMIN_ID, "❌ Нужен текст.")

def process_update_schedule(message):
    if message.content_type == 'document':
        try:
            file_info = bot.get_file(message.document.file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            
            # Пытаемся прочитать как JSON
            new_schedule = json.loads(downloaded_file.decode('utf-8'))
            
            # Простая проверка, есть ли там дни недели
            if "Monday" in new_schedule:
                content_db["schedule"] = new_schedule
                save_json(FILES["content"], content_db)
                bot.send_message(ADMIN_ID, "✅ Расписание успешно обновлено!")
            else:
                bot.send_message(ADMIN_ID, "❌ Ошибка: В файле нет дней недели (Monday и т.д.).")
        except Exception as e:
            bot.send_message(ADMIN_ID, f"❌ Ошибка в файле: {e}")
    else:
        bot.send_message(ADMIN_ID, "❌ Это не файл. Отмена.")

# ==========================================
# 📨 РАССЫЛКА (АДМИН)
# ==========================================
@bot.message_handler(content_types=['text', 'photo', 'video', 'document'])
def admin_broadcast(message):
    if message.chat.id != ADMIN_ID: return # Игнорируем обычных юзеров
    if message.text in USER_BUTTONS or message.text in ADMIN_BUTTONS: return

    bot.reply_to(message, f"📢 Рассылаю...")
    count = 0
    caption_full = f"📢 <b>ОБЪЯВЛЕНИЕ:</b>\n\n{message.caption if message.caption else ''}"
    
    for user_id in list(users_db.keys()):
        if user_id == ADMIN_ID: continue
        try:
            if message.content_type == 'text':
                bot.send_message(user_id, f"📢 <b>ОБЪЯВЛЕНИЕ:</b>\n\n{message.text}", parse_mode='HTML')
            elif message.content_type == 'photo':
                bot.send_photo(user_id, message.photo[-1].file_id, caption=caption_full, parse_mode='HTML')
            elif message.content_type == 'document':
                bot.send_document(user_id, message.document.file_id, caption=caption_full, parse_mode='HTML')
            count += 1
        except: pass
    
    bot.send_message(ADMIN_ID, f"✅ Доставлено: {count}")

# ==========================================
# ⚙️ ВСПОМОГАТЕЛЬНОЕ
# ==========================================

def send_settings_menu(user_id):
    s = users_db.get(user_id, {"notify": True, "time": 10})
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(f"Статус: {'✅' if s['notify'] else '❌'}", callback_data="toggle"))
    markup.add(types.InlineKeyboardButton(f"Время: {s['time']} мин ⏳", callback_data="time"))
    bot.send_message(user_id, "⚙️ Настройки:", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: True)
def callback(c):
    uid = c.message.chat.id
    if uid not in users_db: users_db[uid] = {"notify": True, "time": 10}
    
    if c.data == "toggle": users_db[uid]['notify'] = not users_db[uid]['notify']
    elif c.data == "time": users_db[uid]['time'] = 10 if users_db[uid]['time'] == 5 else (60 if users_db[uid]['time'] == 10 else 5)
    
    save_json(FILES["users"], users_db)
    send_settings_menu(uid) # Обновляем меню

def format_schedule():
    text = "<b>🎓 РАСПИСАНИЕ:</b>\n\n"
    ru_days = {"Monday": "Понедельник", "Tuesday": "Вторник", "Wednesday": "Среда", "Thursday": "Четверг", "Friday": "Пятница", "Saturday": "Суббота", "Sunday": "Воскресенье"}
    
    sched = content_db.get("schedule", {})
    
    for day, lessons in sched.items():
        if not lessons: continue
        text += f"🗓 <b>{ru_days.get(day, day)}</b>\n"
        for l in lessons:
            ct = "🔴 КТ!" if l.get('ct') else ""
            text += f"🕒 {l['time']} — {l['name']} {ct}\n🔗 <a href='{l['link']}'>Ссылка</a>\n\n"
    return text

def notification_loop():
    while True:
        try:
            now = datetime.now()
            day = now.strftime("%A")
            sched = content_db.get("schedule", {})
            
            if day in sched:
                for l in sched[day]:
                    h, m = map(int, l['time'].split(":"))
                    start = now.replace(hour=h, minute=m, second=0, microsecond=0)
                    for uid, s in users_db.items():
                        if s['notify']:
                            ntilde = start - timedelta(minutes=s['time'])
                            if now.hour == ntilde.hour and now.minute == ntilde.minute:
                                bot.send_message(uid, f"⏰ <b>Пара через {s['time']} мин!</b>\n{l['name']}\n<a href='{l['link']}'>Ссылка</a>", parse_mode='HTML')
            time.sleep(60)
        except: time.sleep(60)

if __name__ == "__main__":
    t = threading.Thread(target=notification_loop, daemon=True)
    t.start()
    print("Бот запущен!")
    bot.infinity_polling()
