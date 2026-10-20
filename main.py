import os
import sqlite3
from datetime import datetime, timedelta
import telebot
from telebot import types
import json
from PIL import Image
import io

# Импортируем официальную библиотеку Google GenAI
from google import genai
from google.genai import types as genai_types

# --- СТАБИЛЬНЫЙ МИНИ-СЕРВЕР ДЛЯ RENDER (В ОТДЕЛЬНОМ ПОТОКЕ СОКЕТОВ) ---
import socket
import threading


def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind(('0.0.0.0', port))
    server_socket.listen(5)
    while True:
        try:
            client_socket, _ = server_socket.accept()
            request = client_socket.recv(1024)
            response = b"HTTP/1.1 200 OK\r\nContent-Length: 13\r\n\r\nBot is running"
            client_socket.sendall(response)
            client_socket.close()
        except Exception:
            pass


threading.Thread(target=run_web_server, daemon=True).start()
# -------------------------------------------------------------------------

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("Переменная окружения TELEGRAM_BOT_TOKEN не задана!")
bot = telebot.TeleBot(TOKEN)

# Безопасная инициализация клиента Gemini API через переменную окружения Render
gemini_key = os.environ.get("GEMINI_API_KEY")
if gemini_key:
    client = genai.Client(api_key=gemini_key)
else:
    print("ВНИМАНИЕ: Переменная GEMINI_API_KEY не задана в Environment Variables!")
    client = None

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
        if subj not in storage:
            storage[subj] = []
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

        all_storage_keys = set(extended_subjects).union(homework_storage.keys())

        user_data[user_id] = {
            "active": {sub: list(homework_storage.get(sub, [])) for sub in all_storage_keys},
            "completed": {sub: [] for sub in all_storage_keys},
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
    if user_id in user_data:
        for state_type in ["active", "completed"]:
            for subj in list(user_data[user_id][state_type].keys()):
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

    for subj in list(homework_storage.keys()):
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
    """Распознаёт задания на скриншотах через Gemini, не меняя выбранную модель."""
    print("--- ЗАПУСК АНАЛИЗА GEMINI ---")

    if not client:
        print("❌ GEMINI_API_KEY не задан в переменных окружения.")
        return []

    if not photo_bytes_list:
        print("❌ Список скриншотов пуст.")
        return []

    # Передаём оригинальные байты изображения с корректным MIME-типом.
    contents = []
    mime_by_format = {
        "JPEG": "image/jpeg",
        "JPG": "image/jpeg",
        "PNG": "image/png",
        "WEBP": "image/webp",
        "GIF": "image/gif",
        "BMP": "image/bmp",
    }

    for index, image_bytes in enumerate(photo_bytes_list, start=1):
        try:
            with Image.open(io.BytesIO(image_bytes)) as img:
                image_format = (img.format or "").upper()
                mime_type = mime_by_format.get(image_format)
                if not mime_type:
                    raise ValueError(f"Неподдерживаемый формат изображения: {image_format or 'неизвестен'}")
                img.verify()

            contents.append(
                genai_types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
            )
            print(f"✅ Скриншот #{index} подготовлен ({mime_type}, {len(image_bytes)} байт).")
        except Exception as img_err:
            print(f"❌ Скриншот #{index} пропущен: {img_err}")

    if not contents:
        print("❌ Не удалось подготовить ни одного изображения.")
        return []

    current_year = datetime.now().year
    prompt = f"""
Проанализируй прикреплённые скриншоты школьного электронного дневника.
Найди все домашние задания, которые явно указаны на скриншотах.

Правила:
1. subject — название школьного предмета, как оно написано на скриншоте.
2. date — дата сдачи задания, а не дата публикации. Верни дату в формате ДД.ММ.ГГГГ.
   Если на скриншоте указан день недели и дата без года, используй {current_year}.
   Не выдумывай дату, если её невозможно определить: в таком случае пропусти задание.
3. text — текст домашнего задания. Не включай тему урока, если она не является заданием.
4. Не дублируй одно и то же задание, если оно повторяется на нескольких скриншотах.
5. Не придумывай данные, которых нет на изображениях.

Верни только JSON-массив объектов следующего вида:
[
  {{"subject": "Алгебра", "date": "21.10.{current_year}", "text": "стр. 20, упражнение 5"}}
]
Если заданий нет, верни [].
"""

    try:
        print(f"⏳ Отправка {len(contents)} изображений в Gemini (модель gemini-3.8-flash)...")
        response = client.models.generate_content(
            model="gemini-3.8-flash",
            contents=contents + [prompt],
            config=genai_types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1,
            ),
        )

        response_text = getattr(response, "text", None)
        if not response_text or not response_text.strip():
            print("❌ Gemini вернула пустой ответ.")
            print(f"Причина завершения ответа: {getattr(response, 'prompt_feedback', None)}")
            return []

        print(f"📥 Ответ Gemini получен ({len(response_text)} символов).")
        cleaned_text = response_text.strip()

        # На случай, если модель всё-таки добавила Markdown-обрамление.
        if cleaned_text.startswith("```"):
            cleaned_text = cleaned_text.split("\n", 1)[-1]
            if cleaned_text.rstrip().endswith("```"):
                cleaned_text = cleaned_text.rstrip()[:-3].strip()

        tasks = json.loads(cleaned_text)
        if not isinstance(tasks, list):
            raise ValueError("Ответ Gemini — JSON, но это не список.")

        valid_tasks = []
        for item in tasks:
            if not isinstance(item, dict):
                continue
            subject = str(item.get("subject", "")).strip()
            date_val = str(item.get("date", "")).strip()
            task_text = str(item.get("text", "")).strip()
            if not (subject and date_val and task_text):
                print(f"⚠️ Пропущен неполный элемент: {item}")
                continue
            # Проверяем, что дата действительно разбирается.
            try:
                parsed_date = parse_flexible_date(date_val)
                date_val = parsed_date.strftime("%d.%m.%Y")
            except (ValueError, TypeError):
                print(f"⚠️ Пропущено задание с неверной датой: {item}")
                continue
            valid_tasks.append({
                "subject": subject,
                "date": date_val,
                "text": task_text,
            })

        print(f"✅ Успешно распознано заданий: {len(valid_tasks)}")
        return valid_tasks

    except json.JSONDecodeError as e:
        print(f"❌ Gemini вернула некорректный JSON: {e}")
        print(f"Ответ для диагностики: {getattr(response, 'text', '')[:1000] if 'response' in locals() else 'ответ отсутствует'}")
    except Exception as e:
        print(f"❌ Ошибка Gemini API или обработки изображения: {type(e).__name__}: {e}")

    return []


def show_ocr_results(chat_id, message_id, user_id):
    parsed_tasks = user_data[user_id].get("ocr_parsed_tasks", [])
    markup = types.InlineKeyboardMarkup()
    if parsed_tasks:
        text = "🤖 **Нейросеть проанализировала скриншоты и нашла задания:**\n\n"
        for idx, item in enumerate(parsed_tasks):
            text += f"{idx + 1}. Предмет: {item['subject']}\n"
            text += f"Дата: {item['date']}\n"
            text += f"Задание: {item['text']}\n\n"
            markup.row(types.InlineKeyboardButton(f"✏️ Изменить текст #{idx + 1}", callback_data=f"edit_ocr_{idx}"))
        text += "Всё верно? Нажми кнопку ниже, чтобы автоматически занести их в базу."
        markup.row(types.InlineKeyboardButton("✅ Подтвердить и сохранить", callback_data="confirm_ocr_save"))
    else:
        text = "❌ Нейросеть не смогла обнаружить задания на скриншотах. Попробуй добавить ДЗ вручную через меню."

    markup.row(types.InlineKeyboardButton("🏠 На главную", callback_data="go_home"))
    try:
        bot.edit_message_text(text, chat_id, message_id, reply_markup=markup)
    except Exception as e:
        if "message is not modified" not in str(e):
            msg = bot.send_message(chat_id, text, reply_markup=markup)
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

    # Сообщение пользователя /start НЕ удаляется

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
            f"✏️ Редактирование задания #{idx + 1} ({task['subject']})\n\n"
            f"Текущий текст:\n{task['text']}\n\n"
            "Отправь новый текст для этого задания:"
        )
        try:
            bot.edit_message_text(prompt_text, chat_id, message_id, reply_markup=markup)
        except Exception as e:
            if "message is not modified" not in str(e):
                pass
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
        
        all_subj_keys = list(user_data[user_id]["active"].keys())

        if len(parts) == 2:
            try:
                subj_idx = int(parts[0])
                idx = int(parts[1])
                subj = all_subj_keys[subj_idx]
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
        all_subj_keys = list(user_data[user_id]["active"].keys())

        if len(parts) == 2:
            try:
                subj_idx = int(parts[0])
                idx = int(parts[1])
                subj = all_subj_keys[subj_idx]
                active_list = user_data[user_id]["active"][subj]
                if idx < len(active_list):
                    task_info = active_list.pop(idx)
                    user_data[user_id]["completed"][subj].append(task_info)
            except ValueError:
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
        try:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=markup)
        except Exception as e:
            if "message is not modified" not in str(e):
                pass
        return

    if call.data == "start_ocr_process":
        bot.answer_callback_query(call.id, "Запускаю нейросеть...")

        try:
            bot.edit_message_text("⏳ Нейросеть изучает скриншоты... Это займет несколько секунд.", chat_id, message_id)
        except Exception as e:
            if "message is not modified" not in str(e):
                pass

        try:
            bot.send_chat_action(chat_id, 'typing')
        except Exception:
            pass

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

        saved_count = 0
        for t in tasks_to_add:
            subject = t["subject"].strip()
            date_val = t["date"].strip()
            text_val = t["text"].strip()

            try:
                add_homework_to_db(subject, date_val, text_val)
                task_info = {"date": date_val, "text": text_val, "file_id": None, "file_type": None}

                if subject not in homework_storage:
                    homework_storage[subject] = []
                homework_storage[subject].append(task_info)

                for uid in user_data:
                    if subject not in user_data[uid]["active"]:
                        user_data[uid]["active"][subject] = []
                        user_data[uid]["completed"][subject] = []
                    user_data[uid]["active"][subject].append(task_info)

                saved_count += 1
            except Exception as db_err:
                print(f"❌ Ошибка сохранения задания в БД: {db_err}")

        user_data[user_id]["ocr_parsed_tasks"] = []
        user_data[user_id]["ocr_photos"] = []
        bot.answer_callback_query(call.id, "Задания успешно сохранены! 🎉")

        markup = types.InlineKeyboardMarkup()
        markup.row(types.InlineKeyboardButton("🏠 На главную", callback_data="go_home"))
        try:
            bot.edit_message_text(
                f"✅ Успешно добавлено заданий: {saved_count} из {len(tasks_to_add)}!\n\nВсе ученики уже видят обновлённое ДЗ.",
                chat_id,
                message_id,
                reply_markup=markup
            )
        except Exception as e:
            if "message is not modified" not in str(e):
                pass
        return

    if call.data.startswith("set_eng_"):
        bot.answer_callback_query(call.id, "Группа сохранена! ✅")
        teacher = call.data.replace("set_eng_", "")
        user_data[user_id]["eng_group"] = teacher
        try:
            bot.edit_message_text(
                f"🇬🇧 Отлично! Твоя группа по английскому: {teacher}.\n\nТеперь выбери нужное действие:",
                chat_id,
                message_id,
                reply_markup=get_welcome_markup(),
            )
        except Exception as e:
            if "message is not modified" not in str(e):
                pass
        return

    if call.data == "go_home":
        bot.answer_callback_query(call.id)
        user_data[user_id]["ocr_photos"] = []
        try:
            bot.edit_message_text(
                "Добро пожаловать!👋\n\nЭто проводник по домашнему заданию. Что тебя интересует?📚",
                chat_id,
                message_id,
                reply_markup=get_welcome_markup(),
            )
        except Exception as e:
            if "message is not modified" not in str(e):
                msg = bot.send_message(
                    chat_id,
                    "Добро пожаловать!👋\n\nЭто проводник по домашнему заданию. Что тебя интересует?📚",
                    reply_markup=get_welcome_markup(),
                )
                user_data[user_id]["current_msg_id"] = msg.message_id

    elif call.data == "btn_tomorrow":
        bot.answer_callback_query(call.id)
        
        all_subj_keys = list(user_data[user_id]["active"].keys())
        for subj in all_subj_keys:
            global_tasks = homework_storage.get(subj, [])
            user_active = user_data[user_id]["active"][subj]
            user_completed = user_data[user_id]["completed"][subj]
            for task in global_tasks:
                if task not in user_active and task not in user_completed:
                    user_active.append(task)
        clean_old_homeworks(user_id)

        tomorrow_date_obj = datetime.now().date() + timedelta(days=1)
        text = "📌 Домашняя работа на завтра:\n\n"
        markup = types.InlineKeyboardMarkup()
        has_tasks = False

        for subj, tasks in user_data[user_id]["active"].items():
            for i, t_info in enumerate(tasks):
                try:
                    task_date_obj = parse_flexible_date(t_info["date"])
                    is_tomorrow = task_date_obj == tomorrow_date_obj
                except ValueError:
                    is_tomorrow = False

                if is_tomorrow or t_info["date"].strip().lower() in ["завтра"]:
                    has_tasks = True
                    subj_idx = all_subj_keys.index(subj)
                    text += f"🔹 Предмет: {subj}\n"
                    text += f"📅 Дата: {t_info['date']}\n"
                    text += f"📝 Задание: {t_info['text']}\n\n"

                    btn_text = f"✅ {subj}"
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
        except Exception as e:
            if "message is not modified" not in str(e):
                msg = bot.send_message(chat_id, text, reply_markup=markup)
                user_data[user_id]["current_msg_id"] = msg.message_id

    elif call.data == "btn_all_hw":
        bot.answer_callback_query(call.id)
        
        all_subj_keys = list(user_data[user_id]["active"].keys())
        for subj in all_subj_keys:
            global_tasks = homework_storage.get(subj, [])
            user_active = user_data[user_id]["active"][subj]
            user_completed = user_data[user_id]["completed"][subj]
            for task in global_tasks:
                if task not in user_active and task not in user_completed:
                    user_active.append(task)
        clean_old_homeworks(user_id)

        text = "📚 Всё актуальное домашнее задание:\n\n"
        has_tasks = False
        markup = types.InlineKeyboardMarkup()

        for subj, tasks in user_data[user_id]["active"].items():
            if tasks:
                has_tasks = True
                for i, t_info in enumerate(tasks, 1):
                    subj_idx = all_subj_keys.index(subj)
                    text += f"🔹 Предмет: {subj}\n"
                    text += f"📅 Дата: {t_info['date']}\n"
                    text += f"📝 Задание: {t_info['text']}\n\n"

                    btn_text = f"✅ {subj} ({i})"
                    if len(btn_text) > 35:
                        btn_text = f"✅ ({i}) {subj[:25]}..."

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
        except Exception as e:
            if "message is not modified" not in str(e):
                msg = bot.send_message(chat_id, text, reply_markup=markup)
                user_data[user_id]["current_msg_id"] = msg.message_id

    elif call.data == "btn_done":
        bot.answer_callback_query(call.id)
        clean_old_homeworks(user_id)
        text = "📁 Выполненное домашнее задание:\n\n"
        has_completed = False
        markup = types.InlineKeyboardMarkup()

        all_subj_keys = list(user_data[user_id]["completed"].keys())

        for subj, tasks in user_data[user_id]["completed"].items():
            if tasks:
                has_completed = True
                for i, t_info in enumerate(tasks, 1):
                    subj_idx = all_subj_keys.index(subj)
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
        except Exception as e:
            if "message is not modified" not in str(e):
                msg = bot.send_message(chat_id, text, reply_markup=markup)
                user_data[user_id]["current_msg_id"] = msg.message_id

    elif call.data.startswith("done_all_") or call.data.startswith("done_tom_"):
        is_tomorrow_view = call.data.startswith("done_tom_")
        prefix = "done_tom_" if is_tomorrow_view else "done_all_"
        bot.answer_callback_query(call.id, "Задание выполнено! ✅")
        parts = call.data.replace(prefix, "").rsplit("_", 1)
        all_subj_keys = list(user_data[user_id]["active"].keys())

        if len(parts) == 2:
            try:
                subj_idx = int(parts[0])
                idx = int(parts[1])
                subj = all_subj_keys[subj_idx]
                active_list = user_data[user_id]["active"][subj]
                if idx < len(active_list):
                    task_info = active_list.pop(idx)
                    user_data[user_id]["completed"][subj].append(task_info)
            except ValueError:
                pass

        if is_tomorrow_view:
            tomorrow_date_obj = datetime.now().date() + timedelta(days=1)
            text = "📌 Домашняя работа на завтра:\n\n"
            markup = types.InlineKeyboardMarkup()
            has_tasks = False

            for subj, tasks in user_data[user_id]["active"].items():
                for i, t_info in enumerate(tasks):
                    try:
                        task_date_obj = parse_flexible_date(t_info["date"])
                        is_tomorrow = task_date_obj == tomorrow_date_obj
                    except ValueError:
                        is_tomorrow = False

                    if is_tomorrow or t_info["date"].strip().lower() in ["завтра"]:
                        has_tasks = True
                        subj_idx = all_subj_keys.index(subj)
                        text += f"🔹 Предмет: {subj}\n"
                        text += f"📅 Дата: {t_info['date']}\n"
                        text += f"📝 Задание: {t_info['text']}\n\n"

                        btn_text = f"✅ {subj}"
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
            except Exception as e:
                if "message is not modified" not in str(e):
                    pass
        else:
            text = "📚 Всё актуальное домашнее задание:\n\n"
            has_tasks = False
            markup = types.InlineKeyboardMarkup()

            for subj, tasks in user_data[user_id]["active"].items():
                if tasks:
                    has_tasks = True
                    for i, t_info in enumerate(tasks, 1):
                        subj_idx = all_subj_keys.index(subj)
                        text += f"🔹 Предмет: {subj}\n"
                        text += f"📅 Дата: {t_info['date']}\n"
                        text += f"📝 Задание: {t_info['text']}\n\n"

                        btn_text = f"✅ {subj} ({i})"
                        if len(btn_text) > 35:
                            btn_text = f"✅ ({i}) {subj[:25]}..."

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
            try:
                bot.edit_message_text(text, chat_id, message_id, reply_markup=markup)
            except Exception as e:
                if "message is not modified" not in str(e):
                    pass

    elif call.data.startswith("undone_"):
        bot.answer_callback_query(call.id, "Задание возвращено в активные! ↩️")
        parts = call.data.replace("undone_", "").rsplit("_", 1)
        all_subj_keys = list(user_data[user_id]["completed"].keys())

        if len(parts) == 2:
            try:
                subj_idx = int(parts[0])
                idx = int(parts[1])
                s = all_subj_keys[subj_idx]
                completed_list = user_data[user_id]["completed"][s]
                if idx < len(completed_list):
                    task_info = completed_list.pop(idx)
                    user_data[user_id]["active"][s].append(task_info)
            except ValueError:
                pass
        text = "📁 Выполненное домашнее задание:\n\n"
        has_completed = False
        markup = types.InlineKeyboardMarkup()

        for s, tasks in user_data[user_id]["completed"].items():
            if tasks:
                has_completed = True
                for i, t_info in enumerate(tasks, 1):
                    subj_idx = all_subj_keys.index(s)
                    text += f"✅ Предмет: {s}\n"
                    text += f"📅 Дата: {t_info['date']}\n"
                    text += f"📝 Задание: {t_info['text']}\n\n"
                    markup.row(types.InlineKeyboardButton(f"↩️ Вернуть: {s} ({i})",
                                                          callback_data=f"undone_{subj_idx}_{i - 1}"))
        if not has_completed:
            text = "📁 Выполненное Д/З:\n\nТы пока не отметил ни одного задания как выполненное."
        markup.row(types.InlineKeyboardButton("🏠 На главную", callback_data="go_home"))
        try:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=markup)
        except Exception as e:
            if "message is not modified" not in str(e):
                pass

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
        try:
            bot.edit_message_text(
                "📚 Выбери предмет, для которого хочешь записать Д/З:",
                chat_id,
                message_id,
                reply_markup=markup,
            )
        except Exception as e:
            if "message is not modified" not in str(e):
                pass

    elif call.data.startswith("sub_"):
        bot.answer_callback_query(call.id)
        subj_idx = int(call.data.replace("sub_", ""))
        selected_subject = subjects_list[subj_idx]

        user_data[user_id]["target_subject"] = selected_subject
        user_data[user_id]["step"] = "waiting_date"
        markup = types.InlineKeyboardMarkup()
        markup.row(types.InlineKeyboardButton("🏠 На главную", callback_data="go_home"))
        prompt_text = f"📅 Введи дату сдачи для предмета {selected_subject} (например 9.9 или 9.9.2026):"
        try:
            bot.edit_message_text(prompt_text, chat_id, message_id, reply_markup=markup)
        except Exception as e:
            if "message is not modified" not in str(e):
                pass

    elif call.data == "starosta_delete_menu":
        bot.answer_callback_query(call.id)
        text = "🗑 Выберите задание для удаления:\n\n"
        markup = types.InlineKeyboardMarkup()
        has_any_tasks = False
        
        all_subj_keys = list(homework_storage.keys())

        for subj in all_subj_keys:
            tasks = homework_storage[subj]
            if tasks:
                has_any_tasks = True
                for i, t_info in enumerate(tasks, 1):
                    subj_idx = all_subj_keys.index(subj)
                    text += f"• {subj} ({t_info['date']}): {t_info['text']}\n"
                    markup.row(
                        types.InlineKeyboardButton(f"❌ Удалить: {subj} ({i})", callback_data=f"del_{subj_idx}_{i - 1}"))
        if not has_any_tasks:
            text = "🗑 Удаление ДЗ:\n\nВ базе пока нет активных заданий для удаления."
        markup.row(types.InlineKeyboardButton("🔙 Назад в меню старосты", callback_data="back_to_starosta"))
        markup.row(types.InlineKeyboardButton("🏠 На главную", callback_data="go_home"))
        try:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=markup)
        except Exception as e:
            if "message is not modified" not in str(e):
                pass

    elif call.data.startswith("del_"):
        bot.answer_callback_query(call.id, "Задание удалено! 🗑")
        parts = call.data.replace("del_", "").rsplit("_", 1)
        all_subj_keys = list(homework_storage.keys())

        if len(parts) == 2:
            try:
                subj_idx = int(parts[0])
                idx = int(parts[1])
                subj = all_subj_keys[subj_idx]
                if idx < len(homework_storage[subj]):
                    removed_task = homework_storage[subj].pop(idx)
                    delete_homework_from_db(subj, removed_task["date"], removed_task["text"])
                for uid in user_data:
                    if subj in user_data[uid]["active"] and idx < len(user_data[uid]["active"][subj]):
                        user_data[uid]["active"][subj].pop(idx)
                    elif subj in user_data[uid]["completed"] and idx < len(user_data[uid]["completed"][subj]):
                        user_data[uid]["completed"][subj].pop(idx)
            except ValueError:
                pass
        text = "🗑 Выберите задание для удаления:\n\n"
        markup = types.InlineKeyboardMarkup()
        has_any_tasks = False
        for subj in all_subj_keys:
            tasks = homework_storage[subj]
            if tasks:
                has_any_tasks = True
                for i, t_info in enumerate(tasks, 1):
                    subj_idx = all_subj_keys.index(subj)
                    text += f"• {subj} ({t_info['date']}): {t_info['text']}\n"
                    markup.row(
                        types.InlineKeyboardButton(f"❌ Удалить: {subj} ({i})", callback_data=f"del_{subj_idx}_{i - 1}"))
        if not has_any_tasks:
            text = "🗑 Удаление ДЗ:\n\nВ базе больше нет заданий."
        markup.row(types.InlineKeyboardButton("🔙 Назад в меню старосты", callback_data="back_to_starosta"))
        markup.row(types.InlineKeyboardButton("🏠 На главную", callback_data="go_home"))
        try:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=markup)
        except Exception as e:
            if "message is not modified" not in str(e):
                pass

    elif call.data == "back_to_starosta":
        bot.answer_callback_query(call.id)
        starosta_text = "👨‍🏫 Добро пожаловать в режим старосты!"
        markup = types.InlineKeyboardMarkup()
        markup.row(types.InlineKeyboardButton("Добавить предмет / ДЗ вручную", callback_data="choose_subject"))
        markup.row(types.InlineKeyboardButton("📸 Распознать ДЗ по скриншотам", callback_data="starosta_ocr_mode"))
        markup.row(types.InlineKeyboardButton("🗑 Удалить ДЗ", callback_data="starosta_delete_menu"))
        markup.row(types.InlineKeyboardButton("🏠 На главную", callback_data="go_home"))
        try:
            bot.edit_message_text(starosta_text, chat_id, message_id, reply_markup=markup)
        except Exception as e:
            if "message is not modified" not in str(e):
                pass


@bot.message_handler(content_types=["text", "photo", "document", "video"])
def handle_incoming_content(message):
    SECRET_CODE = "1234"
    user_id = message.from_user.id
    init_user(user_id)
    clean_old_homeworks(user_id)
    chat_id = message.chat.id
    text = message.text or message.caption or ""
    step = user_data[user_id].get("step")

    # 1. Сбор фотографий для OCR (НЕ удаляем фото)
    if step == "collecting_ocr_photos" and message.photo:
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
            except Exception as e:
                if "message is not modified" not in str(e):
                    pass
        msg = bot.send_message(chat_id, prompt_text, reply_markup=markup)
        user_data[user_id]["current_msg_id"] = msg.message_id
        return

    # 2. Редактирование текста задачи из OCR
    if step == "editing_ocr_text":
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

    # 3. Ввод секретного кода старосты
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
            except Exception as e:
                if "message is not modified" not in str(e):
                    pass
        msg = bot.send_message(chat_id, starosta_text, reply_markup=markup)
        user_data[user_id]["current_msg_id"] = msg.message_id
        return

    # 4. Ожидание даты при ручном добавлении
    if step == "waiting_date":
        date_text = text.strip()
        try:
            parsed_date = parse_flexible_date(date_text)
            if parsed_date < datetime.now().date():
                try:
                    bot.delete_message(chat_id, message.message_id)
                except Exception:
                    pass
                error_text = "❌ Ошибка! Нельзя добавить домашку на прошедший день. Введите актуальную дату:"
                markup = types.InlineKeyboardMarkup()
                markup.row(types.InlineKeyboardButton("🏠 На главную", callback_data="go_home"))
                menu_id = user_data[user_id].get("current_msg_id")
                if menu_id:
                    try:
                        bot.edit_message_text(error_text, chat_id, menu_id, reply_markup=markup)
                        return
                    except Exception as e:
                        if "message is not modified" not in str(e):
                            pass
                msg = bot.send_message(chat_id, error_text, reply_markup=markup)
                user_data[user_id]["current_msg_id"] = msg.message_id
                return
        except ValueError:
            try:
                bot.delete_message(chat_id, message.message_id)
            except Exception:
                pass
            error_text = "❌ Неверный формат даты. Введите в формате ДД.ММ.ГГГГ или ДД.ММ (можно без нулей):"
            markup = types.InlineKeyboardMarkup()
            markup.row(types.InlineKeyboardButton("🏠 На главную", callback_data="go_home"))
            menu_id = user_data[user_id].get("current_msg_id")
            if menu_id:
                try:
                    bot.edit_message_text(error_text, chat_id, menu_id, reply_markup=markup)
                    return
                except Exception as e:
                    if "message is not modified" not in str(e):
                        pass
            msg = bot.send_message(chat_id, error_text, reply_markup=markup)
            user_data[user_id]["current_msg_id"] = msg.message_id
            return

        try:
            bot.delete_message(chat_id, message.message_id)
        except Exception:
            pass

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
            except Exception as e:
                if "message is not modified" not in str(e):
                    pass
        msg = bot.send_message(chat_id, prompt_text, reply_markup=markup)
        user_data[user_id]["current_msg_id"] = msg.message_id
        return

    # 5. Ожидание текста/файла задания при ручном добавлении
    if step == "waiting_text":
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
        if subject not in homework_storage:
            homework_storage[subject] = []
        homework_storage[subject].append(task_info)
        
        for uid in user_data:
            if subject not in user_data[uid]["active"]:
                user_data[uid]["active"][subject] = []
                user_data[uid]["completed"][subject] = []
            user_data[uid]["active"][subject].append(task_info)

        success_text = f"✅ ДЗ успешно добавлено!\n\nПредмет: {subject}\nДата: {date_val}\nЗадание: {text}"
        markup = types.InlineKeyboardMarkup()
        markup.row(types.InlineKeyboardButton("🏠 На главную", callback_data="go_home"))

        menu_id = user_data[user_id]["current_msg_id"]
        if menu_id:
            try:
                bot.edit_message_text(success_text, chat_id, menu_id, reply_markup=markup)
                return
            except Exception as e:
                if "message is not modified" not in str(e):
                    pass
        msg = bot.send_message(chat_id, success_text, reply_markup=markup)
        user_data[user_id]["current_msg_id"] = msg.message_id
        return

    # 6. Если бот не ожидает никакого ввода -> молча удаляем бессмысленное сообщение
    try:
        bot.delete_message(chat_id, message.message_id)
    except Exception:
        pass


if __name__ == "__main__":
    print("Бот запущен с поддержкой Gemini AI...")
    if client:
        try:
            test_resp = client.models.generate_content(
                model='gemini-3.8-flash',
                contents='Ответь словом "ОК", если видишь этот запрос'
            )
            print(f"ТЕСТ GEMINI API УСПЕШЕН: {test_resp.text}")
        except Exception as err:
            print(f"ОШИБКА ТЕСТА GEMINI API: {err}")
    else:
        print("ТЕСТ ОТМЕНЕН: Ключ GEMINI_API_KEY отсутствует!")

    bot.infinity_polling(skip_pending=True, interval=1, timeout=20)
