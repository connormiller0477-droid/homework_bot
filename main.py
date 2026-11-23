import io
import json
import os
import socket
import sqlite3
import threading
from datetime import datetime, timedelta

from google import genai
from google.genai import types as genai_types
from PIL import Image
import telebot
from telebot import types


# --- СТАБИЛЬНЫЙ МИНИ-СЕРВЕР ДЛЯ RENDER (В ОТДЕЛЬНОМ ПОТОКЕ СОКЕТОВ) ---
def run_web_server():
  port = int(os.environ.get("PORT", 10000))
  server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
  server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
  server_socket.bind(("0.0.0.0", port))
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
