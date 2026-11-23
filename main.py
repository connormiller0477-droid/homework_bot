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
    prompt_text = (
        f"📅 Дата {text} сохранена.\n\nТеперь отправь текст домашнего задания"
        " (можно прикрепить фото, видео или документ):"
    )
    markup = types.InlineKeyboardMarkup()
    markup.row(types.InlineKeyboardButton("🏠 На главную", callback_data="go_home"))

    menu_id = user_data[user_id].get("current_msg_id")
    if menu_id:
      try:
        bot.edit_message_text(
            prompt_text, chat_id, menu_id, reply_markup=markup
        )
        return
      except Exception as e:
        if "message is not modified" not in str(e):
          pass
    msg = bot.send_message(chat_id, prompt_text, reply_markup=markup)
    user_data[user_id]["current_msg_id"] = msg.message_id
    return

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

    success_text = (
        f"✅ ДЗ успешно добавлено!\n\nПредмет: {subject}\nДата:"
        f" {date_val}\nЗадание: {text}"
    )
    markup = types.InlineKeyboardMarkup()
    markup.row(types.InlineKeyboardButton("🏠 На главную", callback_data="go_home"))

    menu_id = user_data[user_id]["current_msg_id"]
    if menu_id:
      try:
        bot.edit_message_text(
            success_text, chat_id, menu_id, reply_markup=markup
        )
        return
      except Exception as e:
        if "message is not modified" not in str(e):
          pass
    msg = bot.send_message(chat_id, success_text, reply_markup=markup)
    user_data[user_id]["current_msg_id"] = msg.message_id
    return

  try:
    bot.delete_message(chat_id, message.message_id)
  except Exception:
    pass


if __name__ == "__main__":
  print("Бот запущен с моделью gemini-3.5-flash-lite...")
  if client:
    try:
      test_resp = client.models.generate_content(
          model="gemini-3.5-flash-lite",
          contents='Ответь словом "ОК", если видишь этот запрос',
      )
      print(f"ТЕСТ GEMINI API УСПЕШЕН: {test_resp.text}")
    except Exception as err:
      print(f"ОШИБКА ТЕСТА GEMINI API: {err}")
  else:
    print("ТЕСТ ОТМЕНЕН: Ключ GEMINI_API_KEY отсутствует!")

  bot.infinity_polling(skip_pending=True, interval=1, timeout=20)
