from datetime import datetime, timedelta
import os
import sqlite3
from threading import Thread
from flask import Flask
import telebot
from telebot import types

TOKEN = "8797963662:AAGi6DZhW6Fl3bWwGMELIluOsx7F0xw0JdI"
bot = telebot.TeleBot(TOKEN)

# --- МИНИ-СЕРВЕР ДЛЯ RENDER ---
app = Flask("")


@app.route("/")
def home():
    return "Bot is active!"


def run_web():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))


def keep_alive():
    t = Thread(target=run_web)
    t.start()


# -----------------------------------------------------------------------

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
            text TEXT
        )
    """)
    conn.commit()
    conn.close()


init_db()


def load_global_homeworks():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT subject, date, text FROM homeworks")
    rows = cursor.fetchall()
    conn.close()

    storage = {sub: [] for sub in subjects_list}
    for subj, date, text in rows:
        if subj in storage:
            storage[subj].append({"date": date, "text": text})
    return storage


def add_homework_to_db(subject, date_val, text_val):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO homeworks (subject, date, text) VALUES (?, ?, ?)",
        (subject, date_val, text_val),
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
        user_data[user_id] = {
            "active": {
                sub: list(homework_storage.get(sub, [])) for sub in subjects_list
            },
            "completed": {sub: [] for sub in subjects_list},
            "current_msg_id": None,
            "target_subject": None,
            "step": None,
            "temp_date": None,
        }


def clean_old_homeworks(user_id):
    today = datetime.now().date()

    for state_type in ["active", "completed"]:
        for subj in subjects_list:
            filtered_tasks = []
            for t_info in user_data[user_id][state_type][subj]:
                try:
                    task_date = parse_flexible_date(t_info["date"])
                    if task_date >= today:
                        filtered_tasks.append(t_info)
                except ValueError:
                    filtered_tasks.append(t_info)
            user_data[user_id][state_type][subj] = filtered_tasks

    for subj in subjects_list:
        filtered_global = []
        for t_info in homework_storage[subj]:
            try:
                task_date = parse_flexible_date(t_info["date"])
                if task_date >= today:
                    filtered_global.append(t_info)
                else:
                    delete_homework_from_db(subj, t_info["date"], t_info["text"])
            except ValueError:
                filtered_global.append(t_info)
        homework_storage[subj] = filtered_global


def get_welcome_markup():
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn1 = types.InlineKeyboardButton("Всё Д/З", callback_data="btn_all_hw")
    btn2 = types.InlineKeyboardButton("Д/З на завтра", callback_data="btn_tomorrow")
    btn_done = types.InlineKeyboardButton(
        "Выполненное Д/З", callback_data="btn_done"
    )
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
    ):
        user_data[user_id]["target_subject"] = None
        user_data[user_id]["step"] = None
        user_data[user_id]["temp_date"] = None

    if call.data == "go_home":
        bot.answer_callback_query(call.id)
        bot.edit_message_text(
            "Добро пожаловать!👋\n\nЭто проводник по домашнему заданию. Что тебя интересует?📚",
            chat_id,
            message_id,
            reply_markup=get_welcome_markup(),
            parse_mode="Markdown",
        )
        user_data[user_id]["current_msg_id"] = message_id

    elif call.data == "btn_tomorrow":
        bot.answer_callback_query(call.id)

        for subj in subjects_list:
            global_tasks = homework_storage[subj]
            user_active = user_data[user_id]["active"][subj]
            user_completed = user_data[user_id]["completed"][subj]

            for task in global_tasks:
                if task not in user_active and task not in user_completed:
                    user_active.append(task)

        clean_old_homeworks(user_id)

        tomorrow_date_obj = datetime.now().date() + timedelta(days=1)

        text = "📌 **Домашняя работа на завтра:**\n\n"
        has_tomorrow_tasks = False
        markup = types.InlineKeyboardMarkup()

        for subj, tasks in user_data[user_id]["active"].items():
            for i, t_info in enumerate(tasks, 1):
                try:
                    task_date_obj = parse_flexible_date(t_info["date"])
                    is_tomorrow = task_date_obj == tomorrow_date_obj
                except ValueError:
                    is_tomorrow = False

                if is_tomorrow or t_info["date"].strip().lower() in [
                    "завтра",
                ]:
                    has_tomorrow_tasks = True
                    text += f"🔹 **Предмет**: {subj}\n"
                    text += f"📅 **Дата**: {t_info['date']}\n"
                    text += f"📝 **Задание**: {t_info['text']}\n\n"
                    markup.row(
                        types.InlineKeyboardButton(
                            f"✅ Сделано: {subj} ({i})",
                            callback_data=f"done_tom_{subj}_{i - 1}",
                        )
                    )

        if not has_tomorrow_tasks:
            text = "📌 **Домашняя работа на завтра:**\n\nНа завтра заданий нет! Отдыхай 🎉"

        markup.row(types.InlineKeyboardButton("🏠 На главную", callback_data="go_home"))
        bot.edit_message_text(
            text, chat_id, message_id, reply_markup=markup, parse_mode="Markdown"
        )

    elif call.data == "btn_all_hw":
        bot.answer_callback_query(call.id)

        for subj in subjects_list:
            global_tasks = homework_storage[subj]
            user_active = user_data[user_id]["active"][subj]
            user_completed = user_data[user_id]["completed"][subj]

            for task in global_tasks:
                if task not in user_active and task not in user_completed:
                    user_active.append(task)

        clean_old_homeworks(user_id)

        text = "📚 **Всё актуальное домашнее задание:**\n\n"
        has_tasks = False
        markup = types.InlineKeyboardMarkup()

        for subj, tasks in user_data[user_id]["active"].items():
            if tasks:
                has_tasks = True
                for i, t_info in enumerate(tasks, 1):
                    text += f"🔹 **Предмет**: {subj}\n"
                    text += f"📅 **Дата**: {t_info['date']}\n"
                    text += f"📝 **Задание**: {t_info['text']}\n\n"
                    markup.row(
                        types.InlineKeyboardButton(
                            f"✅ Сделано: {subj} ({i})",
                            callback_data=f"done_all_{subj}_{i - 1}",
                        )
                    )

        if not has_tasks:
            text = "📚 **Всё домашнее задание:**\n\nУра! Все задания выполнены 🎉"

        markup.row(types.InlineKeyboardButton("🏠 На главную", callback_data="go_home"))
        bot.edit_message_text(
            text, chat_id, message_id, reply_markup=markup, parse_mode="Markdown"
        )

    elif call.data == "btn_done":
        bot.answer_callback_query(call.id)
        clean_old_homeworks(user_id)

        text = "📁 **Выполненное домашнее задание:**\n\n"
        has_completed = False
        markup = types.InlineKeyboardMarkup()

        for subj, tasks in user_data[user_id]["completed"].items():
            if tasks:
                has_completed = True
                for i, t_info in enumerate(tasks, 1):
                    text += f"✅ **Предмет**: {subj}\n"
                    text += f"📅 **Дата**: {t_info['date']}\n"
                    text += f"📝 **Задание**: {t_info['text']}\n\n"
                    markup.row(
                        types.InlineKeyboardButton(
                            f"↩ Вернуть: {subj} ({i})",
                            callback_data=f"undone_{subj}_{i - 1}",
                        )
                    )

        if not has_completed:
            text = "📁 **Выполненное Д/З:**\n\nТы пока не отметил ни одного задания как выполненное."

        markup.row(types.InlineKeyboardButton("🏠 На главную", callback_data="go_home"))
        bot.edit_message_text(
            text, chat_id, message_id, reply_markup=markup, parse_mode="Markdown"
        )

    elif call.data.startswith("done_all_") or call.data.startswith("done_tom_"):
        is_tomorrow_view = call.data.startswith("done_tom_")
        prefix = "done_tom_" if is_tomorrow_view else "done_all_"

        bot.answer_callback_query(call.id, "Задание выполнено! ✅")
        parts = call.data.replace(prefix, "").rsplit("_", 1)
        if len(parts) == 2:
            subj = parts[0]
            try:
                idx = int(parts[1])
                active_list = user_data[user_id]["active"][subj]
                if idx < len(active_list):
                    task_info = active_list.pop(idx)
                    user_data[user_id]["completed"][subj].append(task_info)
            except ValueError:
                pass

        if is_tomorrow_view:
            tomorrow_date_obj = datetime.now().date() + timedelta(days=1)
            text = "📌 **Домашняя работа на завтра:**\n\n"
            has_tomorrow_tasks = False
            markup = types.InlineKeyboardMarkup()

            for subj, tasks in user_data[user_id]["active"].items():
                for i, t_info in enumerate(tasks, 1):
                    try:
                        task_date_obj = parse_flexible_date(t_info["date"])
                        is_tomorrow = task_date_obj == tomorrow_date_obj
                    except ValueError:
                        is_tomorrow = False

                    if is_tomorrow or t_info["date"].strip().lower() in [
                        "завтра",
                    ]:
                        has_tomorrow_tasks = True
                        text += f"🔹 **Предмет**: {subj}\n"
                        text += f"📅 **Дата**: {t_info['date']}\n"
                        text += f"📝 **Задание**: {t_info['text']}\n\n"
                        markup.row(
                            types.InlineKeyboardButton(
                                f"✅ Сделано: {subj} ({i})",
                                callback_data=f"done_tom_{subj}_{i - 1}",
                            )
                        )

            if not has_tomorrow_tasks:
                text = "📌 **Домашняя работа на завтра:**\n\nНа завтра заданий нет! Отдыхай 🎉"

            markup.row(
                types.InlineKeyboardButton("🏠 На главную", callback_data="go_home")
            )
            bot.edit_message_text(
                text, chat_id, message_id, reply_markup=markup, parse_mode="Markdown"
            )
        else:
            text = "📚 **Всё актуальное домашнее задание:**\n\n"
            has_tasks = False
            markup = types.InlineKeyboardMarkup()

            for s, tasks in user_data[user_id]["active"].items():
                if tasks:
                    has_tasks = True
                    for i, t_info in enumerate(tasks, 1):
                        text += f"🔹 **Предмет**: {s}\n"
                        text += f"📅 **Дата**: {t_info['date']}\n"
                        text += f"📝 **Задание**: {t_info['text']}\n\n"
                        markup.row(
                            types.InlineKeyboardButton(
                                f"✅ Сделано: {s} ({i})",
                                callback_data=f"done_all_{s}_{i - 1}",
                            )
                        )

            if not has_tasks:
                text = "📚 **Всё домашнее задание:**\n\nУра! Все задания выполнены 🎉"

            markup.row(
                types.InlineKeyboardButton("🏠 На главную", callback_data="go_home")
            )
            bot.edit_message_text(
                text, chat_id, message_id, reply_markup=markup, parse_mode="Markdown"
            )

    elif call.data.startswith("undone_"):
        bot.answer_callback_query(call.id, "Задание возвращено в активные! ↩️")
        parts = call.data.replace("undone_", "").rsplit("_", 1)
        if len(parts) == 2:
            subj = parts[0]
            try:
                idx = int(parts[1])
                completed_list = user_data[user_id]["completed"][subj]
                if idx < len(completed_list):
                    task_info = completed_list.pop(idx)
                    user_data[user_id]["active"][subj].append(task_info)
            except ValueError:
                pass

        text = "📁 **Выполненное домашнее задание:**\n\n"
        has_completed = False
        markup = types.InlineKeyboardMarkup()

        for s, tasks in user_data[user_id]["completed"].items():
            if tasks:
                has_completed = True
                for i, t_info in enumerate(tasks, 1):
                    text += f"✅ **Предмет**: {s}\n"
                    text += f"📅 **Дата**: {t_info['date']}\n"
                    text += f"📝 **Задание**: {t_info['text']}\n\n"
                    markup.row(
                        types.InlineKeyboardButton(
                            f"↩️ Вернуть: {s} ({i})",
                            callback_data=f"undone_{s}_{i - 1}",
                        )
                    )

        if not has_completed:
            text = "📁 **Выполненное Д/З:**\n\nТы пока не отметил ни одного задания как выполненное."

        markup.row(types.InlineKeyboardButton("🏠 На главную", callback_data="go_home"))
        bot.edit_message_text(
            text, chat_id, message_id, reply_markup=markup, parse_mode="Markdown"
        )

    elif call.data == "choose_subject":
        bot.answer_callback_query(call.id)
        user_data[user_id]["step"] = None
        user_data[user_id]["target_subject"] = None

        markup = types.InlineKeyboardMarkup()
        iterator = iter(subjects_list)
        for subj1 in iterator:
            try:
                subj2 = next(iterator)
                markup.add(
                    types.InlineKeyboardButton(subj1, callback_data=f"sub_{subj1}"),
                    types.InlineKeyboardButton(subj2, callback_data=f"sub_{subj2}"),
                )
            except StopIteration:
                markup.add(
                    types.InlineKeyboardButton(subj1, callback_data=f"sub_{subj1}")
                )

        markup.row(types.InlineKeyboardButton("🏠 На главную", callback_data="go_home"))
        bot.edit_message_text(
            "📚 Выбери предмет, для которого хочешь записать Д/З:",
            chat_id,
            message_id,
            reply_markup=markup,
        )

    elif call.data.startswith("sub_"):
        bot.answer_callback_query(call.id)
        selected_subject = call.data.replace("sub_", "")

        user_data[user_id]["target_subject"] = selected_subject
        user_data[user_id]["step"] = "waiting_date"

        markup = types.InlineKeyboardMarkup()
        markup.row(types.InlineKeyboardButton("🏠 На главную", callback_data="go_home"))

        prompt_text = f"📅 Введи **дату сдачи** для предмета **{selected_subject}** (можно без нулей, например `9.9` или `9.9.2026`):"
        bot.edit_message_text(
            prompt_text,
            chat_id,
            message_id,
            reply_markup=markup,
            parse_mode="Markdown",
        )

    elif call.data == "starosta_delete_menu":
        bot.answer_callback_query(call.id)

        text = "🗑 **Выберите задание для удаления:**\n\n"
        markup = types.InlineKeyboardMarkup()
        has_any_tasks = False

        for subj in subjects_list:
            tasks = homework_storage[subj]
            if tasks:
                has_any_tasks = True
                for i, t_info in enumerate(tasks, 1):
                    text += f"🔹 **{subj}** ({t_info['date']}): {t_info['text']}\n"
                    markup.row(
                        types.InlineKeyboardButton(
                            f"❌ Удалить: {subj} ({i})",
                            callback_data=f"del_{subj}_{i - 1}",
                        )
                    )

        if not has_any_tasks:
            text = "🗑 **Удаление ДЗ:**\n\nВ базе пока нет активных заданий для удаления."

        markup.row(
            types.InlineKeyboardButton(
                "🔙 Назад в меню старосты", callback_data="back_to_starosta"
            )
        )
        markup.row(types.InlineKeyboardButton("🏠 На главную", callback_data="go_home"))
        bot.edit_message_text(
            text, chat_id, message_id, reply_markup=markup, parse_mode="Markdown"
        )

    elif call.data.startswith("del_"):
        bot.answer_callback_query(call.id, "Задание удалено! 🗑")
        parts = call.data.replace("del_", "").rsplit("_", 1)
        if len(parts) == 2:
            subj = parts[0]
            try:
                idx = int(parts[1])
                if idx < len(homework_storage[subj]):
                    removed_task = homework_storage[subj].pop(idx)
                    delete_homework_from_db(
                        subj, removed_task["date"], removed_task["text"]
                    )

                for uid in user_data:
                    if idx < len(user_data[uid]["active"][subj]):
                        user_data[uid]["active"][subj].pop(idx)
                    elif idx < len(user_data[uid]["completed"][subj]):
                        user_data[uid]["completed"][subj].pop(idx)
            except ValueError:
                pass

        text = "🗑 **Выберите задание для удаления:**\n\n"
        markup = types.InlineKeyboardMarkup()
        has_any_tasks = False

        for subj in subjects_list:
            tasks = homework_storage[subj]
            if tasks:
                has_any_tasks = True
                for i, t_info in enumerate(tasks, 1):
                    text += f"🔹 **{subj}** ({t_info['date']}): {t_info['text']}\n"
                    markup.row(
                        types.InlineKeyboardButton(
                            f"❌ Удалить: {subj} ({i})",
                            callback_data=f"del_{subj}_{i - 1}",
                        )
                    )

        if not has_any_tasks:
            text = "🗑 **Удаление ДЗ:**\n\nВ базе больше нет заданий."

        markup.row(
            types.InlineKeyboardButton(
                "🔙 Назад в меню старосты", callback_data="back_to_starosta"
            )
        )
        markup.row(types.InlineKeyboardButton("🏠 На главную", callback_data="go_home"))
        bot.edit_message_text(
            text, chat_id, message_id, reply_markup=markup, parse_mode="Markdown"
        )

    elif call.data == "back_to_starosta":
        bot.answer_callback_query(call.id)
        starosta_text = "👨‍🏫 Добро пожаловать в режим старосты!"
        markup = types.InlineKeyboardMarkup()
        markup.row(
            types.InlineKeyboardButton(
                "Добавить предмет / ДЗ", callback_data="choose_subject"
            )
        )
        markup.row(
            types.InlineKeyboardButton("🗑 Удалить ДЗ", callback_data="starosta_delete_menu")
        )
        markup.row(types.InlineKeyboardButton("🏠 На главную", callback_data="go_home"))
        bot.edit_message_text(starosta_text, chat_id, message_id, reply_markup=markup)


@bot.message_handler(func=lambda message: True)
def handle_text(message):
    SECRET_CODE = "1234"
    user_id = message.from_user.id
    init_user(user_id)
    clean_old_homeworks(user_id)

    chat_id = message.chat.id
    text = message.text

    try:
        bot.delete_message(chat_id, message.message_id)
    except Exception:
        pass

    if text == SECRET_CODE:
        user_data[user_id]["target_subject"] = None
        user_data[user_id]["step"] = None
        starosta_text = "👨‍🏫 Добро пожаловать в режим старосты!"
        markup = types.InlineKeyboardMarkup()
        markup.row(
            types.InlineKeyboardButton(
                "Добавить предмет / ДЗ", callback_data="choose_subject"
            )
        )
        markup.row(
            types.InlineKeyboardButton("🗑 Удалить ДЗ", callback_data="starosta_delete_menu")
        )
        markup.row(types.InlineKeyboardButton("🏠 На главную", callback_data="go_home"))

        menu_id = user_data[user_id].get("current_msg_id")
        if menu_id:
            try:
                bot.edit_message_text(
                    starosta_text, chat_id, menu_id, reply_markup=markup
                )
                return
            except Exception:
                pass

        msg = bot.send_message(chat_id, starosta_text, reply_markup=markup)
        user_data[user_id]["current_msg_id"] = msg.message_id

    elif user_data[user_id].get("step") == "waiting_date":
        date_text = text.strip()

        try:
            parsed_date = parse_flexible_date(date_text)

            if parsed_date < datetime.now().date():
                error_text = "❌ **Ошибка!** Нельзя добавить домашку на прошедший день. Введите актуальную дату:"
                markup = types.InlineKeyboardMarkup()
                markup.row(
                    types.InlineKeyboardButton("🏠 На главную", callback_data="go_home")
                )

                menu_id = user_data[user_id].get("current_msg_id")
                if menu_id:
                    try:
                        bot.edit_message_text(
                            error_text,
                            chat_id,
                            menu_id,
                            reply_markup=markup,
                            parse_mode="Markdown",
                        )
                        return
                    except Exception:
                        pass
                msg = bot.send_message(
                    chat_id, error_text, reply_markup=markup, parse_mode="Markdown"
                )
                user_data[user_id]["current_msg_id"] = msg.message_id
                return

        except ValueError:
            error_text = "❌ **Неверный формат даты.** Введите в формате `ДД.ММ.ГГГГ` или `ДД.ММ` (можно без нулей):"
            markup = types.InlineKeyboardMarkup()
            markup.row(
                types.InlineKeyboardButton("🏠 На главную", callback_data="go_home")
            )

            menu_id = user_data[user_id].get("current_msg_id")
            if menu_id:
                try:
                    bot.edit_message_text(
                        error_text,
                        chat_id,
                        menu_id,
                        reply_markup=markup,
                        parse_mode="Markdown",
                    )
                    return
                except Exception:
                    pass
            msg = bot.send_message(
                chat_id, error_text, reply_markup=markup, parse_mode="Markdown"
            )
            user_data[user_id]["current_msg_id"] = msg.message_id
            return

        user_data[user_id]["temp_date"] = text
        user_data[user_id]["step"] = "waiting_text"

        prompt_text = f"📅 Дата **{text}** сохранена.\n\nТеперь введи **текст домашнего задания** следующим сообщением:"
        markup = types.InlineKeyboardMarkup()
        markup.row(types.InlineKeyboardButton("🏠 На главную", callback_data="go_home"))

        menu_id = user_data[user_id].get("current_msg_id")
        if menu_id:
            try:
                bot.edit_message_text(
                    prompt_text,
                    chat_id,
                    menu_id,
                    reply_markup=markup,
                    parse_mode="Markdown",
                )
                return
            except Exception:
                pass

        msg = bot.send_message(
            chat_id, prompt_text, reply_markup=markup, parse_mode="Markdown"
        )
        user_data[user_id]["current_msg_id"] = msg.message_id

    elif user_data[user_id].get("step") == "waiting_text":
        subject = user_data[user_id]["target_subject"]
        date_val = user_data[user_id]["temp_date"]

        user_data[user_id]["target_subject"] = None
        user_data[user_id]["step"] = None
        user_data[user_id]["temp_date"] = None

        task_info = {"date": date_val, "text": text}

        add_homework_to_db(subject, date_val, text)
        homework_storage[subject].append(task_info)

        for uid in user_data:
            user_data[uid]["active"][subject].append(task_info)

        success_text = f"✅ **ДЗ успешно добавлено!**\n\nПредмет: {subject}\nДата: {date_val}\nЗадание: {text}"

        markup = types.InlineKeyboardMarkup()
        markup.row(types.InlineKeyboardButton("🏠 На главную", callback_data="go_home"))

        menu_id = user_data[user_id].get("current_msg_id")
        if menu_id:
            try:
                bot.edit_message_text(
                    success_text,
                    chat_id,
                    menu_id,
                    reply_markup=markup,
                    parse_mode="Markdown",
                )
                return
            except Exception:
                pass

        msg = bot.send_message(
            chat_id, success_text, reply_markup=markup, parse_mode="Markdown"
        )
        user_data[user_id]["current_msg_id"] = msg.message_id

    else:
        pass


if __name__ == "__main__":
    keep_alive()
    print("Бот и веб-сервер запущены...")
    bot.infinity_polling(skip_pending=True)
    
