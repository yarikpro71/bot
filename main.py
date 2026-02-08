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
ADMIN_BUTTONS = ["✏️ Ред. ДЗ", "✏️ Ред. КТ", "✏️ Ред. Расписание", "📢 Сделать рассылку"]

@bot.message_handler(commands=['start'])
def start_command(message):
    user_id = message.chat.id
    if user_id not in users_db:
        users_db[user_id] = {"notify": True, "time": 10}
        save_json(FILES["users"], users_db)
    show_main_menu(user_id)

def show_main_menu(user_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    # Кнопки студента
    markup.add("📅 Расписание", "🏠 Домашние работы", "🚩 Контрольные точки", "🔔 Настройки")
    
    # Кнопки админа
    if user_id == ADMIN_ID:
        markup.add("✏️ Ред. ДЗ", "✏️ Ред. КТ")
        markup.add("✏️ Ред. Расписание", "📢 Сделать рассылку")

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
# 🛠 РЕДАКТИРОВАНИЕ РАСПИСАНИЯ
# ==========================================

@bot.message_handler(func=lambda m: m.text == "✏️ Ред. Расписание" and m.chat.id == ADMIN_ID)
def start_edit_schedule(message):
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
        day_code = call.data.split('_')[2]
        edit_cache[ADMIN_ID] = {"day": day_code, "lessons": []}
        
        markup = types.InlineKeyboardMarkup(row_width=3)
        btns = [types.InlineKeyboardButton(str(i), callback_data=f"edit_count_{i}") for i in range(6)]
        markup.add(*btns)
        
        ru_day = {"Monday":"Понедельник","Tuesday":"Вторник","Wednesday":"Среда","Thursday":"Четверг","Friday":"Пятница","Saturday":"Суббота","Sunday":"Воскресенье"}[day_code]
        
        bot.edit_message_text(f"Выбран день: <b>{ru_day}</b>.\nСколько будет пар?", 
                              ADMIN_ID, call.message.message_id, reply_markup=markup, parse_mode='HTML')

    elif action == "count":
        count = int(call.data.split('_')[2])
        edit_cache[ADMIN_ID]["total"] = count
        
        if count == 0:
            day = edit_cache[ADMIN_ID]["day"]
            content_db["schedule"][day] = []
            save_json(FILES["content"], content_db)
            bot.edit_message_text(f"✅ Расписание на этот день очищено (0 пар).", ADMIN_ID, call.message.message_id)
            edit_cache.pop(ADMIN_ID, None)
        else:
            ask_lesson_time(ADMIN_ID, 1)

def ask_lesson_time(user_id, lesson_num):
    msg = bot.send_message(user_id, f"1️⃣ <b>Пара №{lesson_num}</b>\n\nВведите время начала (например: <code>09:00</code>):", parse_mode='HTML')
    bot.register_next_step_handler(msg, process_time, lesson_num)

def process_time(message, lesson_num):
    if message.text.lower() == "отмена": return bot.send_message(ADMIN_ID, "❌ Отменено.")
    current_lesson = {"time": message.text}
    edit_cache[ADMIN_ID]["temp_lesson"] = current_lesson
    msg = bot.send_message(ADMIN_ID, f"2️⃣ Введите <b>название предмета</b>:")
    bot.register_next_step_handler(msg, process_name, lesson_num)

def process_name(message, lesson_num):
    edit_cache[ADMIN_ID]["temp_lesson"]["name"] = message.text
    msg = bot.send_message(ADMIN_ID, f"3️⃣ Вставьте <b>ссылку</b> (или напишите '-', если нет):")
    bot.register_next_step_handler(msg, process_link, lesson_num)

def process_link(message, lesson_num):
    link = message.text
    if link == "-": link = ""
    edit_cache[ADMIN_ID]["temp_lesson"]["link"] = link
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Да, есть КТ", callback_data=f"set_ct_yes_{lesson_num}"),
               types.InlineKeyboardButton("Нет", callback_data=f"set_ct_no_{lesson_num}"))
    bot.send_message(ADMIN_ID, "4️⃣ Будет ли <b>Контрольная Точка (КТ)</b>?", reply_markup=markup, parse_mode='HTML')

@bot.callback_query_handler(func=lambda call: call.data.startswith('set_ct_'))
def callback_set_ct(call):
    if call.message.chat.id != ADMIN_ID: return
    data = call.data.split('_')
    is_ct = (data[2] == "yes")
    lesson_num = int(data[3])
    edit_cache[ADMIN_ID]["temp_lesson"]["ct"] = is_ct
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("✍️ Написать сообщение", callback_data=f"set_note_yes_{lesson_num}"),
               types.InlineKeyboardButton("Без сообщения", callback_data=f"set_note_no_{lesson_num}"))
    bot.edit_message_text("5️⃣ Хотите добавить <b>комментарий/заметку</b> к этой паре?", 
                          ADMIN_ID, call.message.message_id, reply_markup=markup, parse_mode='HTML')

@bot.callback_query_handler(func=lambda call: call.data.startswith('set_note_'))
def callback_set_note(call):
    if call.message.chat.id != ADMIN_ID: return
    choice = call.data.split('_')[2]
    lesson_num = int(call.data.split('_')[3])
    if choice == "yes":
        msg = bot.send_message(ADMIN_ID, "✍️ Введите текст сообщения для этой пары:")
        bot.register_next_step_handler(msg, process_note_text, lesson_num)
    else:
        edit_cache[ADMIN_ID]["temp_lesson"]["note"] = ""
        finish_lesson(lesson_num)

def process_note_text(message, lesson_num):
    edit_cache[ADMIN_ID]["temp_lesson"]["note"] = message.text
    finish_lesson(lesson_num)

def finish_lesson(lesson_num):
    lesson_data = edit_cache[ADMIN_ID]["temp_lesson"]
    edit_cache[ADMIN_ID]["lessons"].append(lesson_data)
    total = edit_cache[ADMIN_ID]["total"]
    if lesson_num < total:
        bot.send_message(ADMIN_ID, "✅ Пара сохранена. Следующая...")
        ask_lesson_time(ADMIN_ID, lesson_num + 1)
    else:
        day = edit_cache[ADMIN_ID]["day"]
        content_db["schedule"][day] = edit_cache[ADMIN_ID]["lessons"]
        save_json(FILES["content"], content_db)
        bot.send_message(ADMIN_ID, f"🎉 <b>Готово!</b> Расписание на этот день обновлено.", parse_mode='HTML')
        edit_cache.pop(ADMIN_ID, None)

# ==========================================
# 🛠 АДМИН-ПАНЕЛЬ (ДЗ и КТ)
# ==========================================

@bot.message_handler(func=lambda m: m.text == "✏️ Ред. ДЗ" and m.chat.id == ADMIN_ID)
def edit_hw(message):
    msg = bot.send_message(ADMIN_ID, "✍️ Введи новый текст для <b>ДЗ</b>:", parse_mode='HTML')
    bot.register_next_step_handler(msg, save_hw)

def save_hw(message):
    content_db["hw"] = message.text
    save_json(FILES["content"], content_db)
    bot.send_message(ADMIN_ID, "✅ ДЗ обновлено.")

@bot.message_handler(func=lambda m: m.text == "✏️ Ред. КТ" and m.chat.id == ADMIN_ID)
def edit_ct(message):
    msg = bot.send_message(ADMIN_ID, "✍️ Введи новый текст для <b>КТ</b>:", parse_mode='HTML')
    bot.register_next_step_handler(msg, save_ct)

def save_ct(message):
    content_db["ct"] = message.text
    save_json(FILES["content"], content_db)
    bot.send_message(ADMIN_ID, "✅ КТ обновлено.")

# ==========================================
# 📢 НОВАЯ ЛОГИКА РАССЫЛКИ
# ==========================================

# 1. Нажимаем кнопку "Сделать рассылку"
@bot.message_handler(func=lambda m: m.text == "📢 Сделать рассылку" and m.chat.id == ADMIN_ID)
def start_broadcast(message):
    msg = bot.send_message(ADMIN_ID, "📝 <b>Отправь сообщение</b> (текст, фото, видео или файл), которое нужно разослать всем студентам.\n\nНапиши <code>Отмена</code>, если передумал.", parse_mode='HTML')
    bot.register_next_step_handler(msg, perform_broadcast)

# 2. Бот ждет сообщение и рассылает его
def perform_broadcast(message):
    if message.content_type == 'text' and message.text.lower() == "отмена":
        return bot.send_message(ADMIN_ID, "❌ Рассылка отменена.")

    bot.reply_to(message, f"📢 Начинаю рассылку...")
    
    count = 0
    caption_full = f"📢 <b>ОБЪЯВЛЕНИЕ:</b>\n\n{message.caption if message.caption else ''}"
    
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
        except: pass
    
    bot.send_message(ADMIN_ID, f"✅ Рассылка завершена. Доставлено: {count}")

# ==========================================
# ⚙️ НАСТРОЙКИ И ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ==========================================

def send_settings_menu(user_id):
    s = users_db.get(user_id, {"notify": True, "time": 10})
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(f"Статус: {'✅' if s['notify'] else '❌'}", callback_data="toggle"))
    markup.add(types.InlineKeyboardButton(f"Время: {s['time']} мин ⏳", callback_data="time"))
    bot.send_message(user_id, "⚙️ Настройки:", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data in ["toggle", "time"])
def callback_settings_actions(c):
    uid = c.message.chat.id
    if uid not in users_db: users_db[uid] = {"notify": True, "time": 10}
    
    if c.data == "toggle": users_db[uid]['notify'] = not users_db[uid]['notify']
    elif c.data == "time": users_db[uid]['time'] = 10 if users_db[uid]['time'] == 5 else (60 if users_db[uid]['time'] == 10 else 5)
    
    save_json(FILES["users"], users_db)

    s = users_db[uid]
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(f"Статус: {'✅' if s['notify'] else '❌'}", callback_data="toggle"))
    markup.add(types.InlineKeyboardButton(f"Время: {s['time']} мин ⏳", callback_data="time"))
    
    try:
        bot.edit_message_reply_markup(chat_id=uid, message_id=c.message.message_id, reply_markup=markup)
    except: pass

def format_schedule():
    text = "<b>🎓 РАСПИСАНИЕ:</b>\n\n"
    ru_days = {"Monday": "Понедельник", "Tuesday": "Вторник", "Wednesday": "Среда", "Thursday": "Четверг", "Friday": "Пятница", "Saturday": "Суббота", "Sunday": "Воскресенье"}
    
    sched = content_db.get("schedule", {})
    
    for day, lessons in sched.items():
        if not lessons: continue
        text += f"🗓 <b>{ru_days.get(day, day)}</b>\n"
        for l in lessons:
            ct = "🔴 КТ!" if l.get('ct') else ""
            note = f"\n📝 <i>{l['note']}</i>" if l.get('note') else ""
            link_text = f"\n🔗 <a href='{l['link']}'>Ссылка</a>" if l.get('link') else ""
            text += f"🕒 {l['time']} — {l['name']} {ct}{link_text}{note}\n\n"
        text += "------------------\n"
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
                                note = f"\n\n📝 {l['note']}" if l.get('note') else ""
                                link = f"\n🔗 <a href='{l['link']}'>Подключиться</a>" if l.get('link') else ""
                                msg = f"⏰ <b>Пара через {s['time']} мин!</b>\n{l['name']}{link}{note}"
                                bot.send_message(uid, msg, parse_mode='HTML')
            time.sleep(60)
        except: time.sleep(60)

if __name__ == "__main__":
    t = threading.Thread(target=notification_loop, daemon=True)
    t.start()
    print("Бот запущен!")
    bot.infinity_polling()
