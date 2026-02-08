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
    "content": "content.json",
    "absences": "absences.json"
}

# Временное хранилище (wizard)
edit_cache = {}

DEFAULT_CONTENT = {
    "hw": "<b>ДЗ:</b> Пока пусто.",
    "ct": "<b>КТ:</b> Информации нет.",
    "schedule": {
        "Monday": [], "Tuesday": [], "Wednesday": [],
        "Thursday": [], "Friday": [], "Saturday": [], "Sunday": []
    }
}

SUBJECTS = [
    "Основы графического дизайна",
    "Живопись с основами цветоведения",
    "Основы дизайн-проектирования",
    "Информационное обеспечение проф. деятельности",
    "Выполнение проектной работы в граф. дизайне",
    "Физическая культура",
    "Основы философии",
    "Математика",
    "Основы motion-дизайна",
    "Иностранный язык в проф. деятельности",
    "Кураторский час"
]

DAYS_RU = {
    "Monday": "Понедельник", "Tuesday": "Вторник", "Wednesday": "Среда",
    "Thursday": "Четверг", "Friday": "Пятница", "Saturday": "Суббота", "Sunday": "Воскресенье"
}

DAY_SORT_ORDER = {
    "Понедельник": 0, "Вторник": 1, "Среда": 2, "Четверг": 3,
    "Пятница": 4, "Суббота": 5, "Воскресенье": 6
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
        except Exception as e:
            print(f"Ошибка чтения {filename}: {e}")
            return default if default is not None else {}
    return default if default is not None else {}

def save_json(filename, data):
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"Ошибка записи {filename}: {e}")

users_db = load_json(FILES["users"], {})
content_db = load_json(FILES["content"], DEFAULT_CONTENT)
absences_db = load_json(FILES["absences"], [])

# ==========================================
# 🧹 ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ==========================================

def safe_delete(chat_id, message_ids):
    if not isinstance(message_ids, list):
        message_ids = [message_ids]
    for msg_id in message_ids:
        try:
            bot.delete_message(chat_id, msg_id)
        except Exception:
            pass 

def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False, is_persistent=True)
    markup.add(types.KeyboardButton("📂 Открыть меню"))
    return markup

def ensure_user_data(user_id):
    if user_id not in users_db:
        users_db[user_id] = {"notify": True, "time": 10, "broadcasts": [], "name": None}
        return True
    else:
        changed = False
        if "broadcasts" not in users_db[user_id]:
            users_db[user_id]["broadcasts"] = []
            changed = True
        if "name" not in users_db[user_id]:
            users_db[user_id]["name"] = None
            changed = True
        return changed

# ==========================================
# 🟢 ГЛАВНЫЙ ВХОД (/start)
# ==========================================

@bot.message_handler(commands=['start'])
def start_command(message):
    user_id = message.chat.id
    safe_delete(user_id, message.message_id) 

    if ensure_user_data(user_id):
        save_json(FILES["users"], users_db)

    if user_id != ADMIN_ID and not users_db[user_id].get("name"):
        msg = bot.send_message(
            user_id, 
            "👋 <b>Добро пожаловать!</b>\n\nДавайте познакомимся. Напишите вашу <b>Фамилию и Имя</b>.\n"
            "<i>Пример: Кузнецов Витя</i>", 
            parse_mode='HTML',
            reply_markup=types.ReplyKeyboardRemove()
        )
        if user_id not in edit_cache: edit_cache[user_id] = {}
        edit_cache[user_id]["reg_msg_id"] = msg.message_id
        bot.register_next_step_handler(msg, process_registration)
        return

    show_welcome_screen(user_id, message.from_user.first_name)

def process_registration(message):
    user_id = message.chat.id
    name = message.text.strip()
    
    safe_delete(user_id, message.message_id)
    if user_id in edit_cache and "reg_msg_id" in edit_cache[user_id]:
        safe_delete(user_id, edit_cache[user_id]["reg_msg_id"])
        del edit_cache[user_id]["reg_msg_id"]

    users_db[user_id]["name"] = name
    save_json(FILES["users"], users_db)
    show_welcome_screen(user_id, message.from_user.first_name)

def show_welcome_screen(user_id, tg_name):
    if "last_welcome_id" in users_db[user_id]:
        safe_delete(user_id, users_db[user_id]["last_welcome_id"])

    msg = bot.send_message(
        user_id,
        f"👋 <b>Привет, {tg_name}!</b>\n\n"
        "Я бот-помощник. Тут ты можешь узнать расписание, домашку и настроить уведомления.\n\n"
        "👇 <b>Нажми кнопку внизу, чтобы начать.</b>",
        reply_markup=get_main_keyboard(),
        parse_mode='HTML'
    )
    
    users_db[user_id]["last_welcome_id"] = msg.message_id
    save_json(FILES["users"], users_db)

# ==========================================
# 📱 МЕНЮ
# ==========================================

@bot.message_handler(func=lambda m: m.text == "📂 Открыть меню")
def open_menu_handler(message):
    chat_id = message.chat.id
    safe_delete(chat_id, message.message_id)

    if chat_id in users_db:
        if "last_welcome_id" in users_db[chat_id]:
            safe_delete(chat_id, users_db[chat_id]["last_welcome_id"])
            del users_db[chat_id]["last_welcome_id"]
        if "last_menu_id" in users_db[chat_id]:
            safe_delete(chat_id, users_db[chat_id]["last_menu_id"])
            
    send_main_menu(message.chat.id)

def send_main_menu(chat_id, message_id=None):
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    btn1 = types.InlineKeyboardButton("📅 Расписание", callback_data="menu_schedule")
    btn2 = types.InlineKeyboardButton("🏠 Домашние работы", callback_data="menu_hw")
    btn3 = types.InlineKeyboardButton("🚩 Контрольные точки", callback_data="menu_ct")
    btn4 = types.InlineKeyboardButton("⚙️ Настройки", callback_data="menu_settings_main")
    
    markup.add(btn1, btn2)
    markup.add(btn3, btn4)

    if chat_id == ADMIN_ID:
        markup.add(types.InlineKeyboardButton("➖➖➖➖ АДМИНКА ➖➖➖➖", callback_data="ignore"))
        markup.add(types.InlineKeyboardButton("📋 Отсутствующие", callback_data="admin_abs_view"))
        markup.add(types.InlineKeyboardButton("✏️ Ред. ДЗ", callback_data="admin_edit_hw"),
                   types.InlineKeyboardButton("✏️ Ред. КТ", callback_data="admin_edit_ct"))
        markup.add(types.InlineKeyboardButton("✏️ Ред. Расписание", callback_data="admin_edit_sched"))
        markup.add(types.InlineKeyboardButton("📢 Сделать рассылку", callback_data="admin_broadcast"))
    else:
        user_name = users_db.get(chat_id, {}).get("name", "Студент")
        markup.add(types.InlineKeyboardButton(f"👤 {user_name}", callback_data="ignore"))
        markup.add(types.InlineKeyboardButton("🚫 Уведомить об отсутствии", callback_data="abs_menu"))

    text = "📂 <b>ГЛАВНОЕ МЕНЮ</b>\nВыберите нужный раздел:"
    
    if message_id:
        try: bot.edit_message_text(text, chat_id, message_id, reply_markup=markup, parse_mode='HTML')
        except: pass
    else:
        msg = bot.send_message(chat_id, text, reply_markup=markup, parse_mode='HTML')
        if chat_id in users_db:
            users_db[chat_id]["last_menu_id"] = msg.message_id
            save_json(FILES["users"], users_db)

# ==========================================
# 🕹️ CALLBACK HANDLER
# ==========================================

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    chat_id = call.message.chat.id
    data = call.data

    if data == "ignore":
        bot.answer_callback_query(call.id)
        return

    if data == "back_to_main":
        send_main_menu(chat_id, call.message.message_id)

    elif data == "menu_schedule":
        text = format_schedule()
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main"))
        bot.edit_message_text(text, chat_id, call.message.message_id, reply_markup=markup, parse_mode='HTML', disable_web_page_preview=True)

    elif data == "menu_hw":
        text = content_db["hw"]
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main"))
        bot.edit_message_text(text, chat_id, call.message.message_id, reply_markup=markup, parse_mode='HTML', disable_web_page_preview=True)

    elif data == "menu_ct":
        text = content_db["ct"]
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main"))
        bot.edit_message_text(text, chat_id, call.message.message_id, reply_markup=markup, parse_mode='HTML')

    # --- НАСТРОЙКИ ---
    elif data == "menu_settings_main" or data.startswith("opt_"):
        if ensure_user_data(chat_id): save_json(FILES["users"], users_db)
        
        if data == "opt_toggle": users_db[chat_id]['notify'] = not users_db[chat_id]['notify']
        elif data == "opt_time": 
            t = users_db[chat_id]['time']
            users_db[chat_id]['time'] = 10 if t == 5 else (60 if t == 10 else 5)
        
        if data.startswith("opt_"): save_json(FILES["users"], users_db)

        s = users_db[chat_id]
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(f"🔔 Уведомления: {'✅' if s['notify'] else '❌'}", callback_data="opt_toggle"),
                   types.InlineKeyboardButton(f"⏳ Время: {s['time']} мин", callback_data="opt_time"))
        markup.add(types.InlineKeyboardButton("🗑 Очистить чат", callback_data="settings_clear_ask"))
        markup.add(types.InlineKeyboardButton("🔄 Перезагрузить кнопку меню", callback_data="settings_restart_btn"))
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main"))

        try: bot.edit_message_text("⚙️ <b>Настройки бота:</b>", chat_id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
        except: pass

    elif data == "settings_restart_btn":
        safe_delete(chat_id, call.message.message_id)
        msg = bot.send_message(chat_id, "🔄 Кнопка обновлена!", reply_markup=get_main_keyboard())
        send_main_menu(chat_id)
        threading.Timer(2, safe_delete, args=[chat_id, msg.message_id]).start()

    # --- ОЧИСТКА ---
    elif data == "settings_clear_ask":
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔥 Удалить всё", callback_data="settings_clear_confirm"))
        markup.add(types.InlineKeyboardButton("Отмена", callback_data="menu_settings_main"))
        bot.edit_message_text("⚠️ <b>Удалить историю?</b>\nЭто удалит все объявления от админа, уведомления и старые сообщения.", chat_id, call.message.message_id, reply_markup=markup, parse_mode='HTML')

    elif data == "settings_clear_confirm":
        # 1. Удаляем ВСЕ сообщения из списка broadcasts
        if "broadcasts" in users_db[chat_id]:
            safe_delete(chat_id, users_db[chat_id]["broadcasts"])
            users_db[chat_id]["broadcasts"] = []
            save_json(FILES["users"], users_db)
        
        # 2. Удаляем САМ ИНТЕРФЕЙС настроек
        safe_delete(chat_id, call.message.message_id)
        
        # 3. Уведомление
        bot.answer_callback_query(call.id, "✅ Чат очищен!", show_alert=False)
        msg = bot.send_message(chat_id, "✅ <b>Чат очищен.</b>", parse_mode='HTML')
        
        # 4. Новое меню
        send_main_menu(chat_id)
        threading.Timer(2, safe_delete, args=[chat_id, msg.message_id]).start()

    # ==========================
    # 🤒 ОТСУТСТВИЕ
    # ==========================
    
    elif data == "abs_menu":
        markup = types.InlineKeyboardMarkup(row_width=2)
        days = [("Понедельник", "Monday"), ("Вторник", "Tuesday"), ("Среда", "Wednesday"),
                ("Четверг", "Thursday"), ("Пятница", "Friday"), ("Суббота", "Saturday")]
        btns = [types.InlineKeyboardButton(txt, callback_data=f"abs_day_{code}") for txt, code in days]
        markup.add(*btns)
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main"))
        bot.edit_message_text("📅 <b>Выберите день отсутствия:</b>", chat_id, call.message.message_id, reply_markup=markup, parse_mode='HTML')

    elif data.startswith("abs_day_"):
        day_code = data.split("_")[2]
        if chat_id not in edit_cache: edit_cache[chat_id] = {}
        edit_cache[chat_id]["abs"] = {"day": day_code, "day_ru": DAYS_RU[day_code], "type": None, "pairs": []}
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🏠 Не буду весь день", callback_data="abs_type_full"))
        markup.add(types.InlineKeyboardButton("🕒 Не буду на парах", callback_data="abs_type_pairs"))
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="abs_menu"))
        bot.edit_message_text(f"🗓 <b>{DAYS_RU[day_code]}:</b>\nКак будете отсутствовать?", chat_id, call.message.message_id, reply_markup=markup, parse_mode='HTML')

    elif data == "abs_type_full":
        edit_cache[chat_id]["abs"]["type"] = "whole"
        ask_login_question(chat_id, call.message.message_id)

    elif data == "abs_type_pairs" or data.startswith("abs_p_select_"):
        if "abs" not in edit_cache.get(chat_id, {}): 
            bot.answer_callback_query(call.id, "⚠️ Ошибка сессии", show_alert=True)
            return send_main_menu(chat_id, call.message.message_id)
        
        if data.startswith("abs_p_select_"):
            p_num = int(data.split("_")[3])
            current_pairs = edit_cache[chat_id]["abs"]["pairs"]
            if p_num in current_pairs:
                current_pairs.remove(p_num)
            else:
                current_pairs.append(p_num)
                current_pairs.sort()
        
        edit_cache[chat_id]["abs"]["type"] = "part"
        
        markup = types.InlineKeyboardMarkup(row_width=3)
        btns = []
        selected = edit_cache[chat_id]["abs"]["pairs"]
        for i in range(1, 6):
            txt = f"{i} пара ✅" if i in selected else f"{i} пара"
            btns.append(types.InlineKeyboardButton(txt, callback_data=f"abs_p_select_{i}"))
        markup.add(*btns)
        
        if selected:
            markup.add(types.InlineKeyboardButton("✅ Подтвердить", callback_data="abs_p_confirm"))
        
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data=f"abs_day_{edit_cache[chat_id]['abs']['day']}"))
        
        bot.edit_message_text(f"🗓 <b>{edit_cache[chat_id]['abs']['day_ru']}</b>\nВыберите пары, которые пропустите:", 
                              chat_id, call.message.message_id, reply_markup=markup, parse_mode='HTML')

    elif data == "abs_p_confirm":
        ask_login_question(chat_id, call.message.message_id)

    # --- ФИНАЛИЗАЦИЯ ОТСУТСТВИЯ ---
    elif data.startswith("abs_login_"):
        try:
            choice = data.split("_")[2] 
            
            if "abs" not in edit_cache.get(chat_id, {}): 
                bot.answer_callback_query(call.id, "⚠️ Время сессии истекло.", show_alert=True)
                return send_main_menu(chat_id, call.message.message_id)
            
            abs_data = edit_cache[chat_id]["abs"]
            user_data = users_db.get(chat_id, {})
            user_name = user_data.get("name", "Неизвестный")
            
            if abs_data["type"] == "whole":
                info_str = "Целый день"
            else:
                info_str = ", ".join([f"{p} пара" for p in abs_data["pairs"]])
                
            login_str = "заходить" if choice == "yes" else "не заходить"
            
            record = {
                "day": abs_data["day_ru"],
                "name": user_name,
                "info": info_str,
                "login": login_str,
                "timestamp": time.time()
            }
            
            if not isinstance(absences_db, list): absences_db.clear()
            absences_db.append(record)
            save_json(FILES["absences"], absences_db)
            
            # Уведомляем админа И сохраняем ID
            try:
                msg = bot.send_message(ADMIN_ID, f"🆕 <b>Уведомление об отсутствии!</b>\n"
                                           f"👤 {user_name}\n"
                                           f"🗓 {abs_data['day_ru']}\n"
                                           f"🕒 {info_str}\n"
                                           f"🔑 {login_str}", parse_mode='HTML')
                
                if ensure_user_data(ADMIN_ID): save_json(FILES["users"], users_db)
                users_db[ADMIN_ID]["broadcasts"].append(msg.message_id)
                save_json(FILES["users"], users_db)
                    
            except Exception as e:
                print(f"Ошибка уведомления админа: {e}")

            bot.answer_callback_query(call.id, "✅ Отправлено старосте!", show_alert=True)
            
            if "abs" in edit_cache.get(chat_id, {}):
                del edit_cache[chat_id]["abs"]
                
            send_main_menu(chat_id, call.message.message_id)
            
        except Exception as e:
            print(f"CRITICAL ERROR in abs_login: {e}")
            bot.answer_callback_query(call.id, "❌ Произошла ошибка", show_alert=True)
            send_main_menu(chat_id, call.message.message_id)

    # ==========================
    # 👮‍♂️ АДМИНКА
    # ==========================
    
    elif data == "admin_abs_view":
        if chat_id != ADMIN_ID: return
        
        if not absences_db:
            text = "📋 <b>Список отсутствующих пуст.</b>"
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main"))
        else:
            text = "📋 <b>СПИСОК ОТСУТСТВУЮЩИХ:</b>\n\n"
            # Сортировка по дню
            sorted_absences = sorted(absences_db, key=lambda x: (DAY_SORT_ORDER.get(x['day'], 7), x.get('timestamp', 0)))
            
            for rec in sorted_absences:
                icon = "🟢" if rec['login'] == "заходить" else "🔴"
                text += f"🗓 <b>{rec['day']}</b> — {rec['name']}\n"
                text += f"   └ 🕒 {rec['info']} ({icon} {rec['login']})\n\n"
            
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🗑 Очистить список", callback_data="admin_abs_clear"))
            markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main"))
            
        bot.edit_message_text(text, chat_id, call.message.message_id, reply_markup=markup, parse_mode='HTML')

    elif data == "admin_abs_clear":
        if chat_id != ADMIN_ID: return
        absences_db.clear()
        save_json(FILES["absences"], absences_db)
        bot.answer_callback_query(call.id, "Список очищен")
        
        callback_handler(call)
        call.data = "admin_abs_view"
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main"))
        bot.edit_message_text("📋 <b>Список отсутствующих пуст.</b>", chat_id, call.message.message_id, reply_markup=markup, parse_mode='HTML')

    # --- РЕДАКТИРОВАНИЕ ---
    elif data in ["admin_edit_hw", "admin_edit_ct"]:
        if chat_id != ADMIN_ID: return
        target = "ДЗ" if data == "admin_edit_hw" else "КТ"
        safe_delete(chat_id, call.message.message_id)
        
        msg = bot.send_message(chat_id, f"✍️ Введите новый текст для <b>{target}</b>:\n(или напишите <code>Отмена</code>)", parse_mode='HTML')
        if chat_id not in edit_cache: edit_cache[chat_id] = {}
        edit_cache[chat_id]["admin_prompt_id"] = msg.message_id
        
        bot.register_next_step_handler(msg, process_admin_text, data)

    elif data == "admin_broadcast":
        if chat_id != ADMIN_ID: return
        safe_delete(chat_id, call.message.message_id)
        msg = bot.send_message(chat_id, "📝 <b>Отправь сообщение для рассылки</b>\nОно останется у пользователей в чате.\nНапиши <code>Отмена</code> для выхода.", parse_mode='HTML')
        if chat_id not in edit_cache: edit_cache[chat_id] = {}
        edit_cache[chat_id]["admin_prompt_id"] = msg.message_id
        bot.register_next_step_handler(msg, process_broadcast)

    elif data == "admin_edit_sched":
        if chat_id != ADMIN_ID: return
        show_schedule_editor(chat_id, call.message.message_id)

    elif data.startswith("edit_"):
        handle_schedule_editor(call)

    # --- WIZARD РАСПИСАНИЯ ---
    elif data.startswith("t_start_h_"):
        if chat_id not in edit_cache: return bot.answer_callback_query(call.id, "Ошибка сессии", show_alert=True)
        edit_cache[chat_id]["temp"]["start_h"] = data.split('_')[3]
        ask_time_start_minute(chat_id, int(data.split('_')[4]), call.message.message_id)

    elif data.startswith("t_start_m_"):
        if chat_id not in edit_cache: return
        edit_cache[chat_id]["temp"]["start_m"] = data.split('_')[3]
        ask_time_end_hour(chat_id, int(data.split('_')[4]), call.message.message_id)

    elif data.startswith("t_end_h_"):
        if chat_id not in edit_cache: return
        edit_cache[chat_id]["temp"]["end_h"] = data.split('_')[3]
        ask_time_end_minute(chat_id, int(data.split('_')[4]), call.message.message_id)

    elif data.startswith("t_end_m_"):
        if chat_id not in edit_cache: return
        minute = data.split('_')[3]
        num = int(data.split('_')[4])
        sh, sm = edit_cache[chat_id]["temp"]["start_h"], edit_cache[chat_id]["temp"]["start_m"]
        eh = edit_cache[chat_id]["temp"]["end_h"]
        edit_cache[chat_id]["temp"]["time_str"] = f"{sh}:{sm} - {eh}:{minute}"
        edit_cache[chat_id]["temp"]["start_clean"] = f"{sh}:{sm}"
        ask_lesson_subject(chat_id, num, call.message.message_id)

    elif data.startswith("subj_"):
        if chat_id not in edit_cache: return
        idx = int(data.split('_')[1])
        edit_cache[chat_id]["temp"]["name"] = SUBJECTS[idx]
        ask_lesson_link_decision(chat_id, int(data.split('_')[2]), call.message.message_id)

    elif data.startswith("ask_link_"):
        if chat_id not in edit_cache: return
        choice = data.split('_')[2]
        num = int(data.split('_')[3])
        if choice == "yes":
            safe_delete(chat_id, call.message.message_id)
            msg = bot.send_message(chat_id, "🔗 Отправь ссылку:")
            edit_cache[chat_id]["msgs_to_del"].append(msg.message_id)
            bot.register_next_step_handler(msg, process_link_text, num)
        else:
            edit_cache[chat_id]["temp"]["link"] = ""
            ask_lesson_ct(chat_id, num, call.message.message_id)

    elif data.startswith("save_ct_"):
        if chat_id not in edit_cache: return
        edit_cache[chat_id]["temp"]["ct"] = (data.split('_')[2] == "yes")
        ask_lesson_note(chat_id, int(data.split('_')[3]), call.message.message_id)

    elif data.startswith("save_note_"):
        if chat_id not in edit_cache: return
        choice = data.split('_')[2]
        num = int(data.split('_')[3])
        if choice == "yes":
            safe_delete(chat_id, call.message.message_id)
            msg = bot.send_message(chat_id, "✍️ Введите текст заметки:")
            edit_cache[chat_id]["msgs_to_del"].append(msg.message_id)
            bot.register_next_step_handler(msg, finalize_lesson, num)
        else:
            edit_cache[chat_id]["temp"]["note"] = ""
            finalize_lesson(None, num, chat_id)

def ask_login_question(chat_id, message_id):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Да", callback_data="abs_login_yes"),
               types.InlineKeyboardButton("Нет", callback_data="abs_login_no"))
    bot.edit_message_text("🤔 <b>Зайти под вашим именем на пару?</b>", chat_id, message_id, reply_markup=markup, parse_mode='HTML')

# ==========================================
# 🛠 ТЕКСТОВЫЕ ОБРАБОТЧИКИ
# ==========================================

def process_admin_text(message, action):
    chat_id = message.chat.id
    safe_delete(chat_id, message.message_id)
    if chat_id in edit_cache and "admin_prompt_id" in edit_cache[chat_id]:
        safe_delete(chat_id, edit_cache[chat_id]["admin_prompt_id"])
        del edit_cache[chat_id]["admin_prompt_id"]

    if message.text and message.text.lower() == "отмена":
        send_main_menu(chat_id)
        return

    if action == "admin_edit_hw": content_db["hw"] = message.text
    elif action == "admin_edit_ct": content_db["ct"] = message.text
    
    save_json(FILES["content"], content_db)
    send_main_menu(chat_id)
    msg = bot.send_message(chat_id, "✅ Обновлено!")
    threading.Timer(2, safe_delete, args=[chat_id, msg.message_id]).start()

def process_broadcast(message):
    chat_id = message.chat.id
    
    if message.text and message.text.lower() == "отмена":
        safe_delete(chat_id, message.message_id)
        if chat_id in edit_cache and "admin_prompt_id" in edit_cache[chat_id]:
            safe_delete(chat_id, edit_cache[chat_id]["admin_prompt_id"])
            del edit_cache[chat_id]["admin_prompt_id"]
        send_main_menu(chat_id)
        return

    if chat_id in edit_cache and "admin_prompt_id" in edit_cache[chat_id]:
        safe_delete(chat_id, edit_cache[chat_id]["admin_prompt_id"])
        del edit_cache[chat_id]["admin_prompt_id"]

    status_msg = bot.send_message(ADMIN_ID, "📢 Начинаю рассылку...")
    count = 0
    
    for uid in users_db:
        try:
            msg = bot.copy_message(uid, message.chat.id, message.message_id)
            count += 1
            if "broadcasts" not in users_db[uid]: users_db[uid]["broadcasts"] = []
            users_db[uid]["broadcasts"].append(msg.message_id)
        except Exception as e:
            print(f"Ошибка отправки пользователю {uid}: {e}")
    
    save_json(FILES["users"], users_db)
    safe_delete(chat_id, message.message_id)
    
    finish_msg = bot.send_message(ADMIN_ID, f"✅ Рассылка завершена. Доставлено: {count}")
    
    threading.Timer(3, safe_delete, args=[ADMIN_ID, [status_msg.message_id, finish_msg.message_id]]).start()
    send_main_menu(ADMIN_ID)

# ==========================================
# 🗓 РЕДАКТОР (ЛОГИКА)
# ==========================================

def show_schedule_editor(chat_id, message_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    days = [("Понедельник", "Monday"), ("Вторник", "Tuesday"), ("Среда", "Wednesday"),
            ("Четверг", "Thursday"), ("Пятница", "Friday"), ("Суббота", "Saturday"), ("Воскресенье", "Sunday")]
    btns = [types.InlineKeyboardButton(text, callback_data=f"edit_day_{code}") for text, code in days]
    markup.add(*btns)
    markup.add(types.InlineKeyboardButton("🗑 Очистить неделю", callback_data="edit_clear_check"))
    markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main"))
    bot.edit_message_text("🗓 <b>Редактор расписания:</b>", chat_id, message_id, reply_markup=markup, parse_mode='HTML')

def handle_schedule_editor(call):
    chat_id = call.message.chat.id
    data = call.data
    action = data.split('_')[1]

    if action == "clear": 
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔥 Удалить", callback_data="edit_confirm_del"), types.InlineKeyboardButton("❌ Отмена", callback_data="admin_edit_sched"))
        bot.edit_message_text("⚠️ Очистить неделю?", chat_id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
    
    elif action == "confirm":
        for day in content_db["schedule"]: content_db["schedule"][day] = []
        save_json(FILES["content"], content_db)
        show_schedule_editor(chat_id, call.message.message_id)

    elif action == "day":
        day_code = data.split('_')[2]
        if chat_id not in edit_cache: edit_cache[chat_id] = {}
        edit_cache[chat_id].update({"day": day_code, "lessons": [], "msgs_to_del": []})
        
        markup = types.InlineKeyboardMarkup(row_width=3)
        markup.add(*[types.InlineKeyboardButton(str(i), callback_data=f"edit_count_{i}") for i in range(6)])
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="admin_edit_sched"))
        ru_days = {"Monday": "Понедельник", "Tuesday": "Вторник", "Wednesday": "Среда", "Thursday": "Четверг", "Friday": "Пятница", "Saturday": "Суббота", "Sunday": "Воскресенье"}
        bot.edit_message_text(f"День: <b>{ru_days[day_code]}</b>\nСколько пар?", chat_id, call.message.message_id, reply_markup=markup, parse_mode='HTML')

    elif action == "count":
        count = int(data.split('_')[2])
        edit_cache[chat_id]["total"] = count
        if count == 0:
            day = edit_cache[chat_id]["day"]
            content_db["schedule"][day] = []
            save_json(FILES["content"], content_db)
            show_schedule_editor(chat_id, call.message.message_id)
        else:
            safe_delete(chat_id, call.message.message_id)
            edit_cache[chat_id]["temp"] = {}
            ask_time_start_hour(chat_id, 1)

def ask_time_start_hour(chat_id, num, prev_msg_id=None):
    if prev_msg_id: safe_delete(chat_id, prev_msg_id)
    markup = types.InlineKeyboardMarkup(row_width=4)
    btns = [types.InlineKeyboardButton(f"{h:02d}", callback_data=f"t_start_h_{h:02d}_{num}") for h in range(8, 21)]
    markup.add(*btns)
    msg = bot.send_message(chat_id, f"1️⃣ <b>Пара №{num}</b>\nНачало: выберите ЧАС", reply_markup=markup, parse_mode='HTML')
    edit_cache[chat_id]["msgs_to_del"].append(msg.message_id)

def ask_time_start_minute(chat_id, num, prev_msg_id=None):
    if prev_msg_id: safe_delete(chat_id, prev_msg_id)
    markup = types.InlineKeyboardMarkup(row_width=4)
    btns = [types.InlineKeyboardButton(f"{m:02d}", callback_data=f"t_start_m_{m:02d}_{num}") for m in range(0, 60, 5)]
    markup.add(*btns)
    h = edit_cache[chat_id]["temp"]["start_h"]
    msg = bot.send_message(chat_id, f"1️⃣ <b>Пара №{num}</b>\nНачало: {h}:?? (выберите минуты)", reply_markup=markup, parse_mode='HTML')
    edit_cache[chat_id]["msgs_to_del"].append(msg.message_id)

def ask_time_end_hour(chat_id, num, prev_msg_id=None):
    if prev_msg_id: safe_delete(chat_id, prev_msg_id)
    markup = types.InlineKeyboardMarkup(row_width=4)
    btns = [types.InlineKeyboardButton(f"{h:02d}", callback_data=f"t_end_h_{h:02d}_{num}") for h in range(8, 21)]
    markup.add(*btns)
    ts = edit_cache[chat_id]["temp"]["start_h"] + ":" + edit_cache[chat_id]["temp"]["start_m"]
    msg = bot.send_message(chat_id, f"2️⃣ <b>Пара №{num}</b>\n({ts} - ??)\nКонец: выберите ЧАС", reply_markup=markup, parse_mode='HTML')
    edit_cache[chat_id]["msgs_to_del"].append(msg.message_id)

def ask_time_end_minute(chat_id, num, prev_msg_id=None):
    if prev_msg_id: safe_delete(chat_id, prev_msg_id)
    markup = types.InlineKeyboardMarkup(row_width=4)
    btns = [types.InlineKeyboardButton(f"{m:02d}", callback_data=f"t_end_m_{m:02d}_{num}") for m in range(0, 60, 5)]
    markup.add(*btns)
    ts = edit_cache[chat_id]["temp"]["start_h"] + ":" + edit_cache[chat_id]["temp"]["start_m"]
    he = edit_cache[chat_id]["temp"]["end_h"]
    msg = bot.send_message(chat_id, f"2️⃣ <b>Пара №{num}</b>\n({ts} - {he}:??)\nКонец: выберите МИНУТЫ", reply_markup=markup, parse_mode='HTML')
    edit_cache[chat_id]["msgs_to_del"].append(msg.message_id)

def ask_lesson_subject(chat_id, num, prev_msg_id=None):
    if prev_msg_id: safe_delete(chat_id, prev_msg_id)
    markup = types.InlineKeyboardMarkup(row_width=1)
    btns = []
    for i, subj in enumerate(SUBJECTS):
        btns.append(types.InlineKeyboardButton(subj, callback_data=f"subj_{i}_{num}"))
    markup.add(*btns)
    msg = bot.send_message(chat_id, f"3️⃣ <b>Пара №{num}</b>\nВыберите предмет:", reply_markup=markup, parse_mode='HTML')
    edit_cache[chat_id]["msgs_to_del"].append(msg.message_id)

def ask_lesson_link_decision(chat_id, num, prev_msg_id=None):
    if prev_msg_id: safe_delete(chat_id, prev_msg_id)
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔗 Добавить ссылку", callback_data=f"ask_link_yes_{num}"),
               types.InlineKeyboardButton("❌ Нет ссылки", callback_data=f"ask_link_no_{num}"))
    msg = bot.send_message(chat_id, "4️⃣ Есть ссылка на пару?", reply_markup=markup)
    edit_cache[chat_id]["msgs_to_del"].append(msg.message_id)

def process_link_text(message, num):
    chat_id = message.chat.id
    if chat_id in edit_cache: edit_cache[chat_id]["msgs_to_del"].append(message.message_id)
    if "temp" not in edit_cache[chat_id]: edit_cache[chat_id]["temp"] = {}
    edit_cache[chat_id]["temp"]["link"] = message.text
    ask_lesson_ct(chat_id, num)

def ask_lesson_ct(chat_id, num, prev_msg_id=None):
    if prev_msg_id: safe_delete(chat_id, prev_msg_id)
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Да", callback_data=f"save_ct_yes_{num}"), 
               types.InlineKeyboardButton("Нет", callback_data=f"save_ct_no_{num}"))
    msg = bot.send_message(chat_id, "5️⃣ Это Контрольная Точка (КТ)?", reply_markup=markup)
    edit_cache[chat_id]["msgs_to_del"].append(msg.message_id)

def ask_lesson_note(chat_id, num, prev_msg_id=None):
    if prev_msg_id: safe_delete(chat_id, prev_msg_id)
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Добавить", callback_data=f"save_note_yes_{num}"), 
               types.InlineKeyboardButton("Нет", callback_data=f"save_note_no_{num}"))
    msg = bot.send_message(chat_id, "6️⃣ Добавить заметку?", reply_markup=markup)
    edit_cache[chat_id]["msgs_to_del"].append(msg.message_id)

def finalize_lesson(message, num, chat_id_override=None):
    chat_id = message.chat.id if message else chat_id_override
    if message: 
        edit_cache[chat_id]["msgs_to_del"].append(message.message_id)
        if "temp" not in edit_cache[chat_id]: edit_cache[chat_id]["temp"] = {}
        edit_cache[chat_id]["temp"]["note"] = message.text
    
    lesson_data = {
        "time": edit_cache[chat_id]["temp"]["time_str"], 
        "start_clean": edit_cache[chat_id]["temp"]["start_clean"],
        "name": edit_cache[chat_id]["temp"]["name"],
        "link": edit_cache[chat_id]["temp"].get("link", ""),
        "ct": edit_cache[chat_id]["temp"].get("ct", False),
        "note": edit_cache[chat_id]["temp"].get("note", "")
    }
    edit_cache[chat_id]["lessons"].append(lesson_data)
    
    if num < edit_cache[chat_id]["total"]:
        edit_cache[chat_id]["temp"] = {}
        ask_time_start_hour(chat_id, num + 1)
    else:
        day = edit_cache[chat_id]["day"]
        content_db["schedule"][day] = edit_cache[chat_id]["lessons"]
        save_json(FILES["content"], content_db)
        
        if chat_id in edit_cache and "msgs_to_del" in edit_cache[chat_id]:
            safe_delete(chat_id, edit_cache[chat_id]["msgs_to_del"])
            edit_cache[chat_id]["msgs_to_del"] = []

        ru_days = {"Monday": "Понедельник", "Tuesday": "Вторник", "Wednesday": "Среда", "Thursday": "Четверг", "Friday": "Пятница", "Saturday": "Суббота", "Sunday": "Воскресенье"}
        msg = bot.send_message(chat_id, f"✅ <b>{ru_days[day]}</b> успешно сохранен!", parse_mode='HTML')
        
        send_main_menu(chat_id)
        threading.Timer(2.0, safe_delete, args=[chat_id, msg.message_id]).start()

# ==========================================
# 📐 ФОРМАТИРОВАНИЕ
# ==========================================
def format_schedule():
    ru_days = {"Monday": "Понедельник", "Tuesday": "Вторник", "Wednesday": "Среда", "Thursday": "Четверг", "Friday": "Пятница", "Saturday": "Суббота", "Sunday": "Воскресенье"}
    sched = content_db.get("schedule", {})
    if all(not sched[d] for d in sched): return "<b>🎓 РАСПИСАНИЕ:</b>\n\nПока пусто. Отдыхаем! 😴"

    text = "<b>🎓 РАСПИСАНИЕ ЗАНЯТИЙ</b>\n"
    
    for day, lessons in sched.items():
        if not lessons: continue
        text += f"\n━━━━━━━━━━━━\n🗓 <b>{ru_days.get(day, day)}</b>\n"
        for i, l in enumerate(lessons, 1):
            ct_icon = "🔴 <b>КТ</b> " if l.get('ct') else ""
            extras = ""
            if l.get('link'):
                extras += f"\n   └ 🔗 <a href='{l['link']}'>Ссылка на пару</a>"
            if l.get('note'):
                extras += f"\n   └ 📝 <i>{l['note']}</i>"
            text += f"{i}️⃣ <code>{l['time']}</code> — {ct_icon}<b>{l['name']}</b>{extras}\n"
    return text

# ==========================================
# 🛑 ЭХО
# ==========================================
@bot.message_handler(content_types=['text'])
def echo_all(message):
    safe_delete(message.chat.id, message.message_id)
    msg = bot.send_message(message.chat.id, "Нажмите кнопку 👇", reply_markup=get_main_keyboard())
    threading.Timer(3, safe_delete, args=[message.chat.id, msg.message_id]).start()

# ==========================================
# ⏰ ФОНОВЫЕ УВЕДОМЛЕНИЯ
# ==========================================
def notification_loop():
    print("Бот запущен и готов к работе.")
    while True:
        try:
            now = datetime.now()
            day = now.strftime("%A")
            sched = content_db.get("schedule", {})
            db_changed = False
            
            if day in sched:
                for l in sched[day]:
                    time_str = l.get('start_clean')
                    if not time_str: time_str = l['time'].split("-")[0].strip()
                    h, m = map(int, time_str.split(":"))
                    start = now.replace(hour=h, minute=m, second=0, microsecond=0)
                    for uid, s in users_db.items():
                        if s.get('notify'):
                            ntilde = start - timedelta(minutes=s['time'])
                            if now.hour == ntilde.hour and now.minute == ntilde.minute:
                                link = f"\n🔗 <a href='{l['link']}'>Ссылка</a>" if l.get('link') else ""
                                msg = f"⏰ <b>Пара через {s['time']} мин!</b>\n{l['name']}{link}"
                                try: 
                                    sent_msg = bot.send_message(uid, msg, parse_mode='HTML')
                                    # [FIX] Сохраняем ID уведомления
                                    if "broadcasts" not in users_db[uid]:
                                        users_db[uid]["broadcasts"] = []
                                    users_db[uid]["broadcasts"].append(sent_msg.message_id)
                                    db_changed = True
                                except: pass
            
            if db_changed:
                save_json(FILES["users"], users_db)
                
            time.sleep(60)
        except Exception as e:
            print(f"Ошибка в цикле: {e}")
            time.sleep(60)

if __name__ == "__main__":
    t = threading.Thread(target=notification_loop, daemon=True)
    t.start()
    bot.infinity_polling()
