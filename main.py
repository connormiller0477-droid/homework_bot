import os
import sqlite3
from datetime import datetime, timedelta
import telebot
from telebot import types
import numpy as np
import cv2

# Импортируем официальную библиотеку Google GenAI
from google import genai
from google.genai import types as genai_types

# Токен твоего Telegram-бота
TOKEN = "8797963662:AAGi6DZhW6Fl3bWwGMELIluOsx7F0xw0JdI"
bot = telebot.TeleBot(TOKEN)

# Инициализируем клиент Gemini API
client = genai.Client(api_key="AQ.Ab8RN6KyYBSiDAwgnIZ5s0-_pm-OFBYH-6RyyDo7ucKGEgz0fg")

DB_FILE = "homework.db"

subjects_list = [
    "Алгебра",
    "Биология",
    "Вероятность и статистика",
    "География",
    "Геометрия",
    "Английский язык",
    "Информатика",
    "История",
    "Литература",
    "Обществознание",
    "ОБЗР",
    "Проектная деятельность",
    "Русский язык",
    "Технология",
    "Физика",
    "Физра",
    "Химия",
]


def parse_flexible_date(date_text):
    """Превращает даты вида 9.9.2026, 09.9.2026, 9.9 или 09.09.2026 в объект date."""
    date_text = date_text.strip()
    current_year = datetime.now().year
    parts = date_text.split(".")
    if len(parts) == 2:
        day, month = parts
        formatted_str = f"{day.zfill(2)}.{month.zfill(2)}.{current_year}"
        return datetime.strptime(formatted_str, "%d.%m.%Y").date()
    elif len(parts) == 3:
        day, month, year = parts
        if len(year) == 2:
            year = "20" + year
        formatted_str = f"{day.zfill(2)}.{month.zfill(2)}.{year}"
        return datetime.strptime(formatted_str, "%d.%m.%Y").date()
    else:
        raise ValueError("Неверный формат даты")


def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS homeworks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT,
            date TEXT,
            text TEXT,
            file_id TEXT,
            file_type TEXT
        )
    """)
    conn.commit()
    conn.close()


init_db()


def load_global_homeworks():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT subject, date, text, file_id, file_type FROM homeworks")
    rows = cursor.fetchall()
    conn.close()

    extended_subjects = list(subjects_list)
    extended_subjects.extend([
        "Английский язык (Елена Николаевна)",
        "Английский язык (Лариса Николаевна)",
    ])

    storage = {sub: [] for sub in extended_subjects}
    for subj, date, text, file_id, file_type in rows:
        if subj in storage:
            storage[subj].append({
                "date": date,
                "text": text,
                "file_id": file_id,
                "file_type": file_type,
            })
    return storage


def add_homework_to_db(subject, date_val, text_val, file_id=None, file_type=None):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO homeworks (subject, date, text, file_id, file_type) VALUES (?, ?, ?, ?, ?)",
        (subject, date_val, text_val, file_id, file_type),
    )
    conn.commit()
    conn.close()


def delete_homework_from_db(subject, date_val, text_val):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM homeworks WHERE subject = ? AND date = ? AND text = ?",
        (subject, date_val, text_val),
    )
    conn.commit()
    conn.close()


homework_storage = load_global_homeworks()
user_data = {}


def init_user(user_id):
    if user_id not in user_data:
        extended_subjects = list(subjects_list)
        extended_subjects.extend([
            "Английский язык (Елена Николаевна)",
            "Английский язык (Лариса Николаевна)",
        ])

        user_data[user_id] = {
            "active": {sub: list(homework_storage.get(sub, [])) for sub in extended_subjects},
            "completed": {sub: [] for sub in extended_subjects},
            "current_msg_id": None,
            "target_subject": None,
            "step": None,
            "temp_date": None,
            "eng_group": None,
            "ocr_photos": [],
            "ocr_parsed_tasks": [],
            "editing_task_idx": None,
        }


def clean_old_homeworks(user_id):
    now = datetime.now()
    extended_subjects = list(subjects_list)
    extended_subjects.extend([
        "Английский язык (Елена Николаевна)",
        "Английский язык (Лариса Николаевна)",
    ])

    for state_type in ["active", "completed"]:
        for subj in extended_subjects:
            filtered_tasks = []
            for t_info in user_data[user_id][state_type][subj]:
                try:
                    task_date = parse_flexible_date(t_info["date"])
                    limit_time = datetime.combine(task_date, datetime.min.time()) + timedelta(hours=4)
                    if now < limit_time:
                        filtered_tasks.append(t_info)
                except ValueError:
                    filtered_tasks.append(t_info)
            user_data[user_id][state_type][subj] = filtered_tasks

    for subj in extended_subjects:
        filtered_global = []
        for t_info in homework_storage[subj]:
            try:
                task_date = parse_flexible_date(t_info["date"])
                limit_time = datetime.combine(task_date, datetime.min.time()) + timedelta(hours=4)
                if now < limit_time:
                    filtered_global.append(t_info)
                else:
                    delete_homework_from_db(subj, t_info["date"], t_info["text"])
            except ValueError:
                filtered_global.append(t_info)
        homework_storage[subj] = filtered_global


def analyze_images_with_gemini(photo_bytes_list):
    """Отправляем скриншоты в Gemini для интеллектуального извлечения домашнего задания."""
    contents = []

    for b in photo_bytes_list:
        contents.append(
            genai_types.Part.from_bytes(
                data=b,
                mime_type="image/jpeg",
            )
        )

    prompt = f"""
    Проанализируй скриншоты школьного электронного дневника. 
    Найди все домашние задания, указанные на них.
    Доступные предметы: {", ".join(subjects_list)}.

    Для каждого задания определи:
    1. Точное название предмета из списка выше.
    2. Дату выполнения/сдачи в формате ДД.ММ.ГГГГ (текущий год 2026). Если дата написана как "19 октября", переведи её в 19.10.2026.
    3. Полный текст домашнего задания.

    Верни ответ СТРОГО в виде списка словарей Python (без лишнего текста и markdown-оберток вроде ```python):
    [
      {{"subject": "Физика", "date": "19.10.2026", "text": "Упр. 9 (1-5)"}},
      {{"subject": "Русский язык", "date": "19.10.2026", "text": "П.10, выучить правила"}}
    ]
    Если заданий не найдено, верни пустой список: []
    """
    contents.append(prompt)

    try:
        response = client.models.generate_content(
            model='gemini-3.8-flash',
            contents=contents,
        )

        cleaned_text = response.text.strip().replace("```python", "").replace("```", "").strip()
        tasks = eval(cleaned_text)
        if isinstance(tasks, list):
            return tasks
    except Exception as e:
        print(f"Ошибка при запросе к Gemini API: {e}")

    return []


def show_ocr_results(chat_id, message_id, user_id):
    parsed_tasks = user_data[user_id].get("ocr_parsed_tasks", [])
    markup = types.InlineKeyboardMarkup()

    if parsed_tasks:
        text = "🤖 **Нейросеть проанализировала скриншоты и нашла задания:**\n\n"
        for idx, item in enumerate(parsed_tasks):
            text += f"<b>{idx + 1}. Предмет:</b> {item['subject']}\n"
            text += f"  <b>Дата:</b> {item['date']}\n"
            text += f"  <b>Задание:</b> {item['text']}\n\n"
            markup.row(types.InlineKeyboardButton(f"✏️ Изменить текст #{idx + 1}", callback_data=f"edit_ocr_{idx}"))

        text += "Всё верно? Нажми кнопку ниже, чтобы автоматически занести их в базу."
        markup.row(types.InlineKeyboardButton("✅ Подтвердить и сохранить", callback_data="confirm_ocr_save"))
    else:
        text = "❌ Нейросеть не смогла обнаружить задания на скриншотах. Попробуй добавить ДЗ вручную через меню."

    markup.row(types.InlineKeyboardButton("🏠 На главную", callback_data="go_home"))

    try:
        bot.edit_message_text(text, chat_id, message_id, parse_mode="HTML", reply_markup=markup)
    except Exception:
        msg = bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup)
        user_data[user_id]["current_msg_id"] = msg.message_id


def get_welcome_markup():
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn1 = types.InlineKeyboardButton("Всё Д/З", callback_data="btn_all_hw")
    btn2 = types.InlineKeyboardButton("Д/З на завтра", callback_data="btn_tomorrow")
    btn_done = types.InlineKeyboardButton("Выполненное Д/З", callback_data="btn_done")
    markup.add(btn1, btn2)
    markup.add(btn_done)
    return markup


@bot.message_handler(commands=["start"])
def send_welcome(message):
    user_id = message.from_user.id
    init_user(user_id)
    clean_old_homeworks(user_id)
    user_data[user_id]["target_subject"] = None
    user_data[user_id]["step"] = None
    user_data[user_id]["temp_date"] = None
    user_data[user_id]["editing_task_idx"] = None
    user_data[user_id]["ocr_photos"] = []

    msg = bot.send_message(
        message.chat.id,
        "Добро пожаловать!👋\n\nЭто проводник по домашнему заданию. Что тебя интересует?📚",
        reply_markup=get_welcome_markup(),
    )
    user_data[user_id]["current_msg_id"] = msg.message_id


@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    user_id = call.from_user.id
    init_user(user_id)
    clean_old_homeworks(user_id)
    chat_id = call.message.chat.id
    message_id = call.message.message_id

    if (
            not call.data.startswith("done_")
            and not call.data.startswith("undone_")
            and not call.data.startswith("sub_")
            and not call.data.startswith("del_")
            and not call.data.startswith("set_eng_")
            and not call.data.startswith("show_file_")
            and not call.data.startswith("file_done_")
            and not call.data.startswith("edit_ocr_")
            and call.data not in ["start_ocr_process", "confirm_ocr_save"]
    ):
        user_data[user_id]["target_subject"] = None
        user_data[user_id]["step"] = None
        user_data[user_id]["temp_date"] = None
        user_data[user_id]["editing_task_idx"] = None

    if call.data.startswith("edit_ocr_"):
        bot.answer_callback_query(call.id)
        idx = int(call.data.replace("edit_ocr_", ""))
        user_data[user_id]["editing_task_idx"] = idx
        user_data[user_id]["step"] = "editing_ocr_text"

        task = user_data[user_id]["ocr_parsed_tasks"][idx]
        markup = types.InlineKeyboardMarkup()
        markup.row(types.InlineKeyboardButton("❌ Отмена", callback_data="back_to_ocr_results"))

        prompt_text = (
            f"✏️ <b>Редактирование задания #{idx + 1} ({task['subject']})</b>\n\n"
            f"Текущий текст:\n<i>{task['text']}</i>\n\n"
            "Отправь новый текст для этого задания:"
        )
        bot.edit_message_text(prompt_text, chat_id, message_id, parse_mode="HTML", reply_markup=markup)
        return

    if call.data == "back_to_ocr_results":
        bot.answer_callback_query(call.id)
        user_data[user_id]["step"] = None
        user_data[user_id]["editing_task_idx"] = None
        show_ocr_results(chat_id, message_id, user_id)
        return

    if call.data.startswith("show_file_"):
        bot.answer_callback_query(call.id, "Открываю файл...")
        parts = call.data.replace("show_file_", "").rsplit("_", 1)
        extended_subjects = list(subjects_list)
        extended_subjects.extend([
            "Английский язык (Елена Николаевна)",
            "Английский язык (Лариса Николаевна)",
        ])

        if len(parts) == 2:
            try:
                subj_idx = int(parts[0])
                idx = int(parts[1])
                subj = extended_subjects[subj_idx]
                task_info = user_data[user_id]["active"][subj][idx]

                file_id = task_info.get("file_id")
                file_type = task_info.get("file_type")

                caption = f"Предмет: {subj}\nДата: {task_info['date']}\nЗадание: {task_info['text']}"

                short_subj = subj.replace("Английский язык", "Англ.")
                btn_done = types.InlineKeyboardButton(f"✅ Сделано ({short_subj})",
                                                      callback_data=f"file_done_{subj_idx}_{idx}")
                btn_back = types.InlineKeyboardButton("🔙 К списку Д/З", callback_data="btn_all_hw")

                markup = types.InlineKeyboardMarkup()
                markup.row(btn_done, btn_back)

                try:
                    bot.delete_message(chat_id, message_id)
                except Exception:
                    pass

                if file_id and file_type:
                    if file_type == "photo":
                        msg = bot.send_photo(chat_id, file_id, caption=caption, reply_markup=markup)
                    elif file_type == "document":
                        msg = bot.send_document(chat_id, file_id, caption=caption, reply_markup=markup)
                    elif file_type == "video":
                        msg = bot.send_video(chat_id, file_id, caption=caption, reply_markup=markup)
                    user_data[user_id]["current_msg_id"] = msg.message_id
            except Exception:
                pass
        return

    if call.data.startswith("file_done_"):
        bot.answer_callback_query(call.id, "Задание выполнено! ✅")
        parts = call.data.replace("file_done_", "").rsplit("_", 1)
        extended_subjects = list(subjects_list)
        extended_subjects.extend([
            "Английский язык (Елена Николаевна)",
            "Английский язык (Лариса Николаевна)",
        ])

        if len(parts) == 2:
            try:
                subj_idx = int(parts[0])
                idx = int(parts[1])
                subj = extended_subjects[subj_idx]
                active_list = user_data[user_id]["active"][subj]
                if idx < len(active_list):
                    task_info = active_list.pop(idx)
                    user_data[user_id]["completed"][subj].append(task_info)
            except ValueError:
                pass

        try:
            bot.delete_message(chat_id, message_id)
        except Exception:
            pass

        call.data = "btn_all_hw"
        callback_query(call)
        return

    if call.data == "starosta_ocr_mode":
        bot.answer_callback_query(call.id)
        user_data[user_id]["step"] = "collecting_ocr_photos"
        user_data[user_id]["ocr_photos"] = []
        user_data[user_id]["ocr_parsed_tasks"] = []
        user_data[user_id]["editing_task_idx"] = None

        markup = types.InlineKeyboardMarkup()
        markup.row(types.InlineKeyboardButton("🏠 На главную", callback_data="go_home"))

        text = (
            "📸 Нейро-сканер ДЗ\n\n"
            "Присылай скриншоты дневника (можно пачкой).\n"
            "Когда отправишь всё, нажми кнопку ниже для анализа нейросетью."
        )
        bot.edit_message_text(text, chat_id, message_id, reply_markup=markup)
        return

    if call.data == "start_ocr_process":
        bot.answer_callback_query(call.id, "Запускаю нейросеть...")
        bot.edit_message_text("⏳ Нейросеть изучает скриншоты... Это займет несколько секунд.", chat_id, message_id)

        photo_bytes_list = user_data[user_id].get("ocr_photos", [])
        parsed_tasks = analyze_images_with_gemini(photo_bytes_list)

        user_data[user_id]["ocr_parsed_tasks"] = parsed_tasks

        show_ocr_results(chat_id, message_id, user_id)
        return

    if call.data == "confirm_ocr_save":
        tasks_to_add = user_data[user_id].get("ocr_parsed_tasks", [])
        if not tasks_to_add:
            bot.answer_callback_query(call.id, "Нет заданий для сохранения!")
            return

        for t in tasks_to_add:
            subject = t["subject"]
            date_val = t["date"]
            text_val = t["text"]

            add_homework_to_db(subject, date_val, text_val)
            task_info = {"date": date_val, "text": text_val, "file_id": None, "file_type": None}
            homework_storage[subject].append(task_info)
            for uid in user_data:
                user_data[uid]["active"][subject].append(task_info)

        user_data[user_id]["ocr_parsed_tasks"] = []
        user_data[user_id]["ocr_photos"] = []  # Очищаем загруженные фото после сохранения
        bot.answer_callback_query(call.id, "Задания успешно сохранены! 🎉")

        markup = types.InlineKeyboardMarkup()
        markup.row(types.InlineKeyboardButton("🏠 На главную", callback_data="go_home"))
        bot.edit_message_text(
            f"✅ Успешно добавлено заданий: {len(tasks_to_add)}!\n\nВсе ученики уже видят обновлённое ДЗ.", chat_id,
            message_id, reply_markup=markup)
        return

    if call.data.startswith("set_eng_"):
        bot.answer_callback_query(call.id, "Группа сохранена! ✅")
        teacher = call.data.replace("set_eng_", "")
        user_data[user_id]["eng_group"] = teacher
        bot.edit_message_text(
            f"🇬🇧 Отлично! Твоя группа по английскому: {teacher}.\n\nТеперь выбери нужное действие:",
            chat_id,
            message_id,
            reply_markup=get_welcome_markup(),
        )
        return

    if call.data == "go_home":
        bot.answer_callback_query(call.id)
        user_data[user_id]["ocr_photos"] = []  # Очищаем буфер фото при возврате
        try:
            bot.edit_message_text(
                "Добро пожаловать!👋\n\nЭто проводник по домашнему заданию. Что тебя интересует?📚",
                chat_id,
                message_id,
                reply_markup=get_welcome_markup(),
            )
        except Exception:
            try:
                bot.delete_message(chat_id, message_id)
            except Exception:
                pass
            msg = bot.send_message(
                chat_id,
                "Добро пожаловать!👋\n\nЭто проводник по домашнему заданию. Что тебя интересует?📚",
                reply_markup=get_welcome_markup(),
            )
            user_data[user_id]["current_msg_id"] = msg.message_id

    elif call.data == "btn_tomorrow":
        if user_data[user_id]["eng_group"] is None:
            bot.answer_callback_query(call.id)
            markup = types.InlineKeyboardMarkup()
            markup.row(
                types.InlineKeyboardButton("👩‍🏫 Елена Николаевна", callback_data="set_eng_Елена Николаевна"),
                types.InlineKeyboardButton("👩‍🏫 Лариса Николаевна", callback_data="set_eng_Лариса Николаевна")
            )
            markup.row(types.InlineKeyboardButton("🏠 На главную", callback_data="go_home"))
            bot.edit_message_text(
                "🇬🇧 Укажи свою группу по английскому языку перед просмотром ДЗ:",
                chat_id,
                message_id,
                reply_markup=markup,
            )
            return

        bot.answer_callback_query(call.id)
        extended_subjects = list(subjects_list)
        extended_subjects.extend([
            "Английский язык (Елена Николаевна)",
            "Английский язык (Лариса Николаевна)",
        ])

        for subj in extended_subjects:
            global_tasks = homework_storage[subj]
            user_active = user_data[user_id]["active"][subj]
            user_completed = user_data[user_id]["completed"][subj]
            for task in global_tasks:
                if task not in user_active and task not in user_completed:
                    user_active.append(task)
        clean_old_homeworks(user_id)

        tomorrow_date_obj = datetime.now().date() + timedelta(days=1)
        user_group = user_data[user_id]["eng_group"]

        text = "📌 Домашняя работа на завтра:\n\n"
        markup = types.InlineKeyboardMarkup()
        has_tasks = False

        for subj, tasks in user_data[user_id]["active"].items():
            if subj.startswith("Английский язык") and subj != f"Английский язык ({user_group})":
                continue
            for i, t_info in enumerate(tasks):
                try:
                    task_date_obj = parse_flexible_date(t_info["date"])
                    is_tomorrow = task_date_obj == tomorrow_date_obj
                except ValueError:
                    is_tomorrow = False

                if is_tomorrow or t_info["date"].strip().lower() in ["завтра"]:
                    has_tasks = True
                    subj_idx = extended_subjects.index(subj)
                    text += f"🔹 Предмет: {subj}\n"
                    text += f"📅 Дата: {t_info['date']}\n"
                    text += f"📝 Задание: {t_info['text']}\n\n"

                    short_subj = subj.replace("Английский язык", "Англ.")
                    btn_text = f"✅ {short_subj}"
                    if len(btn_text) > 35:
                        btn_text = btn_text[:32] + "..."

                    btn_done = types.InlineKeyboardButton(btn_text, callback_data=f"done_tom_{subj_idx}_{i}")
                    if t_info.get("file_id"):
                        btn_file = types.InlineKeyboardButton("📎 Файл", callback_data=f"show_file_{subj_idx}_{i}")
                        markup.row(btn_done, btn_file)
                    else:
                        markup.row(btn_done)

        if not has_tasks:
            text = "📌 Домашняя работа на завтра:\n\nНа завтра заданий нет! Отдыхай 🎉"

        markup.row(types.InlineKeyboardButton("🏠 На главную", callback_data="go_home"))

        try:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=markup)
        except Exception:
            try:
                bot.delete_message(chat_id, message_id)
            except Exception:
                pass
            msg = bot.send_message(chat_id, text, reply_markup=markup)
            user_data[user_id]["current_msg_id"] = msg.message_id

    elif call.data == "btn_all_hw":
        if user_data[user_id]["eng_group"] is None:
            bot.answer_callback_query(call.id)
            markup = types.InlineKeyboardMarkup()
            markup.row(
                types.InlineKeyboardButton("👩‍🏫 Елена Николаевна", callback_data="set_eng_Елена Николаевна"),
                types.InlineKeyboardButton("👩‍🏫 Лариса Николаевна", callback_data="set_eng_Лариса Николаевна")
            )
            markup.row(types.InlineKeyboardButton("🏠 На главную", callback_data="go_home"))
            bot.edit_message_text(
                "🇬🇧 Укажи свою группу по английскому языку перед просмотром ДЗ:",
                chat_id,
                message_id,
                reply_markup=markup,
            )
            return

        bot.answer_callback_query(call.id)
        extended_subjects = list(subjects_list)
        extended_subjects.extend([
            "Английский язык (Елена Николаевна)",
            "Английский язык (Лариса Николаевна)",
        ])

        for subj in extended_subjects:
            global_tasks = homework_storage[subj]
            user_active = user_data[user_id]["active"][subj]
            user_completed = user_data[user_id]["completed"][subj]
            for task in global_tasks:
                if task not in user_active and task not in user_completed:
                    user_active.append(task)
        clean_old_homeworks(user_id)

        user_group = user_data[user_id]["eng_group"]
        text = "📚 Всё актуальное домашнее задание:\n\n"
        has_tasks = False
        markup = types.InlineKeyboardMarkup()

        for subj, tasks in user_data[user_id]["active"].items():
            if subj.startswith("Английский язык") and subj != f"Английский язык ({user_group})":
                continue

            if tasks:
                has_tasks = True
                for i, t_info in enumerate(tasks, 1):
                    subj_idx = extended_subjects.index(subj)
                    text += f"🔹 Предмет: {subj}\n"
                    text += f"📅 Дата: {t_info['date']}\n"
                    text += f"📝 Задание: {t_info['text']}\n\n"

                    short_subj = subj.replace("Английский язык", "Англ.")
                    btn_text = f"✅ {short_subj} ({i})"
                    if len(btn_text) > 35:
                        btn_text = f"✅ ({i}) {short_subj[:25]}..."

                    btn_done = types.InlineKeyboardButton(btn_text, callback_data=f"done_all_{subj_idx}_{i - 1}")
                    if t_info.get("file_id"):
                        btn_file = types.InlineKeyboardButton("📎 Файл", callback_data=f"show_file_{subj_idx}_{i - 1}")
                        markup.row(btn_done, btn_file)
                    else:
                        markup.row(btn_done)

        if not has_tasks:
            text = "📚 Всё домашнее задание:\n\nУра! Все задания выполнены 🎉"

        markup.row(types.InlineKeyboardButton("🏠 На главную", callback_data="go_home"))

        try:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=markup)
        except Exception:
            try:
                bot.delete_message(chat_id, message_id)
            except Exception:
                pass
            msg = bot.send_message(chat_id, text, reply_markup=markup)
            user_data[user_id]["current_msg_id"] = msg.message_id

    elif call.data == "btn_done":
        bot.answer_callback_query(call.id)
        clean_old_homeworks(user_id)
        text = "📁 Выполненное домашнее задание:\n\n"
        has_completed = False
        markup = types.InlineKeyboardMarkup()

        user_group = user_data[user_id]["eng_group"]
        extended_subjects = list(subjects_list)
        extended_subjects.extend([
            "Английский язык (Елена Николаевна)",
            "Английский язык (Лариса Николаевна)",
        ])

        for subj, tasks in user_data[user_id]["completed"].items():
            if subj.startswith("Английский язык") and subj != f"Английский язык ({user_group})":
                continue

            if tasks:
                has_completed = True
                for i, t_info in enumerate(tasks, 1):
                    subj_idx = extended_subjects.index(subj)
                    text += f"✅ Предмет: {subj}\n"
                    text += f"📅 Дата: {t_info['date']}\n"
                    text += f"📝 Задание: {t_info['text']}\n\n"
                    markup.row(types.InlineKeyboardButton(f"↩ Вернуть: {subj} ({i})",
                                                          callback_data=f"undone_{subj_idx}_{i - 1}"))
        if not has_completed:
            text = "📁 Выполненное Д/З:\n\nТы пока не отметил ни одного задания как выполненное."
        markup.row(types.InlineKeyboardButton("🏠 На главную", callback_data="go_home"))

        try:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=markup)
        except Exception:
            try:
                bot.delete_message(chat_id, message_id)
            except Exception:
                pass
            msg = bot.send_message(chat_id, text, reply_markup=markup)
            user_data[user_id]["current_msg_id"] = msg.message_id

    elif call.data.startswith("done_all_") or call.data.startswith("done_tom_"):
        is_tomorrow_view = call.data.startswith("done_tom_")
        prefix = "done_tom_" if is_tomorrow_view else "done_all_"
        bot.answer_callback_query(call.id, "Задание выполнено! ✅")
        parts = call.data.replace(prefix, "").rsplit("_", 1)
        extended_subjects = list(subjects_list)
        extended_subjects.extend([
            "Английский язык (Елена Николаевна)",
            "Английский язык (Лариса Николаевна)",
        ])

        if len(parts) == 2:
            try:
                subj_idx = int(parts[0])
                idx = int(parts[1])
                subj = extended_subjects[subj_idx]
                active_list = user_data[user_id]["active"][subj]
                if idx < len(active_list):
                    task_info = active_list.pop(idx)
                    user_data[user_id]["completed"][subj].append(task_info)
            except ValueError:
                pass

        user_group = user_data[user_id]["eng_group"]

        if is_tomorrow_view:
            tomorrow_date_obj = datetime.now().date() + timedelta(days=1)
            text = "📌 Домашняя работа на завтра:\n\n"
            markup = types.InlineKeyboardMarkup()
            has_tasks = False

            for subj, tasks in user_data[user_id]["active"].items():
                if subj.startswith("Английский язык") and subj != f"Английский язык ({user_group})":
                    continue
                for i, t_info in enumerate(tasks):
                    try:
                        task_date_obj = parse_flexible_date(t_info["date"])
                        is_tomorrow = task_date_obj == tomorrow_date_obj
                    except ValueError:
                        is_tomorrow = False

                    if is_tomorrow or t_info["date"].strip().lower() in ["завтра"]:
                        has_tasks = True
                        subj_idx = extended_subjects.index(subj)
                        text += f"🔹 Предмет: {subj}\n"
                        text += f"📅 Дата: {t_info['date']}\n"
                        text += f"📝 Задание: {t_info['text']}\n\n"

                        short_subj = subj.replace("Английский язык", "Англ.")
                        btn_text = f"✅ {short_subj}"
                        if len(btn_text) > 35:
                            btn_text = btn_text[:32] + "..."

                        btn_done = types.InlineKeyboardButton(btn_text, callback_data=f"done_tom_{subj_idx}_{i}")
                        if t_info.get("file_id"):
                            btn_file = types.InlineKeyboardButton("📎 Файл", callback_data=f"show_file_{subj_idx}_{i}")
                            markup.row(btn_done, btn_file)
                        else:
                            markup.row(btn_done)

            if not has_tasks:
                text = "📌 Домашняя работа на завтра:\n\nНа завтра заданий нет! Отдыхай 🎉"

            markup.row(types.InlineKeyboardButton("🏠 На главную", callback_data="go_home"))
            bot.edit_message_text(text, chat_id, message_id, reply_markup=markup)
        else:
            text = "📚 Всё актуальное домашнее задание:\n\n"
            has_tasks = False
            markup = types.InlineKeyboardMarkup()

            for subj, tasks in user_data[user_id]["active"].items():
                if subj.startswith("Английский язык") and subj != f"Английский язык ({user_group})":
                    continue

                if tasks:
                    has_tasks = True
                    for i, t_info in enumerate(tasks, 1):
                        subj_idx = extended_subjects.index(subj)
                        text += f"🔹 Предмет: {subj}\n"
                        text += f"📅 Дата: {t_info['date']}\n"
                        text += f"📝 Задание: {t_info['text']}\n\n"

                        short_subj = subj.replace("Английский язык", "Англ.")
                        btn_text = f"✅ {short_subj} ({i})"
                        if len(btn_text) > 35:
                            btn_text = f"✅ ({i}) {short_subj[:25]}..."

                        btn_done = types.InlineKeyboardButton(btn_text, callback_data=f"done_all_{subj_idx}_{i - 1}")
                        if t_info.get("file_id"):
                            btn_file = types.InlineKeyboardButton("📎 Файл",
                                                                  callback_data=f"show_file_{subj_idx}_{i - 1}")
                            markup.row(btn_done, btn_file)
                        else:
                            markup.row(btn_done)

            if not has_tasks:
                text = "📚 Всё домашнее задание:\n\nУра! Все задания выполнены 🎉"

            markup.row(types.InlineKeyboardButton("🏠 На главную", callback_data="go_home"))
            bot.edit_message_text(text, chat_id, message_id, reply_markup=markup)

    elif call.data.startswith("undone_"):
        bot.answer_callback_query(call.id, "Задание возвращено в активные! ↩️")
        parts = call.data.replace("undone_", "").rsplit("_", 1)
        extended_subjects = list(subjects_list)
        extended_subjects.extend([
            "Английский язык (Елена Николаевна)",
            "Английский язык (Лариса Николаевна)",
        ])

        if len(parts) == 2:
            try:
                subj_idx = int(parts[0])
                idx = int(parts[1])
                s = extended_subjects[subj_idx]
                completed_list = user_data[user_id]["completed"][s]
                if idx < len(completed_list):
                    task_info = completed_list.pop(idx)
                    user_data[user_id]["active"][s].append(task_info)
            except ValueError:
                pass
        text = "📁 Выполненное домашнее задание:\n\n"
        has_completed = False
        markup = types.InlineKeyboardMarkup()

        user_group = user_data[user_id]["eng_group"]

        for s, tasks in user_data[user_id]["completed"].items():
            if s.startswith("Английский язык") and s != f"Английский язык ({user_group})":
                continue

            if tasks:
                has_completed = True
                for i, t_info in enumerate(tasks, 1):
                    subj_idx = extended_subjects.index(s)
                    text += f"✅ Предмет: {s}\n"
                    text += f"📅 Дата: {t_info['date']}\n"
                    text += f"📝 Задание: {t_info['text']}\n\n"
                    markup.row(types.InlineKeyboardButton(f"↩️ Вернуть: {s} ({i})",
                                                          callback_data=f"undone_{subj_idx}_{i - 1}"))
        if not has_completed:
            text = "📁 Выполненное Д/З:\n\nТы пока не отметил ни одного задания как выполненное."
        markup.row(types.InlineKeyboardButton("🏠 На главную", callback_data="go_home"))
        bot.edit_message_text(text, chat_id, message_id, reply_markup=markup)

    elif call.data == "choose_subject":
        bot.answer_callback_query(call.id)
        user_data[user_id]["step"] = None
        user_data[user_id]["target_subject"] = None
        markup = types.InlineKeyboardMarkup()

        iterator = iter(subjects_list)
        for subj1 in iterator:
            try:
                subj2 = next(iterator)
                idx1 = subjects_list.index(subj1)
                idx2 = subjects_list.index(subj2)
                markup.add(
                    types.InlineKeyboardButton(subj1, callback_data=f"sub_{idx1}"),
                    types.InlineKeyboardButton(subj2, callback_data=f"sub_{idx2}"),
                )
            except StopIteration:
                idx1 = subjects_list.index(subj1)
                markup.add(types.InlineKeyboardButton(subj1, callback_data=f"sub_{idx1}"))
        markup.row(types.InlineKeyboardButton("🏠 На главную", callback_data="go_home"))
        bot.edit_message_text(
            "📚 Выбери предмет, для которого хочешь записать Д/З:",
            chat_id,
            message_id,
            reply_markup=markup,
        )

    elif call.data.startswith("sub_"):
        bot.answer_callback_query(call.id)
        subj_idx = int(call.data.replace("sub_", ""))
        selected_subject = subjects_list[subj_idx]

        if selected_subject == "Английский язык":
            markup = types.InlineKeyboardMarkup()
            markup.row(
                types.InlineKeyboardButton("👩‍🏫 Елена Николаевна", callback_data="eng_group_Елена Николаевна"),
                types.InlineKeyboardButton("👩‍🏫 Лариса Николаевна", callback_data="eng_group_Лариса Николаевна")
            )
            markup.row(types.InlineKeyboardButton("🏠 На главную", callback_data="go_home"))
            bot.edit_message_text(
                "🇬🇧 Выбери подгруппу по английскому языку:",
                chat_id,
                message_id,
                reply_markup=markup,
            )
        else:
            user_data[user_id]["target_subject"] = selected_subject
            user_data[user_id]["step"] = "waiting_date"
            markup = types.InlineKeyboardMarkup()
            markup.row(types.InlineKeyboardButton("🏠 На главную", callback_data="go_home"))
            prompt_text = f"📅 Введи дату сдачи для предмета {selected_subject} (например 9.9 или 9.9.2026):"
            bot.edit_message_text(prompt_text, chat_id, message_id, reply_markup=markup)

    elif call.data.startswith("eng_group_"):
        bot.answer_callback_query(call.id)
        teacher = call.data.replace("eng_group_", "")
        selected_subject = f"Английский язык ({teacher})"
        user_data[user_id]["target_subject"] = selected_subject
        user_data[user_id]["step"] = "waiting_date"

        markup = types.InlineKeyboardMarkup()
        markup.row(types.InlineKeyboardButton("🏠 На главную", callback_data="go_home"))
        prompt_text = f"📅 Введи дату сдачи для предмета {selected_subject} (например 9.9):"
        bot.edit_message_text(prompt_text, chat_id, message_id, reply_markup=markup)

    elif call.data == "starosta_delete_menu":
        bot.answer_callback_query(call.id)
        text = "🗑 Выберите задание для удаления:\n\n"
        markup = types.InlineKeyboardMarkup()
        has_any_tasks = False
        extended_subjects = list(subjects_list)
        extended_subjects.extend([
            "Английский язык (Елена Николаевна)",
            "Английский язык (Лариса Николаевна)",
        ])

        for subj in extended_subjects:
            tasks = homework_storage[subj]
            if tasks:
                has_any_tasks = True
                for i, t_info in enumerate(tasks, 1):
                    subj_idx = extended_subjects.index(subj)
                    text += f"• {subj} ({t_info['date']}): {t_info['text']}\n"
                    markup.row(
                        types.InlineKeyboardButton(f"❌ Удалить: {subj} ({i})", callback_data=f"del_{subj_idx}_{i - 1}"))
        if not has_any_tasks:
            text = "🗑 Удаление ДЗ:\n\nВ базе пока нет активных заданий для удаления."
        markup.row(types.InlineKeyboardButton("🔙 Назад в меню старосты", callback_data="back_to_starosta"))
        markup.row(types.InlineKeyboardButton("🏠 На главную", callback_data="go_home"))
        bot.edit_message_text(text, chat_id, message_id, reply_markup=markup)

    elif call.data.startswith("del_"):
        bot.answer_callback_query(call.id, "Задание удалено! 🗑")
        parts = call.data.replace("del_", "").rsplit("_", 1)
        extended_subjects = list(subjects_list)
        extended_subjects.extend([
            "Английский язык (Елена Николаевна)",
            "Английский язык (Лариса Николаевна)",
        ])

        if len(parts) == 2:
            try:
                subj_idx = int(parts[0])
                idx = int(parts[1])
                subj = extended_subjects[subj_idx]
                if idx < len(homework_storage[subj]):
                    removed_task = homework_storage[subj].pop(idx)
                    delete_homework_from_db(subj, removed_task["date"], removed_task["text"])
                for uid in user_data:
                    if idx < len(user_data[uid]["active"][subj]):
                        user_data[uid]["active"][subj].pop(idx)
                    elif idx < len(user_data[uid]["completed"][subj]):
                        user_data[uid]["completed"][subj].pop(idx)
            except ValueError:
                pass
        text = "🗑 Выберите задание для удаления:\n\n"
        markup = types.InlineKeyboardMarkup()
        has_any_tasks = False
        for subj in extended_subjects:
            tasks = homework_storage[subj]
            if tasks:
                has_any_tasks = True
                for i, t_info in enumerate(tasks, 1):
                    subj_idx = extended_subjects.index(subj)
                    text += f"• {subj} ({t_info['date']}): {t_info['text']}\n"
                    markup.row(
                        types.InlineKeyboardButton(f"❌ Удалить: {subj} ({i})", callback_data=f"del_{subj_idx}_{i - 1}"))
        if not has_any_tasks:
            text = "🗑 Удаление ДЗ:\n\nВ базе больше нет заданий."
        markup.row(types.InlineKeyboardButton("🔙 Назад в меню старосты", callback_data="back_to_starosta"))
        markup.row(types.InlineKeyboardButton("🏠 На главную", callback_data="go_home"))
        bot.edit_message_text(text, chat_id, message_id, reply_markup=markup)

    elif call.data == "back_to_starosta":
        bot.answer_callback_query(call.id)
        starosta_text = "👨‍🏫 Добро пожаловать в режим старосты!"
        markup = types.InlineKeyboardMarkup()
        markup.row(types.InlineKeyboardButton("Добавить предмет / ДЗ вручную", callback_data="choose_subject"))
        markup.row(types.InlineKeyboardButton("📸 Распознать ДЗ по скриншотам", callback_data="starosta_ocr_mode"))
        markup.row(types.InlineKeyboardButton("🗑 Удалить ДЗ", callback_data="starosta_delete_menu"))
        markup.row(types.InlineKeyboardButton("🏠 На главную", callback_data="go_home"))
        bot.edit_message_text(starosta_text, chat_id, message_id, reply_markup=markup)


@bot.message_handler(content_types=["text", "photo", "document", "video"])
def handle_incoming_content(message):
    SECRET_CODE = "1234"
    user_id = message.from_user.id
    init_user(user_id)
    clean_old_homeworks(user_id)
    chat_id = message.chat.id
    text = message.text or message.caption or ""

    if user_data[user_id].get("step") == "editing_ocr_text":
        try:
            bot.delete_message(chat_id, message.message_id)
        except Exception:
            pass

        idx = user_data[user_id].get("editing_task_idx")
        if idx is not None and 0 <= idx < len(user_data[user_id]["ocr_parsed_tasks"]):
            user_data[user_id]["ocr_parsed_tasks"][idx]["text"] = text.strip()

        user_data[user_id]["step"] = None
        user_data[user_id]["editing_task_idx"] = None

        menu_id = user_data[user_id].get("current_msg_id")
        if menu_id:
            show_ocr_results(chat_id, menu_id, user_id)
        return

    if user_data[user_id].get("step") == "collecting_ocr_photos" and message.photo:
        try:
            file_info = bot.get_file(message.photo[-1].file_id)
            downloaded_bytes = bot.download_file(file_info.file_path)
            user_data[user_id]["ocr_photos"].append(downloaded_bytes)
        except Exception as e:
            print(f"Ошибка при скачивании фото: {e}")

        count = len(user_data[user_id]["ocr_photos"])
        menu_id = user_data[user_id].get("current_msg_id")

        markup = types.InlineKeyboardMarkup()
        markup.row(types.InlineKeyboardButton("✅ Готово, запустить анализ", callback_data="start_ocr_process"))
        markup.row(types.InlineKeyboardButton("🏠 На главную", callback_data="go_home"))

        prompt_text = (
            f"📸 Загружено скриншотов: {count}\n\n"
            "Можешь отправить ещё фото или нажать «Готово, запустить анализ»!"
        )

        if menu_id:
            try:
                bot.edit_message_text(prompt_text, chat_id, menu_id, reply_markup=markup)
                return
            except Exception:
                pass
        msg = bot.send_message(chat_id, prompt_text, reply_markup=markup)
        user_data[user_id]["current_msg_id"] = msg.message_id
        return

    if text.strip() == SECRET_CODE:
        try:
            bot.delete_message(chat_id, message.message_id)
        except Exception:
            pass

        user_data[user_id]["target_subject"] = None
        user_data[user_id]["step"] = None
        starosta_text = "👨‍🏫 Добро пожаловать в режим старосты!"
        markup = types.InlineKeyboardMarkup()
        markup.row(types.InlineKeyboardButton("Добавить предмет / ДЗ вручную", callback_data="choose_subject"))
        markup.row(types.InlineKeyboardButton("📸 Распознать ДЗ по скриншотам", callback_data="starosta_ocr_mode"))
        markup.row(types.InlineKeyboardButton("🗑 Удалить ДЗ", callback_data="starosta_delete_menu"))
        markup.row(types.InlineKeyboardButton("🏠 На главную", callback_data="go_home"))
        menu_id = user_data[user_id].get("current_msg_id")
        if menu_id:
            try:
                bot.edit_message_text(starosta_text, chat_id, menu_id, reply_markup=markup)
                return
            except Exception:
                pass
        msg = bot.send_message(chat_id, starosta_text, reply_markup=markup)
        user_data[user_id]["current_msg_id"] = msg.message_id

    elif user_data[user_id].get("step") == "waiting_date":
        try:
            bot.delete_message(chat_id, message.message_id)
        except Exception:
            pass

        date_text = text.strip()
        try:
            parsed_date = parse_flexible_date(date_text)
            if parsed_date < datetime.now().date():
                error_text = "❌ Ошибка! Нельзя добавить домашку на прошедший день. Введите актуальную дату:"
                markup = types.InlineKeyboardMarkup()
                markup.row(types.InlineKeyboardButton("🏠 На главную", callback_data="go_home"))
                menu_id = user_data[user_id].get("current_msg_id")
                if menu_id:
                    try:
                        bot.edit_message_text(error_text, chat_id, menu_id, reply_markup=markup)
                        return
                    except Exception:
                        pass
                msg = bot.send_message(chat_id, error_text, reply_markup=markup)
                user_data[user_id]["current_msg_id"] = msg.message_id
                return
        except ValueError:
            error_text = "❌ Неверный формат даты. Введите в формате ДД.ММ.ГГГГ или ДД.ММ (можно без нулей):"
            markup = types.InlineKeyboardMarkup()
            markup.row(types.InlineKeyboardButton("🏠 На главную", callback_data="go_home"))
            menu_id = user_data[user_id].get("current_msg_id")
            if menu_id:
                try:
                    bot.edit_message_text(error_text, chat_id, menu_id, reply_markup=markup)
                    return
                except Exception:
                    pass
            msg = bot.send_message(chat_id, error_text, reply_markup=markup)
            user_data[user_id]["current_msg_id"] = msg.message_id
            return

        user_data[user_id]["temp_date"] = text
        user_data[user_id]["step"] = "waiting_text"
        prompt_text = f"📅 Дата {text} сохранена.\n\nТеперь отправь текст домашнего задания (можно прикрепить фото, видео или документ):"
        markup = types.InlineKeyboardMarkup()
        markup.row(types.InlineKeyboardButton("🏠 На главную", callback_data="go_home"))
        menu_id = user_data[user_id].get("current_msg_id")
        if menu_id:
            try:
                bot.edit_message_text(prompt_text, chat_id, menu_id, reply_markup=markup)
                return
            except Exception:
                pass
        msg = bot.send_message(chat_id, prompt_text, reply_markup=markup)
        user_data[user_id]["current_msg_id"] = msg.message_id

    elif user_data[user_id].get("step") == "waiting_text":
        try:
            bot.delete_message(chat_id, message.message_id)
        except Exception:
            pass

        subject = user_data[user_id]["target_subject"]
        date_val = user_data[user_id]["temp_date"]
        user_data[user_id]["target_subject"] = None
        user_data[user_id]["step"] = None
        user_data[user_id]["temp_date"] = None

        file_id = None
        file_type = None

        if message.photo:
            file_id = message.photo[-1].file_id
            file_type = "photo"
            if not text:
                text = "📁 Фотография к заданию"
        elif message.document:
            file_id = message.document.file_id
            file_type = "document"
            if not text:
                text = f"📁 Документ: {message.document.file_name}"
        elif message.video:
            file_id = message.video.file_id
            file_type = "video"
            if not text:
                text = "📁 Видеоматериал к заданию"

        if not text:
            text = "Без текстового описания"

        task_info = {
            "date": date_val,
            "text": text,
            "file_id": file_id,
            "file_type": file_type,
        }

        add_homework_to_db(subject, date_val, text, file_id, file_type)
        homework_storage[subject].append(task_info)
        for uid in user_data:
            user_data[uid]["active"][subject].append(task_info)

        success_text = f"✅ ДЗ успешно добавлено!\n\nПредмет: {subject}\nДата: {date_val}\nЗадание: {text}"
        markup = types.InlineKeyboardMarkup()
        markup.row(types.InlineKeyboardButton("🏠 На главную", callback_data="go_home"))

        menu_id = user_data[user_id]["current_msg_id"]
        if menu_id:
            try:
                bot.edit_message_text(success_text, chat_id, menu_id, reply_markup=markup)
                return
            except Exception:
                pass
        msg = bot.send_message(chat_id, success_text, reply_markup=markup)
        user_data[user_id]["current_msg_id"] = msg.message_id
    else:
        pass


if __name__ == "__main__":
    print("Бот запущен с поддержкой Gemini AI для скриншотов...")
    bot.infinity_polling(skip_pending=True, interval=1, timeout=20)
