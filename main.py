import telebot
from telebot import types
import threading
import time
import json
import os
from datetime import datetime, timedelta
from copy import deepcopy
import traceback
import uuid

# ==========================================
# КОНФИГУРАЦИЯ
# ==========================================
TOKEN = '8502946152:AAFjl9jbD-iqYbx3aCp3BcXBTWNT0O4DQIw'
# Чтобы добавить второго админа, добавьте ID через запятую: [1151803777, 123456789]
ADMIN_IDS = [1151803777, 1264124700, 8513347250, 8349611530]
bot = telebot.TeleBot(TOKEN)

FILES = {
    "users": "students_db.json", "content": "content.json",
    "absences": "absences.json", "deadlines": "deadlines.json",
    "polls": "polls.json", "feedback": "feedback.json",
    "subjects": "subjects.json", "suggestions": "suggestions.json"
}

data_lock = threading.RLock()
edit_cache = {}
sent_notifications = set()
EDIT_CACHE_TIMEOUT = 1200
LESSON_DURATION = 90

DEFAULT_CONTENT = {
    "hw": [], 
    "ct": [],
    "schedule": {d: [] for d in ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]},
    "subject_links": {}
}

DAYS_RU = {"Monday":"Понедельник","Tuesday":"Вторник","Wednesday":"Среда",
           "Thursday":"Четверг","Friday":"Пятница","Saturday":"Суббота","Sunday":"Воскресенье"}
DAY_SORT = {"Понедельник":0,"Вторник":1,"Среда":2,"Четверг":3,"Пятница":4,"Суббота":5,"Воскресенье":6}
DAYS_LIST = list(DAYS_RU.items())

# ==========================================
# РАБОТА С ФАЙЛАМИ
# ==========================================
def load_json(fn, default=None):
    if default is None: default = {}
    if not os.path.exists(fn): return deepcopy(default)
    try:
        with open(fn,'r',encoding='utf-8') as f:
            d = json.load(f)
            return {int(k):v for k,v in d.items()} if fn == FILES["users"] else d
    except: return deepcopy(default)

def save_json(fn, data):
    try:
        tmp = fn+".tmp"
        with open(tmp,'w',encoding='utf-8') as f: json.dump(data,f,ensure_ascii=False,indent=2)
        os.replace(tmp, fn)
    except: pass

def save_all(key, data):
    save_json(FILES[key], data)

users_db = load_json(FILES["users"], {})
content_db = load_json(FILES["content"], DEFAULT_CONTENT)
absences_db = load_json(FILES["absences"], [])
deadlines_db = load_json(FILES["deadlines"], [])
polls_db = load_json(FILES["polls"], [])
feedback_db = load_json(FILES["feedback"], [])
subjects_db = load_json(FILES["subjects"], [])
suggestions_db = load_json(FILES["suggestions"], [])

# Миграция
with data_lock:
    for uid in users_db:
        if "hw_done" not in users_db[uid]: users_db[uid]["hw_done"] = []
    if "hw" in content_db:
        for h in content_db["hw"]:
            if "id" not in h: h["id"] = str(uuid.uuid4())[:8]
            if "subject" not in h: h["subject"] = "Общее"
    for p in polls_db:
        if "messages" not in p: p["messages"] = {}
    save_all("users", users_db)
    save_all("content", content_db)
    save_all("polls", polls_db)

# ==========================================
# УТИЛИТЫ
# ==========================================
def moscow():
    """Точное московское время UTC+3"""
    return datetime.utcnow() + timedelta(hours=3)

def fmt_ts(ts):
    """Формат timestamp в МСК"""
    dt = datetime.utcfromtimestamp(ts) + timedelta(hours=3)
    return dt.strftime('%d.%m %H:%M')

def sdel(cid, mids):
    if not isinstance(mids, (list, tuple)): mids = [mids]
    if not mids: return
    def _del_thread(c, ms):
        for m in ms:
            if m:
                try: bot.delete_message(c, m)
                except: pass
    threading.Thread(target=_del_thread, args=(cid, mids), daemon=True).start()

def input_kb(skip=False, done=False):
    mk = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    row = []
    if skip: row.append(types.KeyboardButton("Пропустить (-)"))
    if done: row.append(types.KeyboardButton("Готово"))
    row.append(types.KeyboardButton("Отмена"))
    mk.add(*row)
    return mk

def remove_kb():
    return types.ReplyKeyboardRemove()

def ensure_user(uid):
    defs = {"notify":True,"time":10,"broadcasts":[],"name":None,"hw_done":[]}
    ch = uid not in users_db
    if ch: users_db[uid] = defs.copy()
    else:
        for k,v in defs.items():
            if k not in users_db[uid]: users_db[uid][k]=v; ch=True
    return ch

def clear_ec(uid):
    c = edit_cache.pop(uid, None)
    if c: sdel(uid, c.get("msgs_to_del",[]))
    if c and "view_msgs" in c: sdel(uid, c["view_msgs"])

def set_ec(uid, data):
    data["_ts"] = time.time()
    if "msgs_to_del" not in data: data["msgs_to_del"] = []
    edit_cache[uid] = data

def get_ec(uid):
    return edit_cache.get(uid, {})

def update_ec(uid, key, val):
    if uid in edit_cache: edit_cache[uid][key] = val

def is_admin(uid): return uid in ADMIN_IDS
def subj_name(s): return s.get("name","?") if isinstance(s,dict) else s
def subj_link(s): return s.get("link","") if isinstance(s,dict) else ""

def ddel(cid, mid, delay=2):
    def _(): time.sleep(delay); sdel(cid, mid)
    threading.Thread(target=_, daemon=True).start()

def auto_times(start, count, break_min=0):
    h,m = map(int, start.split(":"))
    cur = datetime(2000,1,1,h,m)
    r = []
    for _ in range(count):
        s=cur
        e=cur+timedelta(minutes=LESSON_DURATION)
        r.append((s.strftime("%H:%M"), e.strftime("%H:%M")))
        cur = e + timedelta(minutes=break_min) 
    return r

def active_input(uid):
    c = edit_cache.get(uid)
    if not c: return False
    return c.get("state","") in (
        "registration","broadcast","sched_edit","subj_add_name","subj_add_link",
        "hw_title","hw_text","hw_date","hw_files","hw_subj_sel","hw_assigned_date",
        "ct_title","ct_text","ct_date",
        "dl_title","dl_date","dl_desc",
        "poll_question","poll_options","feedback","suggestion"
    )

def save_hw_file(file_id, file_name, file_type):
    fid = str(uuid.uuid4())[:8]
    return {"id": fid, "file_id": file_id, "name": file_name or f"file_{fid}", "type": file_type}

# ==========================================
# START & REGISTRATION
# ==========================================
@bot.message_handler(commands=['start'])
def cmd_start(msg):
    uid = msg.chat.id
    sdel(uid, msg.message_id)
    clear_ec(uid)
    
    # Удаляем старую Reply-клавиатуру если была
    dummy = bot.send_message(uid, "⌛", reply_markup=types.ReplyKeyboardRemove())
    sdel(uid, dummy.message_id)

    with data_lock:
        if ensure_user(uid): save_all("users", users_db)
    
    if not is_admin(uid) and not users_db[uid].get("name"):
        m = bot.send_message(uid, "👋 <b>Добро пожаловать!</b>\n\nНапишите <b>Фамилию и Имя</b>.\n<i>Пример: Кузнецов Витя</i>",parse_mode='HTML')
        set_ec(uid,{"state":"registration","reg_msg_id":m.message_id,"msgs_to_del":[]})
        bot.register_next_step_handler(m, do_reg)
        return
    
    welcome(uid, users_db[uid].get("name", "Студент"))

def do_reg(msg):
    uid=msg.chat.id; name=(msg.text or"").strip()
    sdel(uid, msg.message_id)
    if not name:
        m=bot.send_message(uid,"⚠️ Имя не может быть пустым:")
        bot.register_next_step_handler(m, do_reg); return
    c=edit_cache.get(uid,{}); sdel(uid,c.get("reg_msg_id"))
    with data_lock: ensure_user(uid); users_db[uid]["name"]=name; save_all("users",users_db)
    clear_ec(uid); welcome(uid, name)

def welcome(uid, name):
    with data_lock:
        old_w = users_db.get(uid,{}).get("last_welcome_id")
        old_m = users_db.get(uid,{}).get("last_menu_id")
        sdel(uid, [old_w, old_m])
    
    mk = types.InlineKeyboardMarkup()
    mk.add(types.InlineKeyboardButton("📂 Открыть меню", callback_data="open_menu_init"))
    
    m=bot.send_message(uid,f"👋 <b>Привет, {name}!</b>\n\nЯ бот-помощник группы.\nНажми кнопку ниже, чтобы открыть меню.",reply_markup=mk,parse_mode='HTML')
    with data_lock: ensure_user(uid); users_db[uid]["last_welcome_id"]=m.message_id; save_all("users",users_db)

# ==========================================
# MAIN MENU
# ==========================================
def send_menu(cid, mid=None):
    with data_lock:
        ensure_user(cid)
        if mid is None:
            old_menu = users_db[cid].get("last_menu_id")
            if old_menu: 
                sdel(cid, old_menu)
                users_db[cid]["last_menu_id"] = None

    mk=types.InlineKeyboardMarkup(row_width=2)
    mk.add(types.InlineKeyboardButton("📅 Расписание",callback_data="m_sched"),
           types.InlineKeyboardButton("🏠 ДЗ",callback_data="m_hw"))
    mk.add(types.InlineKeyboardButton("🚩 КТ",callback_data="m_ct"),
           types.InlineKeyboardButton("⏳ Дедлайны",callback_data="m_dl"))
    mk.add(types.InlineKeyboardButton("⚙️ Настройки",callback_data="m_set"))
    
    if is_admin(cid):
        mk.add(types.InlineKeyboardButton("➖➖ АДМИНКА ➖➖",callback_data="ign"))
        mk.add(types.InlineKeyboardButton("✏️ ДЗ (Админ)",callback_data="a_hw"))
        mk.add(types.InlineKeyboardButton("📋 Отсутствующие",callback_data="a_abs"))
        mk.add(types.InlineKeyboardButton("✏️ КТ",callback_data="a_ct"), types.InlineKeyboardButton("⏳ Дедлайны",callback_data="a_dl"))
        mk.add(types.InlineKeyboardButton("📊 Опрос",callback_data="a_poll"), types.InlineKeyboardButton("📢 Рассылка",callback_data="a_bcast"))
        mk.add(types.InlineKeyboardButton("💬 Обр. связь",callback_data="a_fb"), types.InlineKeyboardButton("📬 Предложка",callback_data="a_sug"))
    else:
        n=users_db.get(cid,{}).get("name","Студент")
        mk.add(types.InlineKeyboardButton(f"👤 {n}",callback_data="ign"))
        mk.add(types.InlineKeyboardButton("🚫 Отсутствие",callback_data="abs_m"),
               types.InlineKeyboardButton("💬 Обр. связь",callback_data="fb_send"))
        mk.add(types.InlineKeyboardButton("📬 Предложка",callback_data="sug_send"))
    
    txt="📂 <b>ГЛАВНОЕ МЕНЮ</b>\nВыберите раздел:"
    if mid:
        try: bot.edit_message_text(txt,cid,mid,reply_markup=mk,parse_mode='HTML'); return
        except: pass
    
    m=bot.send_message(cid,txt,reply_markup=mk,parse_mode='HTML')
    with data_lock: 
        users_db[cid]["last_menu_id"]=m.message_id
        save_all("users",users_db)

# ==========================================
# CALLBACK ROUTER
# ==========================================
@bot.callback_query_handler(func=lambda c: True)
def cb(call):
    uid=call.message.chat.id; mid=call.message.message_id; d=call.data
    try: bot.answer_callback_query(call.id)
    except: pass
    
    if d in ["back", "m_hw", "a_sug"] or d.startswith("hw_s_"):
         c = get_ec(uid)
         if "view_msgs" in c:
             sdel(uid, c["view_msgs"])
             c["view_msgs"] = []
    
    if d in ["back", "fb_send", "sug_send"]:
        clear_ec(uid)

    try:
        if d=="ign": return

        # === ЛОГИКА ОТКРЫТИЯ МЕНЮ ИЗ ПРИВЕТСТВИЯ ===
        if d=="open_menu_init":
            sdel(uid, mid) 
            send_menu(uid)
            return

        if d=="back": send_menu(uid,mid); return

        # Schedule
        if d=="m_sched": sched_menu(uid,mid)
        elif d in("sc_today","sc_tom","sc_full"): sched_view(call)
        elif d=="sc_edit": sched_editor(uid,mid)
        elif d=="sc_subj": subj_menu(uid,mid)
        elif d.startswith("ed_"): sched_ed(call)
        elif d=="confirm_times": confirm_times(call)
        elif d.startswith("t_"): time_wiz(call)
        elif d.startswith("sj_"): subj_sel(call)
        elif d.startswith("al_"): link_dec(call)
        elif d.startswith("sct_"): ct_dec(call)
        elif d.startswith("sn_"): note_dec(call)
        elif d.startswith("sm_"): subj_act(call)

        # HW (USER & ADMIN)
        elif d=="m_hw": hw_menu_user(uid,mid)
        elif d.startswith("hw_s_"): hw_subj_view(call) 
        elif d.startswith("hw_v_"): hw_view_detail(call, is_update=False)
        elif d.startswith("hw_t_"): hw_toggle_done(call)
        elif d=="a_hw": hw_editor_admin(uid,mid)
        elif d=="hw_add_new": hw_add_start(uid,mid)
        elif d.startswith("hw_d_"): hw_delete_act(call)

        # CT / DL
        elif d=="m_ct": ct_user(uid,mid)
        elif d=="a_ct": ct_editor(uid,mid)
        elif d.startswith("ct_"): ct_act(call)
        elif d=="m_dl": dl_user(uid,mid)
        elif d=="a_dl": dl_editor(uid,mid)
        elif d.startswith("dl_"): dl_act(call)

        # Settings
        elif d.startswith("m_set") or d.startswith("opt_"): settings(call)
        elif d=="set_restart": set_restart(uid,mid)
        elif d.startswith("set_clear"): set_clear(call)

        # Absence
        elif d.startswith("abs_"): absence(call)

        # Polls
        elif d=="a_poll": poll_create(call)
        elif d.startswith("pv_") or d.startswith("pr_"): poll_vote(call)
        elif d.startswith("pend_"): poll_end(call)
        elif d.startswith("pdel_"): poll_del(call)

        # Feedback
        elif d=="fb_send": fb_start(call)
        elif d=="a_fb": fb_list(call)
        elif d.startswith("fb_mode_"): fb_confirm_mode(call)
        elif d.startswith("fb_"): fb_act(call)

        # Suggestions
        elif d=="sug_send": sug_start(call)
        elif d=="a_sug": sug_admin(call)
        elif d.startswith("sg_"): sug_act(call)

        # Admin
        elif d.startswith("a_"): admin_act(call)
    except Exception as e:
        print(f"[ERR] cb '{d}': {e}"); traceback.print_exc()

# ==========================================
# SCHEDULE & SUBJECTS
# ==========================================
def sched_menu(uid,mid):
    mk=types.InlineKeyboardMarkup(row_width=2)
    mk.add(types.InlineKeyboardButton("📅 Сегодня",callback_data="sc_today"),
           types.InlineKeyboardButton("📅 Завтра",callback_data="sc_tom"))
    mk.add(types.InlineKeyboardButton("📅 Вся неделя",callback_data="sc_full"))
    if is_admin(uid):
        mk.add(types.InlineKeyboardButton("─────────",callback_data="ign"))
        mk.add(types.InlineKeyboardButton("✏️ Редактировать",callback_data="sc_edit"))
        mk.add(types.InlineKeyboardButton("📚 Предметы",callback_data="sc_subj"))
    mk.add(types.InlineKeyboardButton("⬅️",callback_data="back"))
    now=moscow(); dr=DAYS_RU.get(now.strftime("%A"),"")
    try: bot.edit_message_text(f"📅 <b>Расписание</b>\nСегодня: <b>{dr}</b>, {now.strftime('%d.%m.%Y')}",uid,mid,reply_markup=mk,parse_mode='HTML')
    except: pass

def sched_view(call):
    uid=call.message.chat.id; mid=call.message.message_id; d=call.data; now=moscow()
    if d=="sc_today": txt=fmt_day(now.strftime("%A"),now)
    elif d=="sc_tom": t=now+timedelta(days=1); txt=fmt_day(t.strftime("%A"),t)
    else: txt=fmt_full()
    mk=types.InlineKeyboardMarkup()
    mk.add(types.InlineKeyboardButton("⬅️",callback_data="m_sched"))
    mk.add(types.InlineKeyboardButton("🏠 Меню",callback_data="back"))
    try: bot.edit_message_text(txt,uid,mid,reply_markup=mk,parse_mode='HTML',disable_web_page_preview=True)
    except: pass

def fmt_day(de,dt):
    dr=DAYS_RU.get(de,de); ls=content_db.get("schedule",{}).get(de,[]); ds=dt.strftime('%d.%m.%Y')
    if not ls: return f"📅 <b>{dr}</b> ({ds})\n\n😴 Пар нет!"
    now=moscow(); txt=f"📅 <b>{dr}</b> ({ds})\n\n"
    for i,l in enumerate(ls,1):
        mark=""
        if dt.date()==now.date():
            try:
                ss=l.get("start_clean") or l["time"].split("-")[0].strip()
                sh,sm=map(int,ss.split(":")); ep=l["time"].split("-")[1].strip().split(":")
                eh,em=int(ep[0]),int(ep[1])
                s=now.replace(hour=sh,minute=sm,second=0); e=now.replace(hour=eh,minute=em,second=0)
                if s<=now<=e: mark=f" 👈 <i>({max(0,int((e-now).total_seconds()//60))} мин)</i>"
                elif now<s and (s-now).total_seconds()<=1800: mark=f" ⏳ <i>({int((s-now).total_seconds()//60)} мин)</i>"
            except: pass
        ct="🔴 <b>КТ</b> " if l.get('ct') else ""
        ex=""
        if l.get('link'): ex+=f"\n   └ 🔗 <a href='{l['link']}'>Ссылка</a>"
        if l.get('note'): ex+=f"\n   └ 📝 <i>{l['note']}</i>"
        txt+=f"{i}️⃣ <code>{l['time']}</code> — {ct}<b>{l['name']}</b>{mark}{ex}\n"
    return txt

def fmt_full():
    sc=content_db.get("schedule",{})
    if all(not sc.get(d) for d in sc): return "<b>🎓 РАСПИСАНИЕ:</b>\n\nПусто. 😴"
    txt="<b>🎓 РАСПИСАНИЕ</b>\n"
    for de in ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]:
        ls=sc.get(de,[])
        if not ls: continue
        txt+=f"\n━━━━━━━━━━━━\n🗓 <b>{DAYS_RU.get(de,de)}</b>\n"
        for i,l in enumerate(ls,1):
            ct="🔴 <b>КТ</b> " if l.get('ct') else ""
            ex=""
            if l.get('link'): ex+=f"\n   └ 🔗 <a href='{l['link']}'>Ссылка</a>"
            if l.get('note'): ex+=f"\n   └ 📝 <i>{l['note']}</i>"
            txt+=f"{i}️⃣ <code>{l.get('time','?')}</code> — {ct}<b>{l.get('name','?')}</b>{ex}\n"
    return txt

def subj_menu(uid,mid):
    mk=types.InlineKeyboardMarkup()
    mk.add(types.InlineKeyboardButton("➕ Добавить",callback_data="sm_add"))
    if subjects_db:
        mk.add(types.InlineKeyboardButton("📋 Список",callback_data="sm_list"))
        mk.add(types.InlineKeyboardButton("🗑 Удалить",callback_data="sm_dlist"))
    mk.add(types.InlineKeyboardButton("⬅️",callback_data="m_sched"))
    try: bot.edit_message_text(f"📚 <b>Предметы</b>\nВсего: <b>{len(subjects_db)}</b>",uid,mid,reply_markup=mk,parse_mode='HTML')
    except: pass

def subj_act(call):
    uid=call.message.chat.id; mid=call.message.message_id; d=call.data
    if not is_admin(uid): return
    if d=="sm_add":
        sdel(uid,mid)
        m=bot.send_message(uid,"📚 <b>Название предмета:</b>\n<i>Введите название...</i>",parse_mode='HTML',reply_markup=input_kb())
        set_ec(uid,{"state":"subj_add_name","prompt_id":m.message_id,"msgs_to_del":[]})
        bot.register_next_step_handler(m, do_subj_name)
    elif d=="sm_list":
        txt="📚 <b>ПРЕДМЕТЫ:</b>\n\n"
        for i,s in enumerate(subjects_db,1):
            txt+=f"{i}. {subj_name(s)}{'🔗' if subj_link(s) else ''}\n"
        mk=types.InlineKeyboardMarkup()
        mk.add(types.InlineKeyboardButton("⬅️",callback_data="sc_subj"))
        try: bot.edit_message_text(txt,uid,mid,reply_markup=mk,parse_mode='HTML')
        except: pass
    elif d=="sm_dlist":
        mk=types.InlineKeyboardMarkup()
        for i,s in enumerate(subjects_db):
            mk.add(types.InlineKeyboardButton(f"❌ {subj_name(s)}",callback_data=f"sm_d{i}"))
        mk.add(types.InlineKeyboardButton("⬅️",callback_data="sc_subj"))
        try: bot.edit_message_text("🗑 <b>Удалить:</b>",uid,mid,reply_markup=mk,parse_mode='HTML')
        except: pass
    elif d.startswith("sm_d"):
        idx=int(d[4:])
        with data_lock:
            if 0<=idx<len(subjects_db): subjects_db.pop(idx); save_all("subjects",subjects_db)
        subj_menu(uid,mid)

def do_subj_name(msg):
    uid=msg.chat.id; t=(msg.text or"").strip()
    sdel(uid,msg.message_id); c=edit_cache.get(uid,{}); sdel(uid,c.get("prompt_id"))
    if t == "Отмена":
        clear_ec(uid)
        m=bot.send_message(uid,"❌ Отмена",reply_markup=remove_kb()); ddel(uid,m.message_id,3)
        send_menu(uid); return
    if not t:
        m=bot.send_message(uid,"⚠️ Пустое название:",reply_markup=input_kb())
        set_ec(uid,{"state":"subj_add_name","prompt_id":m.message_id,"msgs_to_del":[]})
        bot.register_next_step_handler(m, do_subj_name); return
    m=bot.send_message(uid,f"🔗 Ссылка для «{t}»\n<i>Отправьте ссылку или нажмите Пропустить</i>",parse_mode='HTML',reply_markup=input_kb(skip=True))
    set_ec(uid,{"state":"subj_add_link","subj_name":t,"prompt_id":m.message_id,"msgs_to_del":[]})
    bot.register_next_step_handler(m, do_subj_link)

def do_subj_link(msg):
    uid=msg.chat.id; t=(msg.text or"").strip()
    sdel(uid,msg.message_id); c=edit_cache.get(uid,{}); sdel(uid,c.get("prompt_id"))
    if t == "Отмена":
        clear_ec(uid)
        m=bot.send_message(uid,"❌ Отмена",reply_markup=remove_kb()); ddel(uid,m.message_id,3)
        send_menu(uid); return
    link="" if (t in ["-", "Пропустить (-)"]) else t; name=c.get("subj_name","?")
    with data_lock:
        subjects_db.append({"name":name,"link":link}); save_all("subjects",subjects_db)
        if link: content_db["subject_links"][name]=link; save_all("content",content_db)
    clear_ec(uid)
    m=bot.send_message(uid,f"✅ <b>«{name}»</b> добавлен!",parse_mode='HTML',reply_markup=remove_kb())
    send_menu(uid); ddel(uid,m.message_id,3)

def sched_editor(uid,mid):
    mk=types.InlineKeyboardMarkup(row_width=2)
    for code,ru in [(c,DAYS_RU[c]) for c in ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]]:
        ls=content_db["schedule"].get(code,[])
        mk.add(types.InlineKeyboardButton(f"{ru} ({len(ls)})" if ls else ru,callback_data=f"ed_d_{code}"))
    mk.add(types.InlineKeyboardButton("🗑 Очистить",callback_data="ed_clr"))
    mk.add(types.InlineKeyboardButton("⬅️",callback_data="m_sched"))
    try: bot.edit_message_text("🗓 <b>Редактор расписания</b>",uid,mid,reply_markup=mk,parse_mode='HTML')
    except: pass

def sched_ed(call):
    uid=call.message.chat.id; mid=call.message.message_id; d=call.data
    if not is_admin(uid): return
    if d=="ed_clr":
        mk=types.InlineKeyboardMarkup()
        mk.add(types.InlineKeyboardButton("🔥 Да",callback_data="ed_clrc"),types.InlineKeyboardButton("❌",callback_data="sc_edit"))
        try: bot.edit_message_text("⚠️ Очистить всё?",uid,mid,reply_markup=mk,parse_mode='HTML')
        except: pass
    elif d=="ed_clrc":
        with data_lock:
            for day in content_db["schedule"]: content_db["schedule"][day]=[]
            save_all("content",content_db)
        sched_editor(uid,mid)
    elif d.startswith("ed_d_"):
        dc=d[5:]
        if not subjects_db:
            try: bot.answer_callback_query(call.id,"⚠️ Сначала добавьте предметы!",show_alert=True)
            except: pass
            return
        set_ec(uid,{"state":"sched_edit","day":dc,"lessons":[],"msgs_to_del":[],"temp":{}})
        mk=types.InlineKeyboardMarkup(row_width=3)
        for i in range(7): mk.add(types.InlineKeyboardButton(str(i),callback_data=f"ed_c_{i}"))
        mk.add(types.InlineKeyboardButton("⬅️",callback_data="sc_edit"))
        try: bot.edit_message_text(f"<b>{DAYS_RU.get(dc,dc)}</b>\nСколько пар?",uid,mid,reply_markup=mk,parse_mode='HTML')
        except: pass
    elif d.startswith("ed_c_"):
        cnt=int(d[5:]); c=edit_cache.get(uid)
        if not c or c.get("state")!="sched_edit": return
        c["total"]=cnt
        if cnt==0:
            with data_lock: content_db["schedule"][c["day"]]=[]; save_all("content",content_db)
            clear_ec(uid); sched_editor(uid,mid)
        else:
            sdel(uid,mid); c["temp"]={}; ask_hour(uid)

def ask_hour(uid,prev=None):
    if prev: sdel(uid,prev)
    mk=types.InlineKeyboardMarkup(row_width=4)
    btns=[types.InlineKeyboardButton(f"{h:02d}",callback_data=f"t_h_{h:02d}") for h in range(7,21)]
    for i in range(0,len(btns),4): mk.row(*btns[i:i+4])
    m=bot.send_message(uid,f"🕐 <b>Час начала 1-й пары</b>\n(пара {LESSON_DURATION} мин)",reply_markup=mk,parse_mode='HTML')
    edit_cache[uid]["msgs_to_del"].append(m.message_id)

def ask_min(uid,prev=None):
    if prev: sdel(uid,prev)
    h=edit_cache[uid]["temp"]["fh"]
    mk=types.InlineKeyboardMarkup(row_width=4)
    btns=[types.InlineKeyboardButton(f"{m:02d}",callback_data=f"t_m_{m:02d}") for m in range(0,60,5)]
    for i in range(0,len(btns),4): mk.row(*btns[i:i+4])
    m=bot.send_message(uid,f"🕐 <b>{h}:??</b> — минуты:",reply_markup=mk,parse_mode='HTML')
    edit_cache[uid]["msgs_to_del"].append(m.message_id)

def ask_break(uid, prev=None):
    if prev: sdel(uid, prev)
    mk = types.InlineKeyboardMarkup(row_width=3)
    opts = [0, 5, 10, 15, 20, 30]
    btns = [types.InlineKeyboardButton(f"{o} мин", callback_data=f"t_b_{o}") for o in opts]
    mk.add(*btns)
    m = bot.send_message(uid, "☕ <b>Выберите перерыв между парами:</b>", reply_markup=mk, parse_mode='HTML')
    edit_cache[uid]["msgs_to_del"].append(m.message_id)

def time_wiz(call):
    uid=call.message.chat.id; mid=call.message.message_id; d=call.data
    p=d.split('_')
    if len(p)<3: return
    if p[1]=="h": 
        edit_cache[uid]["temp"]["fh"]=p[2]
        ask_min(uid,mid)
    elif p[1]=="m":
        edit_cache[uid]["temp"]["fm"]=p[2]
        ask_break(uid, mid)
    elif p[1]=="b":
        b_min = int(p[2])
        h=edit_cache[uid]["temp"]["fh"]
        m=edit_cache[uid]["temp"]["fm"]
        ft=f"{h}:{m}"
        total=edit_cache[uid].get("total",0)
        edit_cache[uid]["auto_times"]=auto_times(ft,total,b_min)
        sdel(uid,mid); show_times_preview(uid)

def show_times_preview(uid):
    ts=edit_cache[uid]["auto_times"]
    txt="🕐 <b>Звонки:</b>\n\n"
    for i,(s,e) in enumerate(ts,1): txt+=f"{i}️⃣ <code>{s} - {e}</code>\n"
    mk=types.InlineKeyboardMarkup()
    mk.add(types.InlineKeyboardButton("👍 Ок",callback_data="confirm_times"))
    mk.add(types.InlineKeyboardButton("❌",callback_data="sc_edit"))
    m=bot.send_message(uid,txt,reply_markup=mk,parse_mode='HTML')
    edit_cache[uid]["msgs_to_del"].append(m.message_id)

def confirm_times(call):
    uid=call.message.chat.id; sdel(uid,call.message.message_id)
    edit_cache[uid]["cur"]=1; edit_cache[uid]["temp"]={}; ask_subj(uid,1)

def ask_subj(uid,num):
    ts=edit_cache[uid]["auto_times"]
    if num-1>=len(ts): return
    s,e=ts[num-1]
    mk=types.InlineKeyboardMarkup(row_width=1)
    for i,subj in enumerate(subjects_db):
        n=subj_name(subj); lk="🔗" if subj_link(subj) else ""
        mk.add(types.InlineKeyboardButton(f"{n} {lk}",callback_data=f"sj_{i}_{num}"))
    m=bot.send_message(uid,f"📚 <b>Пара №{num}</b> (<code>{s}-{e}</code>)\nПредмет:",reply_markup=mk,parse_mode='HTML')
    edit_cache[uid]["msgs_to_del"].append(m.message_id)

def subj_sel(call):
    uid=call.message.chat.id; mid=call.message.message_id; d=call.data
    p=d.split('_'); idx=int(p[1]); num=int(p[2])
    if idx>=len(subjects_db): return
    subj=subjects_db[idx]; ts=edit_cache[uid]["auto_times"]
    if num-1>=len(ts): return
    s,e=ts[num-1]
    edit_cache[uid]["temp"].update({"name":subj_name(subj),"time_str":f"{s} - {e}","start_clean":s,"saved_link":subj_link(subj)})
    ask_link(uid,num,mid)

def ask_link(uid,num,prev=None):
    if prev: sdel(uid,prev)
    name=edit_cache[uid]["temp"]["name"]; saved=edit_cache[uid]["temp"].get("saved_link","") or content_db.get("subject_links",{}).get(name,"")
    mk=types.InlineKeyboardMarkup()
    if saved:
        mk.add(types.InlineKeyboardButton("🔗 Сохранённая",callback_data=f"al_p_{num}"))
        mk.add(types.InlineKeyboardButton("🆕 Новая",callback_data=f"al_y_{num}"))
    else:
        mk.add(types.InlineKeyboardButton("🔗 Добавить",callback_data=f"al_y_{num}"))
    mk.add(types.InlineKeyboardButton("❌ Нет",callback_data=f"al_n_{num}"))
    m=bot.send_message(uid,f"🔗 <b>{name}</b> — ссылка?",reply_markup=mk,parse_mode='HTML')
    edit_cache[uid]["msgs_to_del"].append(m.message_id)

def link_dec(call):
    uid=call.message.chat.id; mid=call.message.message_id; d=call.data
    p=d.split('_'); ch=p[1]; num=int(p[2]); name=edit_cache[uid]["temp"].get("name","")
    if ch=="p":
        saved=edit_cache[uid]["temp"].get("saved_link","") or content_db.get("subject_links",{}).get(name,"")
        edit_cache[uid]["temp"]["link"]=saved; ask_ct_q(uid,num,mid)
    elif ch=="y":
        sdel(uid,mid); m=bot.send_message(uid,"🔗 Ссылку:",reply_markup=input_kb())
        edit_cache[uid]["msgs_to_del"].append(m.message_id); edit_cache[uid]["link_num"]=num
        bot.register_next_step_handler(m, do_link_txt)
    else:
        edit_cache[uid]["temp"]["link"]=""; ask_ct_q(uid,num,mid)

def do_link_txt(msg):
    uid=msg.chat.id
    edit_cache[uid]["msgs_to_del"].append(msg.message_id)
    if msg.text == "Отмена":
        clear_ec(uid)
        m=bot.send_message(uid,"❌ Отмена",reply_markup=remove_kb()); ddel(uid,m.message_id,3)
        send_menu(uid); return
    link=(msg.text or"").strip(); num=edit_cache[uid].pop("link_num",1)
    name=edit_cache[uid]["temp"].get("name","")
    edit_cache[uid]["temp"]["link"]=link
    if name and link:
        with data_lock:
            content_db["subject_links"][name]=link
            for s in subjects_db:
                if isinstance(s,dict) and s.get("name")==name: s["link"]=link; break
            save_all("content",content_db); save_all("subjects",subjects_db)
    ask_ct_q(uid,num)

def ask_ct_q(uid,num,prev=None):
    if prev: sdel(uid,prev)
    mk=types.InlineKeyboardMarkup()
    mk.add(types.InlineKeyboardButton("Да",callback_data=f"sct_y_{num}"),types.InlineKeyboardButton("Нет",callback_data=f"sct_n_{num}"))
    m=bot.send_message(uid,"🔴 КТ?",reply_markup=mk)
    edit_cache[uid]["msgs_to_del"].append(m.message_id)

def ct_dec(call):
    uid=call.message.chat.id; mid=call.message.message_id; d=call.data
    p=d.split('_'); edit_cache[uid]["temp"]["ct"]=(p[1]=="y"); num=int(p[2])
    ask_note_q(uid,num,mid)

def ask_note_q(uid,num,prev=None):
    if prev: sdel(uid,prev)
    mk=types.InlineKeyboardMarkup()
    mk.add(types.InlineKeyboardButton("Добавить",callback_data=f"sn_y_{num}"),types.InlineKeyboardButton("Нет",callback_data=f"sn_n_{num}"))
    m=bot.send_message(uid,"📝 Заметка?",reply_markup=mk)
    edit_cache[uid]["msgs_to_del"].append(m.message_id)

def note_dec(call):
    uid=call.message.chat.id; mid=call.message.message_id; d=call.data
    p=d.split('_'); ch=p[1]; num=int(p[2])
    if ch=="y":
        sdel(uid,mid); m=bot.send_message(uid,"✍️ Заметка:",reply_markup=input_kb())
        edit_cache[uid]["msgs_to_del"].append(m.message_id); edit_cache[uid]["note_num"]=num
        bot.register_next_step_handler(m, do_note_txt)
    else:
        edit_cache[uid]["temp"]["note"]=""; fin_lesson(uid,num)

def do_note_txt(msg):
    uid=msg.chat.id
    edit_cache[uid]["msgs_to_del"].append(msg.message_id)
    if msg.text == "Отмена":
        clear_ec(uid)
        m=bot.send_message(uid,"❌ Отмена",reply_markup=remove_kb()); ddel(uid,m.message_id,3)
        send_menu(uid); return
    edit_cache[uid]["temp"]["note"]=msg.text or""
    fin_lesson(uid, edit_cache[uid].pop("note_num",1))

def fin_lesson(uid,num):
    c=edit_cache.get(uid)
    if not c: return
    t=c.get("temp",{})
    c["lessons"].append({"time":t.get("time_str",""),"start_clean":t.get("start_clean",""),
        "name":t.get("name",""),"link":t.get("link",""),"ct":t.get("ct",False),"note":t.get("note","")})
    if num<c.get("total",0): c["temp"]={}; ask_subj(uid,num+1)
    else:
        with data_lock: content_db["schedule"][c["day"]]=c["lessons"]; save_all("content",content_db)
        sdel(uid,c.get("msgs_to_del",[])); dr=DAYS_RU.get(c["day"],c["day"])
        m=bot.send_message(uid,f"✅ <b>{dr}</b> сохранён!",parse_mode='HTML',reply_markup=remove_kb())
        edit_cache.pop(uid,None); send_menu(uid); ddel(uid,m.message_id,2)

# ==========================================
# HOMEWORK
# ==========================================

# 1. МЕНЮ ПОЛЬЗОВАТЕЛЯ
def hw_menu_user(uid,mid):
    with data_lock:
        hw_list = content_db.get("hw", [])
        user_done = set(users_db.get(uid, {}).get("hw_done", []))

    if not hw_list:
        try: bot.edit_message_text("🏠 <b>ДЗ</b>\n\nПусто 🎉",uid,mid,reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("⬅️",callback_data="back")),parse_mode='HTML')
        except: pass
        return

    subjects = {}
    for h in hw_list:
        subj = h.get("subject", "Общее")
        if subj not in subjects: subjects[subj] = {"total": 0, "done": 0}
        subjects[subj]["total"] += 1
        if h.get("id") in user_done:
            subjects[subj]["done"] += 1

    mk = types.InlineKeyboardMarkup(row_width=1)
    for subj, stats in subjects.items():
        btn_text = f"{subj} [{stats['done']}/{stats['total']}]"
        mk.add(types.InlineKeyboardButton(btn_text, callback_data=f"hw_s_{subj}"))
    mk.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="back"))

    try: bot.edit_message_text("🏠 <b>Предметы с ДЗ:</b>",uid,mid,reply_markup=mk,parse_mode='HTML')
    except: pass

# 2. СПИСОК ЗАДАНИЙ
def hw_subj_view(call):
    uid = call.message.chat.id
    mid = call.message.message_id
    subj_name = call.data[5:]

    c = get_ec(uid)
    if "view_msgs" in c and c["view_msgs"]:
        sdel(uid, c["view_msgs"])
        c["view_msgs"] = []
    set_ec(uid, c)

    sdel(uid, mid)

    with data_lock:
        hw_list = [h for h in content_db.get("hw", []) if h.get("subject") == subj_name]
        user_done = set(users_db.get(uid, {}).get("hw_done", []))

    if not hw_list:
        send_menu(uid)
        return

    hw_list.sort(key=lambda x: x.get("date", "99.99.9999"))
    mk = types.InlineKeyboardMarkup(row_width=1)
    for h in hw_list:
        status = "✅" if h.get("id") in user_done else "⭕"
        due_date = h.get("date") or "?"
        btn_text = f"{status} {h.get('title','?')} ({due_date})"
        mk.add(types.InlineKeyboardButton(btn_text, callback_data=f"hw_v_{h['id']}"))
    mk.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="m_hw"))

    bot.send_message(uid, f"📚 <b>{subj_name}</b>\nСписок заданий:", reply_markup=mk, parse_mode='HTML')

# 3. ДЕТАЛИ ЗАДАНИЯ
def hw_view_detail(call, is_update=False):
    uid = call.message.chat.id
    mid = call.message.message_id
    hid = call.data[5:]

    with data_lock:
        hw_item = next((h for h in content_db.get("hw", []) if h.get("id") == hid), None)
        user_done = users_db.get(uid, {}).get("hw_done", [])
        is_done = hid in user_done

    if not hw_item:
        hw_menu_user(uid, mid)
        return

    if not is_update:
        sdel(uid, mid)

    c = get_ec(uid)
    sent_files = []
    
    if not is_update and hw_item.get("files"):
        for f in hw_item["files"]:
            try:
                fid = f["file_id"]
                ftype = f.get("type", "document")
                caption = f.get("name", "")
                
                if ftype == "photo": m=bot.send_photo(uid, fid, caption=caption)
                elif ftype == "video": m=bot.send_video(uid, fid, caption=caption)
                elif ftype == "audio": m=bot.send_audio(uid, fid, caption=caption)
                elif ftype == "voice": m=bot.send_voice(uid, fid, caption=caption)
                else: m=bot.send_document(uid, fid, caption=caption)
                sent_files.append(m.message_id)
            except: pass
        
        c["view_msgs"] = sent_files
        set_ec(uid, c)

    created_dt = hw_item.get("assigned_date") or datetime.fromtimestamp(hw_item.get("created", 0)).strftime("%d.%m.%Y")
    due_date = hw_item.get("date", "Не указано")
    status_txt = "✅ Выполнено" if is_done else "⭕ Не выполнено"
    
    txt = (f"📌 <b>{hw_item.get('title')}</b>\n"
           f"📚 Предмет: {hw_item.get('subject')}\n\n"
           f"📅 Задано: {created_dt}\n"
           f"📅 Сдать до: {due_date}\n\n"
           f"📝 <b>Задание:</b>\n{hw_item.get('text','-')}\n\n"
           f"Статус: <b>{status_txt}</b>")

    mk = types.InlineKeyboardMarkup()
    toggle_btn_txt = "❌ Отменить" if is_done else "✅ Отметить выполненным"
    mk.add(types.InlineKeyboardButton(toggle_btn_txt, callback_data=f"hw_t_{hid}"))
    mk.add(types.InlineKeyboardButton("⬅️ К списку", callback_data=f"hw_s_{hw_item.get('subject')}"))

    if is_update:
        try: bot.edit_message_text(txt, uid, mid, reply_markup=mk, parse_mode='HTML')
        except: pass
    else:
        m = bot.send_message(uid, txt, reply_markup=mk, parse_mode='HTML')
        c = get_ec(uid)
        if "view_msgs" not in c: c["view_msgs"] = []
        c["view_msgs"].append(m.message_id)
        set_ec(uid, c)

def hw_toggle_done(call):
    uid = call.message.chat.id
    hid = call.data[5:]
    with data_lock:
        if "hw_done" not in users_db[uid]: users_db[uid]["hw_done"] = []
        if hid in users_db[uid]["hw_done"]:
            users_db[uid]["hw_done"].remove(hid)
        else:
            users_db[uid]["hw_done"].append(hid)
        save_all("users", users_db)
    hw_view_detail(call, is_update=True)

# --- ADMIN PART (EDITOR) ---
def hw_editor_admin(uid,mid):
    if not is_admin(uid): return
    mk=types.InlineKeyboardMarkup()
    mk.add(types.InlineKeyboardButton("➕ Создать ДЗ",callback_data="hw_add_new"))
    hw_list = content_db.get("hw", [])
    if hw_list:
        for i,h in enumerate(hw_list):
            mk.add(types.InlineKeyboardButton(f"🗑 {h.get('subject')} - {h.get('title')}", callback_data=f"hw_d_{i}"))
    mk.add(types.InlineKeyboardButton("⬅️ Меню",callback_data="back"))
    try: bot.edit_message_text(f"🏠 <b>Админ: ДЗ</b>\nВсего: {len(hw_list)}",uid,mid,reply_markup=mk,parse_mode='HTML')
    except: pass

def hw_delete_act(call):
    if not is_admin(call.message.chat.id): return
    try:
        idx = int(call.data[5:])
        with data_lock:
             if 0 <= idx < len(content_db["hw"]):
                 content_db["hw"].pop(idx)
                 save_all("content", content_db)
        hw_editor_admin(call.message.chat.id, call.message.message_id)
    except: pass

# --- СОЗДАНИЕ ДЗ (АДМИН) ---
def hw_add_start(uid,mid):
    sdel(uid,mid)
    mk = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    existing_subjs = set(s.get("name") for s in subjects_db)
    existing_subjs.add("Общее")
    for s in existing_subjs: mk.add(types.KeyboardButton(s))
    mk.add(types.KeyboardButton("Отмена"))

    m = bot.send_message(uid, "📚 <b>Выберите предмет</b> или напишите новый:", parse_mode='HTML', reply_markup=mk)
    set_ec(uid, {"state":"hw_subj_sel", "prompt_id":m.message_id, "msgs_to_del":[], "temp_hw":{}})
    bot.register_next_step_handler(m, do_hw_subj)

def do_hw_subj(msg):
    uid=msg.chat.id; t=(msg.text or"").strip()
    c=edit_cache.get(uid); sdel(uid, [msg.message_id, c.get("prompt_id")])
    if t == "Отмена":
        clear_ec(uid)
        m=bot.send_message(uid,"❌ Отмена",reply_markup=remove_kb()); ddel(uid,m.message_id,3)
        send_menu(uid); return

    c["temp_hw"]["subject"] = t
    m = bot.send_message(uid, "📝 <b>Название ДЗ:</b>\n<i>Введите название...</i>", reply_markup=input_kb(), parse_mode='HTML')
    c["state"] = "hw_title"
    c["prompt_id"] = m.message_id
    bot.register_next_step_handler(m, do_hw_title_new)

def do_hw_title_new(msg):
    uid=msg.chat.id; t=(msg.text or"").strip()
    c=edit_cache.get(uid); sdel(uid, [msg.message_id, c.get("prompt_id")])
    if t == "Отмена":
        clear_ec(uid)
        m=bot.send_message(uid,"❌ Отмена",reply_markup=remove_kb()); ddel(uid,m.message_id,3)
        send_menu(uid); return

    c["temp_hw"]["title"] = t
    m = bot.send_message(uid, "📝 <b>Текст задания:</b>\nМожно пропустить (-)", reply_markup=input_kb(skip=True), parse_mode='HTML')
    c["state"] = "hw_text"
    c["prompt_id"] = m.message_id
    bot.register_next_step_handler(m, do_hw_text_new)

def do_hw_text_new(msg):
    uid=msg.chat.id; t=(msg.text or"").strip()
    c=edit_cache.get(uid); sdel(uid, [msg.message_id, c.get("prompt_id")])
    if t == "Отмена":
        clear_ec(uid)
        m=bot.send_message(uid,"❌ Отмена",reply_markup=remove_kb()); ddel(uid,m.message_id,3)
        send_menu(uid); return

    c["temp_hw"]["text"] = "" if t in ["-", "Пропустить (-)"] else t
    
    today = datetime.utcnow() + timedelta(hours=3)
    today_str = today.strftime("%d.%m.%Y")
    m = bot.send_message(uid, f"📅 <b>Дата выдачи (задано):</b>\nВведите дату или <b>Пропустить</b> для сегодня ({today_str})", reply_markup=input_kb(skip=True), parse_mode='HTML')
    c["state"] = "hw_assigned_date"
    c["prompt_id"] = m.message_id
    bot.register_next_step_handler(m, do_hw_assigned_date)

def do_hw_assigned_date(msg):
    uid=msg.chat.id; t=(msg.text or"").strip()
    c=edit_cache.get(uid); sdel(uid, [msg.message_id, c.get("prompt_id")])
    if t == "Отмена":
        clear_ec(uid)
        m=bot.send_message(uid,"❌ Отмена",reply_markup=remove_kb()); ddel(uid,m.message_id,3)
        send_menu(uid); return

    if t in ["-", "Пропустить (-)"]:
        dt_str = (datetime.utcnow() + timedelta(hours=3)).strftime("%d.%m.%Y")
    else:
        dt_str = t 

    c["temp_hw"]["assigned_date"] = dt_str
    m = bot.send_message(uid, "📅 <b>Срок сдачи (Дедлайн):</b>\nДД.ММ.ГГГГ или Пропустить", reply_markup=input_kb(skip=True), parse_mode='HTML')
    c["state"] = "hw_date"
    c["prompt_id"] = m.message_id
    bot.register_next_step_handler(m, do_hw_date_new)

def do_hw_date_new(msg):
    uid=msg.chat.id; t=(msg.text or"").strip()
    c=edit_cache.get(uid); sdel(uid, [msg.message_id, c.get("prompt_id")])
    if t == "Отмена":
        clear_ec(uid)
        m=bot.send_message(uid,"❌ Отмена",reply_markup=remove_kb()); ddel(uid,m.message_id,3)
        send_menu(uid); return

    ds = ""
    if t and t not in ["-", "Пропустить (-)"]:
        try: datetime.strptime(t,"%d.%m.%Y"); ds=t
        except: 
            m=bot.send_message(uid,"⚠️ Формат ДД.ММ.ГГГГ!", reply_markup=input_kb(skip=True))
            c["prompt_id"]=m.message_id; bot.register_next_step_handler(m, do_hw_date_new); return
    
    c["temp_hw"]["date"] = ds
    c["temp_hw"]["files"] = []
    
    m = bot.send_message(uid, "📎 <b>Прикрепите файлы</b> (фото, видео, док).\nКогда закончите — нажмите <b>Готово</b>", parse_mode='HTML', reply_markup=input_kb(done=True))
    c["state"] = "hw_files"
    c["prompt_id"] = m.message_id
    bot.register_next_step_handler(m, do_hw_files_new)

def do_hw_files_new(msg):
    uid=msg.chat.id; c=edit_cache.get(uid)
    if not c or c.get("state")!="hw_files": return
    
    c["msgs_to_del"].append(msg.message_id)

    if msg.text == "Отмена":
        clear_ec(uid)
        m=bot.send_message(uid,"❌ Отмена",reply_markup=remove_kb()); ddel(uid,m.message_id,3)
        send_menu(uid); return

    if msg.text == "Готово":
        hw = c["temp_hw"]
        hw["id"] = str(uuid.uuid4())[:8]
        hw["created"] = time.time()
        
        with data_lock:
            content_db["hw"].append(hw)
            save_all("content", content_db)
        
        sdel(uid, c.get("prompt_id"))
        sdel(uid, c.get("msgs_to_del"))
        
        clear_ec(uid)
        m = bot.send_message(uid, f"✅ ДЗ по <b>{hw['subject']}</b> создано!", parse_mode='HTML', reply_markup=remove_kb())
        send_menu(uid); ddel(uid, m.message_id, 3)
        return

    file_id=None; file_name=None; file_type="document"
    if msg.document:
        file_id=msg.document.file_id; file_name=msg.document.file_name; file_type="document"
    elif msg.photo:
        file_id=msg.photo[-1].file_id; file_name="photo.jpg"; file_type="photo"
    elif msg.video:
        file_id=msg.video.file_id; file_name=msg.video.file_name or "video.mp4"; file_type="video"
    elif msg.audio:
        file_id=msg.audio.file_id; file_name=msg.audio.file_name or "audio"; file_type="audio"
    
    if file_id:
        c["temp_hw"]["files"].append(save_hw_file(file_id, file_name, file_type))
        reply = bot.send_message(uid, f"📎 +1 ({len(c['temp_hw']['files'])} шт). Ещё или <b>Готово</b>", parse_mode='HTML', reply_markup=input_kb(done=True))
        c["msgs_to_del"].append(reply.message_id)
        bot.register_next_step_handler(reply, do_hw_files_new)
    else:
        reply = bot.send_message(uid, "📎 Жду файл или <b>Готово</b>", parse_mode='HTML', reply_markup=input_kb(done=True))
        c["msgs_to_del"].append(reply.message_id)
        bot.register_next_step_handler(reply, do_hw_files_new)


# ==========================================
# CT / DL / POLLS
# ==========================================
def ct_user(uid,mid):
    with data_lock: 
        ct_list = list(content_db.get("ct",[]))
        sched = content_db.get("schedule", {})

    # Объединяем ручные КТ и КТ из расписания
    now = moscow()
    today = now.date()
    en_to_int = {"Monday":0,"Tuesday":1,"Wednesday":2,"Thursday":3,"Friday":4,"Saturday":5,"Sunday":6}

    for day_code, lessons in sched.items():
        if not lessons: continue
        wd_idx = en_to_int.get(day_code)
        if wd_idx is None: continue

        # Вычисляем дату следующего дня недели
        current_wd = today.weekday()
        delta_days = wd_idx - current_wd
        if delta_days < 0: delta_days += 7
        target_date = today + timedelta(days=delta_days)
        date_str = target_date.strftime("%d.%m.%Y")

        for l in lessons:
            if l.get("ct"):
                ct_list.append({
                    "title": f"📚 {l.get('name')} (по расписанию)",
                    "date": date_str,
                    "text": f"Время: {l.get('time')}",
                    "is_auto": True
                })

    if not ct_list: 
        txt="🚩 <b>КТ</b>\n\nПусто 🎉"
    else:
        def parse_ct_date(x):
            try: return datetime.strptime(x.get("date"), "%d.%m.%Y")
            except: return datetime.max
        ct_list.sort(key=parse_ct_date)

        txt="🚩 <b>КОНТРОЛЬНЫЕ ТОЧКИ:</b>\n\n"
        for i,c in enumerate(ct_list,1):
            st = ""
            if c.get('date'):
                try:
                    dd = datetime.strptime(c['date'], "%d.%m.%Y")
                    delta = (dd - now.replace(hour=0, minute=0, second=0, microsecond=0)).days
                    if delta < 0: st = f" — 🏁 прошел ({abs(delta)}д)"
                    elif delta == 0: st = " — 🔴 СЕГОДНЯ!"
                    elif delta == 1: st = " — 🟠 завтра!"
                    else: st = f" — 🟢 через {delta}д"
                except: pass

            txt+=f"🔴 <b>{c.get('title','?')}</b>\n"
            if c.get('date'): txt+=f"   └ 📅 {c['date']}{st}\n"
            if c.get('text'): txt+=f"   └ 📝 {c['text']}\n"
            txt+="\n"

    mk=types.InlineKeyboardMarkup()
    mk.add(types.InlineKeyboardButton("⬅️",callback_data="back"))
    try: bot.edit_message_text(txt,uid,mid,reply_markup=mk,parse_mode='HTML')
    except: pass

def ct_editor(uid,mid):
    if not is_admin(uid): return
    mk=types.InlineKeyboardMarkup()
    mk.add(types.InlineKeyboardButton("➕",callback_data="ct_add"))
    mk.add(types.InlineKeyboardButton("🗑 Удалить",callback_data="ct_dlist"))
    mk.add(types.InlineKeyboardButton("🗑 Все",callback_data="ct_clr"))
    mk.add(types.InlineKeyboardButton("⬅️",callback_data="back"))
    try: bot.edit_message_text(f"🚩 <b>Редактор КТ</b>\n{len(content_db.get('ct',[]))}",uid,mid,reply_markup=mk,parse_mode='HTML')
    except: pass

def ct_act(call):
    uid=call.message.chat.id; mid=call.message.message_id; d=call.data
    if not is_admin(uid): return
    if d=="ct_add":
        sdel(uid,mid)
        m=bot.send_message(uid,"📝 <b>Название КТ:</b>\n<i>Введите название...</i>",parse_mode='HTML',reply_markup=input_kb())
        set_ec(uid,{"state":"ct_title","prompt_id":m.message_id,"msgs_to_del":[]})
        bot.register_next_step_handler(m, do_ct_title)
    elif d=="ct_dlist":
        cl=content_db.get("ct",[])
        if not cl: return
        mk=types.InlineKeyboardMarkup()
        for i,c in enumerate(cl): mk.add(types.InlineKeyboardButton(f"❌ {c.get('title','?')}",callback_data=f"ct_d_{i}"))
        mk.add(types.InlineKeyboardButton("⬅️",callback_data="a_ct"))
        try: bot.edit_message_text("🗑",uid,mid,reply_markup=mk,parse_mode='HTML')
        except: pass
    elif d.startswith("ct_d_") and d!="ct_dlist":
        idx=int(d[5:])
        with data_lock:
            cl=content_db.get("ct",[])
            if 0<=idx<len(cl): cl.pop(idx); save_all("content",content_db)
        ct_editor(uid,mid)
    elif d=="ct_clr":
        mk=types.InlineKeyboardMarkup()
        mk.add(types.InlineKeyboardButton("🔥",callback_data="ct_clrc"),types.InlineKeyboardButton("❌",callback_data="a_ct"))
        try: bot.edit_message_text("⚠️ Все?",uid,mid,reply_markup=mk,parse_mode='HTML')
        except: pass
    elif d=="ct_clrc":
        with data_lock: content_db["ct"]=[]; save_all("content",content_db)
        ct_editor(uid,mid)

def do_ct_title(msg):
    uid=msg.chat.id; t=(msg.text or"").strip()
    c=edit_cache.get(uid,{}); sdel(uid,[msg.message_id, c.get("prompt_id")])
    if t == "Отмена":
        clear_ec(uid)
        m=bot.send_message(uid,"❌ Отмена",reply_markup=remove_kb()); ddel(uid,m.message_id,3)
        send_menu(uid); return
    if not t:
        m=bot.send_message(uid,"⚠️ Пустое:",reply_markup=input_kb())
        set_ec(uid,{"state":"ct_title","prompt_id":m.message_id,"msgs_to_del":[]})
        bot.register_next_step_handler(m, do_ct_title); return
    m=bot.send_message(uid,"📝 <b>Описание:</b>\n<i>Пропустить (-), если нет</i>",parse_mode='HTML',reply_markup=input_kb(skip=True))
    set_ec(uid,{"state":"ct_text","ct_title":t,"prompt_id":m.message_id,"msgs_to_del":[]})
    bot.register_next_step_handler(m, do_ct_text)

def do_ct_text(msg):
    uid=msg.chat.id; t=(msg.text or"").strip()
    c=edit_cache.get(uid,{}); sdel(uid,[msg.message_id, c.get("prompt_id")])
    if t == "Отмена":
        clear_ec(uid)
        m=bot.send_message(uid,"❌ Отмена",reply_markup=remove_kb()); ddel(uid,m.message_id,3)
        send_menu(uid); return
    m=bot.send_message(uid,"📅 <code>ДД.ММ.ГГГГ</code>\n<i>Пропустить (-), если нет</i>",parse_mode='HTML',reply_markup=input_kb(skip=True))
    set_ec(uid,{"state":"ct_date","ct_title":c.get("ct_title","?"),"ct_text":"" if t in ["-", "Пропустить (-)"] else t,"prompt_id":m.message_id,"msgs_to_del":[]})
    bot.register_next_step_handler(m, do_ct_date)

def do_ct_date(msg):
    uid=msg.chat.id; t=(msg.text or"").strip()
    c=edit_cache.get(uid,{}); sdel(uid,[msg.message_id, c.get("prompt_id")])
    if t == "Отмена":
        clear_ec(uid)
        m=bot.send_message(uid,"❌ Отмена",reply_markup=remove_kb()); ddel(uid,m.message_id,3)
        send_menu(uid); return
    ds=""
    if t and t not in ["-", "Пропустить (-)"]:
        try: datetime.strptime(t,"%d.%m.%Y"); ds=t
        except:
            m=bot.send_message(uid,"⚠️ Неверный формат даты!\nНужно: <b>ДД.ММ.ГГГГ</b> или пропустить.",parse_mode='HTML',reply_markup=input_kb(skip=True))
            c["prompt_id"]=m.message_id; bot.register_next_step_handler(m, do_ct_date); return
    ct={"title":c.get("ct_title","?"),"text":c.get("ct_text",""),"date":ds,"created":time.time()}
    with data_lock:
        if not isinstance(content_db.get("ct"),list): content_db["ct"]=[]
        content_db["ct"].append(ct); save_all("content",content_db)
    clear_ec(uid)
    m=bot.send_message(uid,f"✅ КТ <b>«{ct['title']}»</b>!",parse_mode='HTML',reply_markup=remove_kb())
    send_menu(uid); ddel(uid,m.message_id,3)

def dl_user(uid,mid):
    now=moscow()
    with data_lock: 
        dl=list(deadlines_db)
        hw_list = content_db.get("hw", [])

    # Объединяем ручные дедлайны и ДЗ с датами
    combined_dl = []
    
    # 1. Добавляем ручные
    for d in dl:
        combined_dl.append(d)
        
    # 2. Добавляем из ДЗ
    for h in hw_list:
        if h.get("date") and h.get("date") not in ["-", "Пропустить (-)"]:
            combined_dl.append({
                "title": f"📚 {h.get('subject')} - {h.get('title')}",
                "date": h.get("date"),
                "desc": "Автоматически из ДЗ",
                "is_hw": True,
                "id": h.get("id")
            })

    if not combined_dl: 
        txt="⏳ <b>Дедлайны</b>\n\nПусто 🎉"
    else:
        # Сортируем все по дате
        def parse_dl_date(d):
            try: return datetime.strptime(d.get("date"),"%d.%m.%Y")
            except: return datetime(2099,12,31)
            
        combined_dl.sort(key=parse_dl_date)
        
        txt="⏳ <b>ДЕДЛАЙНЫ:</b>\n\n"
        for d in combined_dl:
            try:
                dd=datetime.strptime(d["date"],"%d.%m.%Y"); delta=(dd-now.replace(hour=0,minute=0,second=0,microsecond=0)).days
                if delta<0: ic,st="⚫",f"просрочен {abs(delta)}д"
                elif delta==0: ic,st="🔴","СЕГОДНЯ!"
                elif delta==1: ic,st="🔴","завтра!"
                elif delta<=3: ic,st="🟠",f"{delta}д"
                elif delta<=7: ic,st="🟡",f"{delta}д"
                else: ic,st="🟢",f"{delta}д"
            except: ic,st="⚪","?"
            
            # Если это ДЗ, добавляем метку
            prefix = ""
            
            txt+=f"{ic} {prefix}<b>{d.get('title','?')}</b>\n   └ 📅 {d.get('date','?')} — {st}\n"
            if d.get("desc") and d.get("desc") != "Автоматически из ДЗ": 
                 txt+=f"   └ 📝 <i>{d['desc']}</i>\n"
            
            # Проверка статуса выполнения для ДЗ
            if d.get("is_hw"):
                is_done = d.get("id") in users_db.get(uid, {}).get("hw_done", [])
                status_line = "✅ Выполнено" if is_done else "⭕ Не выполнено"
                txt += f"   └ Статус: {status_line}\n"

            txt+="\n"
            
    mk=types.InlineKeyboardMarkup()
    mk.add(types.InlineKeyboardButton("⬅️",callback_data="back"))
    try: bot.edit_message_text(txt,uid,mid,reply_markup=mk,parse_mode='HTML')
    except: pass

def dl_editor(uid,mid):
    if not is_admin(uid): return
    mk=types.InlineKeyboardMarkup()
    mk.add(types.InlineKeyboardButton("➕",callback_data="dl_add"))
    mk.add(types.InlineKeyboardButton("🗑 Удалить",callback_data="dl_dlist"))
    mk.add(types.InlineKeyboardButton("🗑 Все",callback_data="dl_clr"))
    mk.add(types.InlineKeyboardButton("⬅️",callback_data="back"))
    try: bot.edit_message_text(f"⏳ <b>Дедлайны</b>\n{len(deadlines_db)}",uid,mid,reply_markup=mk,parse_mode='HTML')
    except: pass

def dl_act(call):
    uid=call.message.chat.id; mid=call.message.message_id; d=call.data
    if not is_admin(uid): return
    if d=="dl_add":
        sdel(uid,mid)
        m=bot.send_message(uid,"📝 <b>Название:</b>\n<i>Введите название...</i>",parse_mode='HTML',reply_markup=input_kb())
        set_ec(uid,{"state":"dl_title","prompt_id":m.message_id,"msgs_to_del":[]})
        bot.register_next_step_handler(m, do_dl_title)
    elif d=="dl_dlist":
        if not deadlines_db: return
        mk=types.InlineKeyboardMarkup()
        for i,dl in enumerate(deadlines_db): mk.add(types.InlineKeyboardButton(f"❌ {dl.get('title','?')} ({dl.get('date','')})",callback_data=f"dl_d_{i}"))
        mk.add(types.InlineKeyboardButton("⬅️",callback_data="a_dl"))
        try: bot.edit_message_text("🗑",uid,mid,reply_markup=mk,parse_mode='HTML')
        except: pass
    elif d.startswith("dl_d_") and d!="dl_dlist":
        idx=int(d[5:])
        with data_lock:
            if 0<=idx<len(deadlines_db): deadlines_db.pop(idx); save_all("deadlines",deadlines_db)
        dl_editor(uid,mid)
    elif d=="dl_clr":
        mk=types.InlineKeyboardMarkup()
        mk.add(types.InlineKeyboardButton("🔥",callback_data="dl_clrc"),types.InlineKeyboardButton("❌",callback_data="a_dl"))
        try: bot.edit_message_text("⚠️",uid,mid,reply_markup=mk,parse_mode='HTML')
        except: pass
    elif d=="dl_clrc":
        with data_lock: deadlines_db.clear(); save_all("deadlines",deadlines_db)
        dl_editor(uid,mid)

def do_dl_title(msg):
    uid=msg.chat.id; t=(msg.text or"").strip()
    c=edit_cache.get(uid,{}); sdel(uid,[msg.message_id, c.get("prompt_id")])
    if t == "Отмена":
        clear_ec(uid)
        m=bot.send_message(uid,"❌ Отмена",reply_markup=remove_kb()); ddel(uid,m.message_id,3)
        send_menu(uid); return
    if not t:
        m=bot.send_message(uid,"⚠️",reply_markup=input_kb())
        set_ec(uid,{"state":"dl_title","prompt_id":m.message_id,"msgs_to_del":[]})
        bot.register_next_step_handler(m, do_dl_title); return
    m=bot.send_message(uid,"📅 <code>ДД.ММ.ГГГГ</code>",parse_mode='HTML',reply_markup=input_kb())
    set_ec(uid,{"state":"dl_date","dl_title":t,"prompt_id":m.message_id,"msgs_to_del":[]})
    bot.register_next_step_handler(m, do_dl_date)

def do_dl_date(msg):
    uid=msg.chat.id; t=(msg.text or"").strip()
    c=edit_cache.get(uid,{}); sdel(uid,[msg.message_id, c.get("prompt_id")])
    if t == "Отмена":
        clear_ec(uid)
        m=bot.send_message(uid,"❌ Отмена",reply_markup=remove_kb()); ddel(uid,m.message_id,3)
        send_menu(uid); return
    try: datetime.strptime(t,"%d.%m.%Y")
    except:
        m=bot.send_message(uid,"⚠️ Формат:",parse_mode='HTML',reply_markup=input_kb())
        c["prompt_id"]=m.message_id; bot.register_next_step_handler(m, do_dl_date); return
    m=bot.send_message(uid,"📝 Описание (<code>-</code> пропуск)",parse_mode='HTML',reply_markup=input_kb(skip=True))
    set_ec(uid,{"state":"dl_desc","dl_title":c.get("dl_title","?"),"dl_date":t,"prompt_id":m.message_id,"msgs_to_del":[]})
    bot.register_next_step_handler(m, do_dl_desc)

def do_dl_desc(msg):
    uid=msg.chat.id; t=(msg.text or"").strip()
    c=edit_cache.get(uid,{}); sdel(uid,[msg.message_id, c.get("prompt_id")])
    if t == "Отмена":
        clear_ec(uid)
        m=bot.send_message(uid,"❌ Отмена",reply_markup=remove_kb()); ddel(uid,m.message_id,3)
        send_menu(uid); return
    dl={"title":c.get("dl_title","?"),"date":c.get("dl_date","?"),"desc":"" if t in ["-", "Пропустить (-)"] else t,"created":time.time()}
    with data_lock: deadlines_db.append(dl); save_all("deadlines",deadlines_db)
    clear_ec(uid)
    m=bot.send_message(uid,f"✅ <b>«{dl['title']}»</b>!",parse_mode='HTML',reply_markup=remove_kb())
    send_menu(uid); ddel(uid,m.message_id,3)

def poll_create(call):
    uid=call.message.chat.id; mid=call.message.message_id
    if not is_admin(uid): return
    mk=types.InlineKeyboardMarkup()
    mk.add(types.InlineKeyboardButton("🆕 Создать опрос",callback_data="pend_new"))
    active=[p for p in polls_db if p.get("active",True)]
    for p in active:
        mk.add(types.InlineKeyboardButton(f"🔴 Завершить: {p['question'][:25]}",callback_data=f"pend_end_{p['id']}"))
    mk.add(types.InlineKeyboardButton("⬅️",callback_data="back"))
    try: bot.edit_message_text("📊 <b>Опросы</b>",uid,mid,reply_markup=mk,parse_mode='HTML')
    except: pass

def poll_end(call):
    uid=call.message.chat.id; mid=call.message.message_id; d=call.data
    if not is_admin(uid): return
    if d=="pend_new":
        sdel(uid,mid)
        # Исправлен текст
        m=bot.send_message(uid,"📊 <b>Напишите тему опроса:</b>",parse_mode='HTML',reply_markup=input_kb())
        set_ec(uid,{"state":"poll_question","prompt_id":m.message_id,"msgs_to_del":[]})
        bot.register_next_step_handler(m, do_poll_q)
        return
    if d.startswith("pend_end_"):
        pid=d[9:]
        poll=None
        with data_lock:
            for p in polls_db:
                if p["id"]==pid: poll=p; break
            if poll:
                poll["active"]=False
                save_all("polls",polls_db)
        if poll:
            msg_ids = poll.get("messages", {})
            for u_id, m_id in msg_ids.items():
                try: bot.delete_message(u_id, m_id)
                except: pass
            result_text = fmt_poll_results(poll)
            with data_lock: uids=list(users_db.keys())
            for u in uids:
                try:
                    mk2=types.InlineKeyboardMarkup()
                    mk2.add(types.InlineKeyboardButton("🗑 Закрыть",callback_data=f"pdel_{pid}"))
                    bot.send_message(u,result_text,reply_markup=mk2,parse_mode='HTML')
                except: pass
        poll_create(call)

def poll_del(call):
    uid=call.message.chat.id; mid=call.message.message_id
    sdel(uid,mid)

def fmt_poll_results(poll):
    total=sum(len(v) for v in poll["options"].values())
    txt=f"📊 <b>РЕЗУЛЬТАТЫ:</b>\n❓ {poll['question']}\n\n"
    order=poll.get("options_order",list(poll["options"].keys()))
    for opt in order:
        cnt=len(poll["options"].get(opt,[])); pct=(cnt/total*100) if total>0 else 0
        bar="█"*int(pct/5)+"░"*(20-int(pct/5))
        txt+=f"{opt}: {cnt} ({pct:.0f}%)\n{bar}\n\n"
    txt+=f"Всего: {total}\n<i>Опрос завершён</i>"
    return txt

def do_poll_q(msg):
    uid=msg.chat.id; t=(msg.text or"").strip()
    c=edit_cache.get(uid,{}); sdel(uid,[msg.message_id, c.get("prompt_id")])
    if t == "Отмена":
        clear_ec(uid)
        m=bot.send_message(uid,"❌ Отмена",reply_markup=remove_kb()); ddel(uid,m.message_id,3)
        send_menu(uid); return
    if not t:
        m=bot.send_message(uid,"⚠️",reply_markup=input_kb())
        set_ec(uid,{"state":"poll_question","prompt_id":m.message_id,"msgs_to_del":[]})
        bot.register_next_step_handler(m, do_poll_q); return
    m=bot.send_message(uid,"📝 <b>Варианты</b> (каждый с новой строки):",parse_mode='HTML',reply_markup=input_kb())
    set_ec(uid,{"state":"poll_options","poll_q":t,"prompt_id":m.message_id,"msgs_to_del":[]})
    bot.register_next_step_handler(m, do_poll_opts)

def do_poll_opts(msg):
    uid=msg.chat.id; t=(msg.text or"").strip()
    c=edit_cache.get(uid,{}); sdel(uid,[msg.message_id, c.get("prompt_id")])
    if t == "Отмена":
        clear_ec(uid)
        m=bot.send_message(uid,"❌ Отмена",reply_markup=remove_kb()); ddel(uid,m.message_id,3)
        send_menu(uid); return
    opts=[o.strip() for o in t.split("\n") if o.strip()]
    if len(opts)<2:
        m=bot.send_message(uid,"⚠️ Минимум 2 варианта:",reply_markup=input_kb())
        c["prompt_id"]=m.message_id; bot.register_next_step_handler(m, do_poll_opts); return
    pid=f"p{int(time.time())}"
    poll={"id":pid,"question":c.get("poll_q","?"),"options":{o:[] for o in opts},"options_order":opts,"created":time.time(),"active":True, "messages":{}}
    with data_lock: polls_db.append(poll); save_all("polls",polls_db)
    clear_ec(uid)
    cnt=0
    with data_lock: uids=list(users_db.keys())
    for u in uids:
        try: send_poll(u,poll); cnt+=1
        except: pass
    with data_lock: save_all("polls",polls_db)
    m=bot.send_message(uid,f"✅ Опрос разослан: {cnt}",reply_markup=remove_kb())
    send_menu(uid); ddel(uid,m.message_id,3)

def send_poll(uid,poll):
    mk=types.InlineKeyboardMarkup()
    order=poll.get("options_order",list(poll["options"].keys()))
    for i,opt in enumerate(order):
        cnt=len(poll["options"].get(opt,[])); voted=uid in poll["options"].get(opt,[])
        pref="✅ " if voted else ""
        mk.add(types.InlineKeyboardButton(f"{pref}{opt} [{cnt}]",callback_data=f"pv_{poll['id']}_{i}"))
    mk.add(types.InlineKeyboardButton("📊 Результаты",callback_data=f"pr_{poll['id']}"))
    s=bot.send_message(uid,f"📊 <b>ОПРОС:</b>\n\n❓ {poll['question']}",reply_markup=mk,parse_mode='HTML')
    poll["messages"][str(uid)] = s.message_id

def poll_vote(call):
    uid=call.message.chat.id; mid=call.message.message_id; d=call.data
    if d.startswith("pv_"):
        p=d.split('_'); pid=p[1]
        try: oi=int(p[2])
        except: return
        with data_lock:
            poll=None
            for pp in polls_db:
                if pp["id"]==pid: poll=pp; break
            if not poll or not poll.get("active",True): return
            order=poll.get("options_order",list(poll["options"].keys()))
            if oi>=len(order): return
            opt=order[oi]
            already=uid in poll["options"].get(opt,[])
            for o in poll["options"]:
                if uid in poll["options"][o]: poll["options"][o].remove(uid)
            if not already: poll["options"][opt].append(uid)
            save_all("polls",polls_db)
        mk=types.InlineKeyboardMarkup()
        for i,o in enumerate(order):
            cnt=len(poll["options"].get(o,[])); voted=uid in poll["options"].get(o,[])
            mk.add(types.InlineKeyboardButton(f"{'✅ ' if voted else ''}{o} [{cnt}]",callback_data=f"pv_{pid}_{i}"))
        mk.add(types.InlineKeyboardButton("📊 Результаты",callback_data=f"pr_{pid}"))
        try: bot.edit_message_reply_markup(uid,mid,reply_markup=mk)
        except: pass
    elif d.startswith("pr_"):
        pid=d[3:]
        with data_lock:
            poll=None
            for pp in polls_db:
                if pp["id"]==pid: poll=pp; break
        if not poll: return
        total=sum(len(v) for v in poll["options"].values())
        txt=f"📊 {poll['question']}\n\n"
        for o in poll.get("options_order",list(poll["options"].keys())):
            cnt=len(poll["options"].get(o,[])); pct=(cnt/total*100) if total>0 else 0
            txt+=f"{o}: {cnt} ({pct:.0f}%)\n"
        txt+=f"\nВсего: {total}"
        try: bot.answer_callback_query(call.id,txt[:200],show_alert=True)
        except: pass

# ==========================================
# SETTINGS
# ==========================================
def settings(call):
    uid=call.message.chat.id; mid=call.message.message_id; d=call.data
    with data_lock:
        ensure_user(uid)
        if d=="opt_t": users_db[uid]['notify']=not users_db[uid]['notify']; save_all("users",users_db)
        elif d=="opt_m":
            cyc={5:10,10:30,30:60,60:5}; users_db[uid]['time']=cyc.get(users_db[uid]['time'],10); save_all("users",users_db)
        s=dict(users_db[uid])
    ni='✅' if s['notify'] else '❌'
    mk=types.InlineKeyboardMarkup()
    mk.add(types.InlineKeyboardButton(f"🔔 {ni}",callback_data="opt_t"),types.InlineKeyboardButton(f"⏳ {s['time']}мин",callback_data="opt_m"))
    mk.add(types.InlineKeyboardButton("🗑 Очистить чат",callback_data="set_clear_a"))
    mk.add(types.InlineKeyboardButton("🔄 Перезагрузить",callback_data="set_restart"))
    mk.add(types.InlineKeyboardButton("⬅️",callback_data="back"))
    try: bot.edit_message_text("⚙️ <b>Настройки</b>",uid,mid,reply_markup=mk,parse_mode='HTML')
    except: pass

def set_restart(uid,mid):
    sdel(uid,mid)
    send_menu(uid)

def set_clear(call):
    uid=call.message.chat.id; mid=call.message.message_id; d=call.data
    if d=="set_clear_a":
        mk=types.InlineKeyboardMarkup()
        mk.add(types.InlineKeyboardButton("🔥 Стереть всё",callback_data="set_clear_c"),types.InlineKeyboardButton("❌ Отмена",callback_data="m_set"))
        try: bot.edit_message_text("⚠️ <b>Очистить чат?</b>\nЭто удалит сообщения бота.",uid,mid,reply_markup=mk,parse_mode='HTML')
        except: pass
    elif d=="set_clear_c":
        with data_lock:
            br=users_db.get(uid,{}).get("broadcasts",[])
            sdel(uid,br)
            users_db[uid]["broadcasts"]=[]
            sdel(uid, users_db[uid].get("last_menu_id"))
            sdel(uid, users_db[uid].get("last_welcome_id"))
            users_db[uid]["last_menu_id"] = None
            users_db[uid]["last_welcome_id"] = None
            save_all("users",users_db)
        sdel(uid,mid)
        clear_ec(uid)
        send_menu(uid)

# ==========================================
# ABSENCE & SUGGESTIONS & FEEDBACK
# ==========================================
def absence(call):
    uid=call.message.chat.id; mid=call.message.message_id; d=call.data
    if d=="abs_m":
        mk=types.InlineKeyboardMarkup(row_width=2)
        for code,ru in DAYS_LIST[:6]: mk.add(types.InlineKeyboardButton(ru,callback_data=f"abs_d_{code}"))
        mk.add(types.InlineKeyboardButton("⬅️",callback_data="back"))
        try: bot.edit_message_text("📅 <b>День:</b>",uid,mid,reply_markup=mk,parse_mode='HTML')
        except: pass
    elif d.startswith("abs_d_"):
        dc=d[6:]
        set_ec(uid,{"state":"absence","abs":{"day":dc,"day_ru":DAYS_RU.get(dc,dc),"type":None,"pairs":[]},"msgs_to_del":[]})
        mk=types.InlineKeyboardMarkup()
        mk.add(types.InlineKeyboardButton("🏠 Весь день",callback_data="abs_tf"))
        mk.add(types.InlineKeyboardButton("🕒 Пары",callback_data="abs_tp"))
        mk.add(types.InlineKeyboardButton("⬅️",callback_data="abs_m"))
        try: bot.edit_message_text(f"🗓 <b>{DAYS_RU.get(dc,dc)}</b>:",uid,mid,reply_markup=mk,parse_mode='HTML')
        except: pass
    elif d=="abs_tf":
        c=edit_cache.get(uid,{})
        if "abs" not in c: send_menu(uid,mid); return
        c["abs"]["type"]="whole"; show_login(uid,mid)
    elif d=="abs_tp" or d.startswith("abs_p_"):
        c=edit_cache.get(uid,{})
        if "abs" not in c: send_menu(uid,mid); return
        if d.startswith("abs_p_"):
            p=int(d.split("_")[2]); pairs=c["abs"]["pairs"]
            if p in pairs: pairs.remove(p)
            else: pairs.append(p); pairs.sort()
        c["abs"]["type"]="part"; sel=c["abs"]["pairs"]
        mk=types.InlineKeyboardMarkup(row_width=3)
        for i in range(1,7): mk.add(types.InlineKeyboardButton(f"{i}✅" if i in sel else str(i),callback_data=f"abs_p_{i}"))
        if sel: mk.add(types.InlineKeyboardButton("✅ Ок",callback_data="abs_pc"))
        mk.add(types.InlineKeyboardButton("⬅️",callback_data=f"abs_d_{c['abs']['day']}"))
        try: bot.edit_message_text(f"🗓 <b>{c['abs']['day_ru']}</b>\nПары:",uid,mid,reply_markup=mk,parse_mode='HTML')
        except: pass
    elif d=="abs_pc":
        c=edit_cache.get(uid,{})
        if "abs" not in c: send_menu(uid,mid); return
        show_login(uid,mid)
    elif d.startswith("abs_l_"):
        c=edit_cache.get(uid,{})
        if "abs" not in c: send_menu(uid,mid); return
        ch=d.split("_")[2]; ab=c["abs"]
        with data_lock: un=users_db.get(uid,{}).get("name","?")
        info="Весь день" if ab["type"]=="whole" else ", ".join([f"{p}п" for p in ab["pairs"]])
        login="заходить" if ch=="y" else "не заходить"
        rec={"day":ab["day_ru"],"name":un,"info":info,"login":login,"timestamp":time.time()}
        with data_lock: absences_db.append(rec); save_all("absences",absences_db)
        for aid in ADMIN_IDS:
            try:
                am=bot.send_message(aid,f"🆕 <b>Отсутствие!</b>\n👤 {un}\n🗓 {ab['day_ru']}\n🕒 {info}\n🔑 {login}",parse_mode='HTML')
                with data_lock: ensure_user(aid); users_db[aid]["broadcasts"].append(am.message_id); save_all("users",users_db)
            except: pass
        edit_cache.pop(uid,None); send_menu(uid,mid)

def show_login(uid,mid):
    mk=types.InlineKeyboardMarkup()
    mk.add(types.InlineKeyboardButton("Да",callback_data="abs_l_y"),types.InlineKeyboardButton("Нет",callback_data="abs_l_n"))
    try: bot.edit_message_text("🤔 Зайти под вашим именем?",uid,mid,reply_markup=mk,parse_mode='HTML')
    except: pass

# --- FEEDBACK ---
def fb_start(call):
    uid=call.message.chat.id; sdel(uid,call.message.message_id)
    mk = types.InlineKeyboardMarkup()
    mk.add(types.InlineKeyboardButton("👤 От своего имени", callback_data="fb_mode_name"))
    mk.add(types.InlineKeyboardButton("🕵️ Анонимно", callback_data="fb_mode_anon"))
    mk.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="back"))
    m = bot.send_message(uid, "📤 <b>Как отправить сообщение?</b>", reply_markup=mk, parse_mode='HTML')

def fb_confirm_mode(call):
    uid = call.message.chat.id; mid = call.message.message_id
    is_anon = (call.data == "fb_mode_anon")
    sdel(uid, mid)
    
    label = "🕵️ <b>Анонимное сообщение:</b>" if is_anon else "👤 <b>Сообщение от вашего имени:</b>"
    m = bot.send_message(uid, f"{label}\nНапишите текст:", parse_mode='HTML', reply_markup=input_kb())
    
    set_ec(uid, {"state": "feedback", "prompt_id": m.message_id, "is_anon": is_anon, "msgs_to_del": []})
    bot.register_next_step_handler(m, do_fb)

def do_fb(msg):
    uid=msg.chat.id; t=(msg.text or"").strip()
    c=edit_cache.get(uid,{}); sdel(uid,[msg.message_id, c.get("prompt_id")])
    if t == "Отмена":
        clear_ec(uid)
        m=bot.send_message(uid,"❌ Отмена",reply_markup=remove_kb()); ddel(uid,m.message_id,3)
        send_menu(uid); return
    if not t:
        m=bot.send_message(uid,"⚠️ Пустое сообщение",reply_markup=input_kb())
        c["prompt_id"]=m.message_id; bot.register_next_step_handler(m, do_fb); return
    
    is_anon = c.get("is_anon", False)
    with data_lock: 
        real_name = users_db.get(uid,{}).get("name","Неизвестный")
    
    display_name = "Аноним" if is_anon else real_name
    
    rec={"uid":uid,"name":display_name,"text":t,"time":time.time()}
    with data_lock: feedback_db.append(rec); save_all("feedback",feedback_db)
    
    for aid in ADMIN_IDS:
        try:
            am=bot.send_message(aid,f"💬 <b>Новый отзыв!</b>\n👤 {display_name}\n📝 {t}",parse_mode='HTML')
            with data_lock: ensure_user(aid); users_db[aid]["broadcasts"].append(am.message_id); save_all("users",users_db)
        except: pass
    
    clear_ec(uid)
    m=bot.send_message(uid,"✅ Отправлено!",reply_markup=remove_kb())
    send_menu(uid); ddel(uid,m.message_id,3)

def fb_list(call):
    uid=call.message.chat.id; mid=call.message.message_id
    if not is_admin(uid): return
    if not feedback_db:
        mk=types.InlineKeyboardMarkup()
        mk.add(types.InlineKeyboardButton("⬅️",callback_data="back"))
        try: bot.edit_message_text("💬 <b>Отзывов нет</b>",uid,mid,reply_markup=mk,parse_mode='HTML')
        except: pass
        return
    
    txt="💬 <b>ОТЗЫВЫ:</b>\n\n"
    mk=types.InlineKeyboardMarkup()
    for i,f in enumerate(feedback_db):
        dt=fmt_ts(f.get("time",0))
        txt+=f"{i+1}. <b>{f.get('name','?')}</b> ({dt}):\n{f.get('text','')}\n\n"
        mk.add(types.InlineKeyboardButton(f"❌ Удалить #{i+1}",callback_data=f"fb_d_{i}"))
    mk.add(types.InlineKeyboardButton("🗑 Все",callback_data="fb_clr"))
    mk.add(types.InlineKeyboardButton("⬅️",callback_data="back"))
    try: bot.edit_message_text(txt,uid,mid,reply_markup=mk,parse_mode='HTML')
    except: pass

def fb_act(call):
    uid=call.message.chat.id; mid=call.message.message_id; d=call.data
    if not is_admin(uid): return
    if d.startswith("fb_d_"):
        idx=int(d[5:])
        with data_lock:
            if 0<=idx<len(feedback_db): feedback_db.pop(idx); save_all("feedback",feedback_db)
        fb_list(call)
    elif d=="fb_clr":
        with data_lock: feedback_db.clear(); save_all("feedback",feedback_db)
        fb_list(call)

# --- SUGGESTIONS ---
def sug_start(call):
    uid=call.message.chat.id; sdel(uid,call.message.message_id)
    m=bot.send_message(uid,
        "📬 <b>Предложка</b>\n\n"
        "Отправьте сообщение, файл, фото, видео.\n"
        "Когда закончите — нажмите <b>Готово</b>",parse_mode='HTML',reply_markup=input_kb(done=True))
    set_ec(uid,{"state":"suggestion","prompt_id":m.message_id,"msgs_to_del":[],"items":[]})
    bot.register_next_step_handler(m, do_sug)

def do_sug(msg):
    uid=msg.chat.id; c=edit_cache.get(uid)
    if not c or c.get("state")!="suggestion": return
    c["msgs_to_del"].append(msg.message_id)
    if msg.text == "Отмена":
        sdel(uid, [c.get("prompt_id")] + c.get("msgs_to_del"))
        clear_ec(uid)
        m=bot.send_message(uid,"❌ Отмена",reply_markup=remove_kb()); ddel(uid,m.message_id,3)
        send_menu(uid); return
    if msg.text == "Готово":
        items=c.get("items",[])
        sdel(uid, [c.get("prompt_id")] + c.get("msgs_to_del"))
        if not items:
            clear_ec(uid); m=bot.send_message(uid,"⚠️ Ничего не отправлено",reply_markup=remove_kb())
            send_menu(uid); ddel(uid,m.message_id,2); return
        with data_lock: name=users_db.get(uid,{}).get("name","Аноним")
        entry={"uid":uid,"name":name,"items":items,"timestamp":time.time()}
        with data_lock: suggestions_db.append(entry); save_all("suggestions",suggestions_db)
        for aid in ADMIN_IDS:
            try:
                am = bot.send_message(aid,f"📬 <b>Новое в предложке!</b>\nОт: {name}\nСообщений: {len(items)}",parse_mode='HTML')
                with data_lock: ensure_user(aid); users_db[aid]["broadcasts"].append(am.message_id); save_all("users", users_db)
            except: pass
        clear_ec(uid)
        m=bot.send_message(uid,f"✅ Отправлено ({len(items)} шт)",reply_markup=remove_kb())
        send_menu(uid); ddel(uid,m.message_id,3)
        return
    item={"type":"text","content":msg.text or "","file_id":None,"file_name":None,"caption":msg.caption or ""}
    if msg.document: item={"type":"document","file_id":msg.document.file_id,"file_name":msg.document.file_name,"caption":msg.caption or ""}
    elif msg.photo: item={"type":"photo","file_id":msg.photo[-1].file_id,"caption":msg.caption or ""}
    elif msg.video: item={"type":"video","file_id":msg.video.file_id,"file_name":msg.video.file_name or "video","caption":msg.caption or ""}
    elif msg.audio: item={"type":"audio","file_id":msg.audio.file_id,"file_name":msg.audio.file_name or "audio","caption":msg.caption or ""}
    c["items"].append(item)
    reply=bot.send_message(uid,f"📎 +1 ({len(c['items'])} всего). Ещё или <b>Готово</b>",parse_mode='HTML',reply_markup=input_kb(done=True))
    c["msgs_to_del"].append(reply.message_id)
    bot.register_next_step_handler(reply, do_sug)

def sug_admin(call):
    uid=call.message.chat.id; mid=call.message.message_id
    if not is_admin(uid): return
    if not suggestions_db:
        mk=types.InlineKeyboardMarkup()
        mk.add(types.InlineKeyboardButton("⬅️",callback_data="back"))
        try: bot.edit_message_text("📬 <b>Предложка пуста</b>",uid,mid,reply_markup=mk,parse_mode='HTML')
        except: pass
        return
    users_map={}
    for i,s in enumerate(suggestions_db):
        key=s.get("uid",0)
        if key not in users_map: users_map[key]={"name":s.get("name","?"),"indices":[]}
        users_map[key]["indices"].append(i)
    mk=types.InlineKeyboardMarkup()
    for ukey,info in users_map.items():
        cnt=len(info["indices"])
        mk.add(types.InlineKeyboardButton(f"👤 {info['name']} [{cnt}]",callback_data=f"sg_u_{ukey}"))
    mk.add(types.InlineKeyboardButton("🗑 Очистить всё",callback_data="sg_clr"))
    mk.add(types.InlineKeyboardButton("⬅️",callback_data="back"))
    try: bot.edit_message_text(f"📬 <b>Предложка</b>\nОтправителей: {len(users_map)}",uid,mid,reply_markup=mk,parse_mode='HTML')
    except: pass

def sug_act(call):
    uid=call.message.chat.id; mid=call.message.message_id; d=call.data
    if not is_admin(uid): return
    
    c = get_ec(uid)
    if "view_msgs" in c:
        sdel(uid, c["view_msgs"])
        c["view_msgs"] = []
    set_ec(uid, c)

    if d.startswith("sg_u_"):
        target_uid=int(d[5:])
        entries=[s for s in suggestions_db if s.get("uid")==target_uid]
        if not entries: return
        name=entries[0].get("name","?")
        sdel(uid,mid)
        
        sent_msgs = []
        m = bot.send_message(uid,f"📬 <b>Сообщения от {name}:</b>",parse_mode='HTML')
        sent_msgs.append(m.message_id)
        
        for entry in entries:
            dt_str = fmt_ts(entry.get("timestamp", 0))
            m = bot.send_message(uid,f"⏰ {dt_str}",parse_mode='HTML')
            sent_msgs.append(m.message_id)
            for item in entry.get("items",[]):
                try: 
                    m = send_sug_item_msg(uid, item)
                    if m: sent_msgs.append(m.message_id)
                except Exception as e: bot.send_message(uid,f"⚠️ Ошибка: {e}")

        c["view_msgs"] = sent_msgs
        set_ec(uid, c)

        mk=types.InlineKeyboardMarkup()
        mk.add(types.InlineKeyboardButton(f"🗑 Очистить от {name}",callback_data=f"sg_du_{target_uid}"))
        mk.add(types.InlineKeyboardButton("⬅️ К предложке",callback_data="a_sug"))
        mk.add(types.InlineKeyboardButton("🏠 Меню",callback_data="back"))
        bot.send_message(uid,"👆 Все сообщения выше",reply_markup=mk,parse_mode='HTML')

    elif d.startswith("sg_du_"):
        target_uid=int(d[6:])
        with data_lock:
            suggestions_db[:] = [s for s in suggestions_db if s.get("uid")!=target_uid]
            save_all("suggestions",suggestions_db)
        
        c = get_ec(uid)
        if "view_msgs" in c: 
            sdel(uid, c["view_msgs"])
            c["view_msgs"] = [] 
        
        m = bot.send_message(uid,"✅ Сообщения удалены")
        ddel(uid, m.message_id, 2)
        sug_admin(call)

    elif d=="sg_clr":
        mk=types.InlineKeyboardMarkup()
        mk.add(types.InlineKeyboardButton("🔥 Да",callback_data="sg_clrc"),types.InlineKeyboardButton("❌",callback_data="a_sug"))
        try: bot.edit_message_text("⚠️ Очистить всю предложку?",uid,mid,reply_markup=mk,parse_mode='HTML')
        except: pass

    elif d=="sg_clrc":
        with data_lock: suggestions_db.clear(); save_all("suggestions",suggestions_db)
        m=bot.send_message(uid,"✅ Очищено")
        send_menu(uid); ddel(uid,m.message_id,2)

def send_sug_item_msg(uid, item):
    t=item.get("type","text"); fid=item.get("file_id"); cap=item.get("caption","")
    if t=="text": return bot.send_message(uid, item.get("content",""))
    elif t=="photo": return bot.send_photo(uid, fid, caption=cap)
    elif t=="video": return bot.send_video(uid, fid, caption=cap)
    elif t=="document": return bot.send_document(uid, fid, caption=cap)
    elif t=="audio": return bot.send_audio(uid, fid, caption=cap)
    return None

def admin_act(call):
    uid=call.message.chat.id; mid=call.message.message_id; d=call.data
    if d=="a_abs": show_abs(uid,mid)
    elif d=="a_abs_clr":
        with data_lock: absences_db.clear(); save_all("absences",absences_db)
        show_abs(uid,mid)
    elif d=="a_bcast":
        sdel(uid,mid)
        m=bot.send_message(uid,"📝 <b>Рассылка:</b>\n<i>Введите текст или перешлите сообщение...</i>",parse_mode='HTML',reply_markup=input_kb())
        set_ec(uid,{"state":"broadcast","admin_prompt_id":m.message_id,"msgs_to_del":[]})
        bot.register_next_step_handler(m, do_bcast)

def show_abs(uid,mid):
    if not absences_db:
        txt="📋 <b>Пусто</b>"
        mk=types.InlineKeyboardMarkup()
        mk.add(types.InlineKeyboardButton("⬅️",callback_data="back"))
    else:
        txt="📋 <b>ОТСУТСТВУЮЩИЕ:</b>\n\n"
        sa=sorted(absences_db,key=lambda x:(DAY_SORT.get(x.get('day',''),7),x.get('timestamp',0)))
        for r in sa:
            ic="🟢" if r.get('login')=="заходить" else "🔴"
            txt+=f"🗓 <b>{r.get('day','?')}</b> — {r.get('name','?')}\n   └ {r.get('info','?')} ({ic} {r.get('login','?')})\n\n"
        mk=types.InlineKeyboardMarkup()
        mk.add(types.InlineKeyboardButton("🗑",callback_data="a_abs_clr"))
        mk.add(types.InlineKeyboardButton("⬅️",callback_data="back"))
    try: bot.edit_message_text(txt,uid,mid,reply_markup=mk,parse_mode='HTML')
    except: pass

def do_bcast(msg):
    uid=msg.chat.id; t=(msg.text or"").strip()
    c=edit_cache.get(uid,{}); pid=c.get("admin_prompt_id")
    sdel(uid, [msg.message_id, pid])
    if t == "Отмена":
        clear_ec(uid)
        m=bot.send_message(uid,"❌ Отмена",reply_markup=remove_kb()); ddel(uid,m.message_id,3)
        send_menu(uid); return
    clear_ec(uid)
    st=bot.send_message(uid,"📢 Рассылка началась...",reply_markup=remove_kb())
    cnt=0
    with data_lock: uids=list(users_db.keys())
    for u in uids:
        try:
            s=bot.copy_message(u,uid,msg.message_id); cnt+=1
            with data_lock: ensure_user(u); users_db[u]["broadcasts"].append(s.message_id)
        except: pass
    with data_lock: save_all("users",users_db)
    fin=bot.send_message(uid,f"✅ Рассылка завершена: {cnt} чел.")
    send_menu(uid); ddel(uid,[st.message_id,fin.message_id],3)

@bot.message_handler(content_types=['text','photo','video','document','audio','voice','video_note','sticker'])
def echo(msg):
    uid=msg.chat.id
    if active_input(uid): return
    sdel(uid,msg.message_id)

def notif_loop():
    print("[INFO] Notifications started")
    global sent_notifications
    last_min=None
    while True:
        try:
            now=moscow(); cm=(now.year,now.month,now.day,now.hour,now.minute)
            if cm==last_min: time.sleep(5); continue
            last_min=cm; de=now.strftime("%A"); ts=now.strftime("%Y-%m-%d")
            sent_notifications-={k for k in sent_notifications if not k.startswith(ts)}
            stale=[u for u,c in edit_cache.items() if time.time()-c.get("_ts",0)>EDIT_CACHE_TIMEOUT]
            for u in stale: clear_ec(u)
            with data_lock: lessons=list(content_db.get("schedule",{}).get(de,[])); uids=list(users_db.keys())
            if lessons:
                ch=False
                for l in lessons:
                    tss=l.get('start_clean') or l['time'].split("-")[0].strip()
                    try: h,m=map(int,tss.split(":"))
                    except: continue
                    ls=now.replace(hour=h,minute=m,second=0,microsecond=0)
                    ln=l.get('name','Пара'); lt=f"\n🔗 <a href='{l['link']}'>Ссылка</a>" if l.get('link') else ""
                    for u in uids:
                        with data_lock:
                            us=users_db.get(u)
                            if not us or not us.get('notify'): continue
                            ut=us.get('time',10)
                        rt=ls-timedelta(minutes=ut)
                        kb=f"{ts}_{u}_{h}:{m}_b"; ks=f"{ts}_{u}_{h}:{m}_s"
                        if now.hour==rt.hour and now.minute==rt.minute and kb not in sent_notifications:
                            try:
                                sm=bot.send_message(u,f"⏰ <b>Через {ut} мин!</b>\n{ln}{lt}",parse_mode='HTML',disable_web_page_preview=True)
                                with data_lock: ensure_user(u); users_db[u]["broadcasts"].append(sm.message_id); ch=True
                            except: pass
                            sent_notifications.add(kb)
                        if now.hour==h and now.minute==m and ks not in sent_notifications:
                            try:
                                sm=bot.send_message(u,f"🔔 <b>Началась!</b>\n{ln}{lt}",parse_mode='HTML',disable_web_page_preview=True)
                                with data_lock: ensure_user(u); users_db[u]["broadcasts"].append(sm.message_id); ch=True
                            except: pass
                            sent_notifications.add(ks)
                if ch:
                    with data_lock: save_all("users",users_db)
            if now.hour==9 and now.minute==0: check_dl(ts)
            time.sleep(max(1,60-datetime.utcnow().second))
        except Exception as e: print(f"[ERR] notif: {e}"); traceback.print_exc(); time.sleep(10)

def check_dl(ts):
    key=f"{ts}_dl"
    if key in sent_notifications: return
    sent_notifications.add(key); now=moscow(); alerts=[]
    for d in deadlines_db:
        try:
            dd=datetime.strptime(d["date"],"%d.%m.%Y"); delta=(dd-now.replace(hour=0,minute=0,second=0,microsecond=0)).days
            if delta==0: alerts.append(f"🔴 <b>{d['title']}</b> — СЕГОДНЯ!")
            elif delta==1: alerts.append(f"🟠 <b>{d['title']}</b> — завтра!")
            elif delta==3: alerts.append(f"🟡 <b>{d['title']}</b> — через 3 дня")
        except: continue
    if not alerts: return
    txt="⏳ <b>ДЕДЛАЙНЫ:</b>\n\n"+"\n".join(alerts)
    with data_lock: uids=list(users_db.keys())
    ch=False
    for u in uids:
        with data_lock:
            if not users_db.get(u,{}).get('notify'): continue
        try:
            sm=bot.send_message(u,txt,parse_mode='HTML')
            with data_lock: ensure_user(u); users_db[u]["broadcasts"].append(sm.message_id); ch=True
        except: pass
    if ch:
        with data_lock: save_all("users",users_db)

if __name__=="__main__":
    print("[INFO] Bot starting...")
    threading.Thread(target=notif_loop,daemon=True).start()
    while True:
        try: print("[INFO] Polling"); bot.infinity_polling(timeout=60,long_polling_timeout=30)
        except Exception as e: print(f"[ERR] {e}"); traceback.print_exc(); time.sleep(5)
