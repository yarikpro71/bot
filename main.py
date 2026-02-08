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

# Временное хранилище
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
# 🟢 ГЛАВНЫЙ ВХОД (/start)
# ==========================================

@bot.message_handler(commands=['start'])
def start_command(message):
    user_id = message.chat.id
    if user_id not in users_db:
        users_db[user_id] = {"notify": True, "time": 10}
        save_json(FILES["users"], users_db)

    # Единственная кнопка внизу - ReplyKeyboard
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("📂 Открыть меню"))

    bot.send_message(
        user_id,
        f"👋 <b>Привет, {message.from_user.first_name}!</b>\n\n"
        "Я бот-помощник. Тут ты можешь узнать расписание, домашку и настроить уведомления.\n\n"
        "👇 <b>Нажми кнопку внизу, чтобы начать.</b>",
        reply_markup=markup,
        parse_mode='HTML'
    )

# ==========================================
# 📱 ОБРАБОТЧИК КНОПКИ "ОТКРЫТЬ МЕНЮ"
# ==========================================

@bot.message_handler(func=lambda m: m.text == "📂 Открыть меню")
def open_menu_handler(message):
    # Отправляем новое сообщение с Inline-меню
    send_main_menu(message.chat.id)

def send_main_menu(chat_id, message_id=None):
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    # Кнопки для всех
    btn1 = types.InlineKeyboardButton("📅 Расписание", callback_data="menu_schedule")
    btn2 = types.InlineKeyboardButton("🏠 Домашние работы", callback_data="menu_hw")
    btn3 = types.InlineKeyboardButton("🚩 Контрольные точки", callback_data="menu_ct")
    btn4 = types.InlineKeyboardButton("🔔 Настройки уведомлений", callback_data="menu_settings")
    
    markup.add(btn1, btn2)
    markup.add(btn3, btn4)

    # Кнопки админа
    if chat_id == ADMIN_ID:
        markup.add(types.InlineKeyboardButton("➖➖➖➖ АДМИНКА ➖➖➖➖", callback_data="ignore"))
        markup.add(types.InlineKeyboardButton("✏️ Ред. ДЗ", callback_data="admin_edit_hw"),
                   types.InlineKeyboardButton("✏️ Ред. КТ", callback_data="admin_edit_ct"))
        markup.add(types.InlineKeyboardButton("✏️ Ред. Расписание", callback_data="admin_edit_sched"))
        markup.add(types.InlineKeyboardButton("📢 Сделать рассылку", callback_data="admin_broadcast"))

    text = "📂 <b>ГЛАВНОЕ МЕНЮ</b>\nВыберите нужный раздел:"
    
    if message_id:
        try:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=markup, parse_mode='HTML')
        except:
            bot.send_message(chat_id, text, reply_markup=markup, parse_mode='HTML')
    else:
        bot.send_message(chat_id, text, reply_markup=markup, parse_mode='HTML')

# ==========================================
# 🕹️ ЛОГИКА CALLBACK (НАВИГАЦИЯ)
# ==========================================

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    chat_id = call.message.chat.id
    data = call.data

    # --- 🔙 КНОПКА НАЗАД ---
    if data == "back_to_main":
        send_main_menu(chat_id, call.message.message_id)
        return

    # --- 📅 РАСПИСАНИЕ ---
    if data == "menu_schedule":
        text = format_schedule()
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main"))
        bot.edit_message_text(text, chat_id, call.message.message_id, reply_markup=markup, parse_mode='HTML', disable_web_page_preview=True)

    # --- 🏠 ДОМАШКА ---
    elif data == "menu_hw":
        text = content_db["hw"]
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main"))
        bot.edit_message_text(text, chat_id, call.message.message_id, reply_markup=markup, parse_mode='HTML', disable_web_page_preview=True)

    # --- 🚩 КОНТРОЛЬНЫЕ ТОЧКИ ---
    elif data == "menu_ct":
        text = content_db["ct"]
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main"))
        bot.edit_message_text(text, chat_id, call.message.message_id, reply_markup=markup, parse_mode='HTML')

    # --- 🔔 НАСТРОЙКИ ---
    elif data == "menu_settings" or data.startswith("set_"):
        # Логика переключения
        if chat_id not in users_db: users_db[chat_id] = {"notify": True, "time": 10}
        
        if data == "set_toggle": users_db[chat_id]['notify'] = not users_db[chat_id]['notify']
        elif data == "set_time": 
            t = users_db[chat_id]['time']
            users_db[chat_id]['time'] = 10 if t == 5 else (60 if t == 10 else 5)
        
        if data.startswith("set_"): save_json(FILES["users"], users_db)

        # Рисуем меню настроек
        s = users_db[chat_id]
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(f"Рассылка: {'✅ ВКЛ' if s['notify'] else '❌ ВЫКЛ'}", callback_data="set_toggle"))
        markup.add(types.InlineKeyboardButton(f"Время: за {s['time']} мин ⏳", callback_data="set_time"))
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main"))
        
        text = "⚙️ <b>Настройки уведомлений:</b>\nЗдесь вы можете включить/выключить напоминания о парах и выбрать время."
        
        try:
            bot.edit_message_text(text, chat_id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
        except: pass

    # ==========================
    # 👮‍♂️ АДМИНСКИЕ ФУНКЦИИ
    # ==========================
    
    # --- ✏️ РЕД. ДЗ и КТ ---
    elif data in ["admin_edit_hw", "admin_edit_ct"]:
        if chat_id != ADMIN_ID: return
        target = "ДЗ" if data == "admin_edit_hw" else "КТ"
        bot.delete_message(chat_id, call.message.message_id) # Удаляем меню, чтобы не мешало
        msg = bot.send_message(chat_id, f"✍️ Введите новый текст для <b>{target}</b>:\n(или напишите <code>Отмена</code>)", parse_mode='HTML')
        bot.register_next_step_handler(msg, process_admin_text, data)

    # --- 📢 РАССЫЛКА ---
    elif data == "admin_broadcast":
        if chat_id != ADMIN_ID: return
        bot.delete_message(chat_id, call.message.message_id)
        msg = bot.send_message(chat_id, "📝 <b>Отправь сообщение для рассылки</b> (текст, фото, файл...)\nНапиши <code>Отмена</code> для выхода.", parse_mode='HTML')
        bot.register_next_step_handler(msg, process_broadcast)

    # --- ✏️ РЕД. РАСПИСАНИЕ (ВЫБОР ДНЯ) ---
    elif data == "admin_edit_sched":
        if chat_id != ADMIN_ID: return
        show_schedule_editor(chat_id, call.message.message_id)

    # --- ЛОГИКА РЕДАКТОРА РАСПИСАНИЯ ---
    elif data.startswith("edit_"):
        handle_schedule_editor(call)

# ==========================================
# 🛠 ФУНКЦИИ АДМИНКИ
# ==========================================

def process_admin_text(message, action):
    if message.text and message.text.lower() == "отмена":
        send_main_menu(message.chat.id)
        return

    if action == "admin_edit_hw":
        content_db["hw"] = message.text
        bot.send_message(message.chat.id, "✅ Домашнее задание обновлено!")
    elif action == "admin_edit_ct":
        content_db["ct"] = message.text
        bot.send_message(message.chat.id, "✅ Контрольные точки обновлены!")
    
    save_json(FILES["content"], content_db)
    time.sleep(1)
    send_main_menu(message.chat.id) # Возвращаем меню

def process_broadcast(message):
    if message.text and message.text.lower() == "отмена":
        send_main_menu(message.chat.id)
        return

    bot.send_message(ADMIN_ID, "📢 Начинаю рассылку...")
    count = 0
    # Отправляем копию сообщения всем
    for uid in users_db:
        if uid == ADMIN_ID: continue
        try:
            bot.copy_message(uid, message.chat.id, message.message_id)
            count += 1
        except: pass
    
    bot.send_message(ADMIN_ID, f"✅ Рассылка завершена. Доставлено: {count}")
    time.sleep(1)
    send_main_menu(ADMIN_ID)

# ==========================================
# 🗓 ЛОГИКА РЕДАКТОРА РАСПИСАНИЯ
# ==========================================

def show_schedule_editor(chat_id, message_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    days = [("Понедельник", "Monday"), ("Вторник", "Tuesday"), ("Среда", "Wednesday"),
            ("Четверг", "Thursday"), ("Пятница", "Friday"), ("Суббота", "Saturday"), ("Воскресенье", "Sunday")]
    
    btns = [types.InlineKeyboardButton(text, callback_data=f"edit_day_{code}") for text, code in days]
    markup.add(*btns)
    markup.add(types.InlineKeyboardButton("🗑 Удалить всё расписание", callback_data="edit_clear_check"))
    markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main"))
    
    bot.edit_message_text("🗓 <b>Редактор расписания:</b>\nВыберите день или действие.", chat_id, message_id, reply_markup=markup, parse_mode='HTML')

def handle_schedule_editor(call):
    chat_id = call.message.chat.id
    data = call.data
    action = data.split('_')[1] # day, count, clear...

    # --- УДАЛЕНИЕ ВСЕГО ---
    if action == "clear": # edit_clear_check
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔥 Да, удалить ВСЁ", callback_data="edit_confirm_del"))
        markup.add(types.InlineKeyboardButton("❌ Нет, отмена", callback_data="admin_edit_sched"))
        bot.edit_message_text("⚠️ <b>Вы уверены?</b>\nЭто очистит расписание на всю неделю.", chat_id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
    
    elif action == "confirm": # edit_confirm_del
        for day in content_db["schedule"]: content_db["schedule"][day] = []
        save_json(FILES["content"], content_db)
        bot.answer_callback_query(call.id, "Расписание очищено")
        show_schedule_editor(chat_id, call.message.message_id)

    # --- ВЫБОР ДНЯ ---
    elif action == "day":
        day_code = data.split('_')[2]
        edit_cache[chat_id] = {"day": day_code, "lessons": []}
        
        markup = types.InlineKeyboardMarkup(row_width=3)
        btns = [types.InlineKeyboardButton(str(i), callback_data=f"edit_count_{i}") for i in range(6)]
        markup.add(*btns)
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="admin_edit_sched"))
        
        ru = {"Monday":"ПН","Tuesday":"ВТ","Wednesday":"СР","Thursday":"ЧТ","Friday":"ПТ","Saturday":"СБ","Sunday":"ВС"}
        bot.edit_message_text(f"День: <b>{ru[day_code]}</b>. Сколько пар?", chat_id, call.message.message_id, reply_markup=markup, parse_mode='HTML')

    # --- КОЛИЧЕСТВО ПАР ---
    elif action == "count":
        count = int(data.split('_')[2])
        edit_cache[chat_id]["total"] = count
        
        if count == 0:
            day = edit_cache[chat_id]["day"]
            content_db["schedule"][day] = []
            save_json(FILES["content"], content_db)
            bot.answer_callback_query(call.id, "Очищено")
            show_schedule_editor(chat_id, call.message.message_id)
        else:
            # Переходим к текстовому вводу (удаляем инлайн, пишем текст)
            bot.delete_message(chat_id, call.message.message_id)
            ask_lesson_time(chat_id, 1)

# --- ЦЕПОЧКА ВОПРОСОВ (ТЕКСТОМ) ---
def ask_lesson_time(chat_id, num):
    msg = bot.send_message(chat_id, f"1️⃣ <b>Пара №{num}</b>\nВведите время (09:00):", parse_mode='HTML')
    bot.register_next_step_handler(msg, process_time, num)

def process_time(message, num):
    if message.text.lower() == "отмена": return send_main_menu(message.chat.id)
    edit_cache[message.chat.id]["temp"] = {"time": message.text}
    msg = bot.send_message(message.chat.id, "2️⃣ Название предмета:")
    bot.register_next_step_handler(msg, process_name, num)

def process_name(message, num):
    edit_cache[message.chat.id]["temp"]["name"] = message.text
    msg = bot.send_message(message.chat.id, "3️⃣ Ссылка (или '-'):")
    bot.register_next_step_handler(msg, process_link, num)

def process_link(message, num):
    link = message.text if message.text != "-" else ""
    edit_cache[message.chat.id]["temp"]["link"] = link
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Да", callback_data=f"save_ct_yes_{num}"), types.InlineKeyboardButton("Нет", callback_data=f"save_ct_no_{num}"))
    bot.send_message(message.chat.id, "4️⃣ Есть КТ?", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("save_ct_"))
def save_ct_callback(call):
    data = call.data.split('_')
    is_ct = (data[2] == "yes")
    num = int(data[3])
    chat_id = call.message.chat.id
    
    edit_cache[chat_id]["temp"]["ct"] = is_ct
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Добавить", callback_data=f"save_note_yes_{num}"), types.InlineKeyboardButton("Нет", callback_data=f"save_note_no_{num}"))
    bot.edit_message_text("5️⃣ Заметка?", chat_id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("save_note_"))
def save_note_callback(call):
    data = call.data.split('_')
    choice = data[2]
    num = int(data[3])
    chat_id = call.message.chat.id
    
    if choice == "yes":
        bot.delete_message(chat_id, call.message.message_id)
        msg = bot.send_message(chat_id, "✍️ Введите заметку:")
        bot.register_next_step_handler(msg, finalize_lesson, num)
    else:
        edit_cache[chat_id]["temp"]["note"] = ""
        finalize_lesson(None, num, chat_id) # None т.к. нет сообщения

def finalize_lesson(message, num, chat_id_override=None):
    chat_id = message.chat.id if message else chat_id_override
    if message: edit_cache[chat_id]["temp"]["note"] = message.text
    
    # Сохраняем пару
    edit_cache[chat_id]["lessons"].append(edit_cache[chat_id]["temp"])
    
    total = edit_cache[chat_id]["total"]
    if num < total:
        ask_lesson_time(chat_id, num + 1)
    else:
        # Всё, сохраняем в базу
        day = edit_cache[chat_id]["day"]
        content_db["schedule"][day] = edit_cache[chat_id]["lessons"]
        save_json(FILES["content"], content_db)
        
        bot.send_message(chat_id, "✅ Расписание обновлено!")
        time.sleep(1)
        send_main_menu(chat_id)

# ==========================================
# 📐 ФОРМАТИРОВАНИЕ РАСПИСАНИЯ
# ==========================================
def format_schedule():
    text = "<b>🎓 РАСПИСАНИЕ:</b>\n"
    ru_days = {"Monday": "Понедельник", "Tuesday": "Вторник", "Wednesday": "Среда", "Thursday": "Четверг", "Friday": "Пятница", "Saturday": "Суббота", "Sunday": "Воскресенье"}
    
    sched = content_db.get("schedule", {})
    is_empty = True
    for day in sched:
        if sched[day]: is_empty = False
    
    if is_empty: return "<b>🎓 РАСПИСАНИЕ:</b>\n\nПока пусто. Отдыхаем! 😴"

    for day, lessons in sched.items():
        if not lessons: continue
        text += f"\n🗓 <b>{ru_days.get(day, day)}</b>\n"
        cnt = 1
        for l in lessons:
            ct = " 🔴 <b>КТ!</b>" if l.get('ct') else ""
            note = f"\n📝 <i>{l['note']}</i>" if l.get('note') else ""
            link = f"\n🔗 <a href='{l['link']}'>Ссылка</a>" if l.get('link') else ""
            text += f"\n{cnt}️⃣ <b>Пара {cnt}</b>\n🕒 <code>{l['time']}</code> — {l['name']}{ct}{link}{note}\n"
            cnt += 1
        text += "\n━━━━━━━━━━━━━━\n"
    return text

# ==========================================
# ⏰ ФОНОВЫЕ УВЕДОМЛЕНИЯ
# ==========================================
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
                                link = f"\n🔗 <a href='{l['link']}'>Ссылка</a>" if l.get('link') else ""
                                msg = f"⏰ <b>Пара через {s['time']} мин!</b>\n{l['name']}{link}{note}"
                                try: bot.send_message(uid, msg, parse_mode='HTML')
                                except: pass
            time.sleep(60)
        except: time.sleep(60)

if __name__ == "__main__":
    t = threading.Thread(target=notification_loop, daemon=True)
    t.start()
    print("Бот запущен! (Режим одного окна)")
    bot.infinity_polling()
