from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
import hashlib

def safe_callback_data(data: str, max_len: int = 64) -> str:
    """Проверка длины callback_data. Если слишком длинная, заменяет на md5 хеш."""
    if len(data.encode('utf-8')) > max_len:
        print(f"[WARN] callback_data слишком длинная ({len(data.encode('utf-8'))} байт): {data}")
        data = hashlib.md5(data.encode('utf-8')).hexdigest()
        print(f"[INFO] Заменено на хеш: {data}")
    return data

# Пример "опасного" пути
test_data = "C:\\Users\\Администратор\\server_files\\server_files_bot\\Tasks\\Актуальные\\Проект X\\Стадия Y\\Задание Z"

# Проверяем
safe_data = safe_callback_data(test_data)
print("callback_data готово к использованию:", safe_data)

# Создаем тестовую клавиатуру
kb = InlineKeyboardMarkup(row_width=1)
kb.add(InlineKeyboardButton(text="Удалить", callback_data=safe_data))

print("InlineKeyboardMarkup создан успешно.")
