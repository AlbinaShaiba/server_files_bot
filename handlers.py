from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from models import User, FileInfo, Subscription
import os
import asyncio
from datetime import datetime
from config import FILES_ROOT

# Создаем роутер
router = Router()

# Константа для пагинации
ITEMS_PER_PAGE = 6

# ---------------
# FSM State Group
# ---------------
class SubscribeState(StatesGroup):
    order = State()
    stage = State()
    task = State()
    file = State()

# Клавиатура с командами
main_menu_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="/subscribe")],
        [KeyboardButton(text="/my_subs")],
        [KeyboardButton(text="/refresh_files")]
    ],
    resize_keyboard=True
)

@router.message(Command("start"))
async def cmd_start(message: Message, session: AsyncSession):
    stmt = select(User).where(User.tg_id == message.from_user.id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    
    if not user:
        # Создаем нового пользователя с полной информацией
        user = User(
            tg_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name
        )
        session.add(user)
        await session.commit()
        print(f"➕ Новый пользователь: {message.from_user.full_name} (@{message.from_user.username})")
    else:
        # Обновляем информацию о существующем пользователе
        user.username = message.from_user.username
        user.first_name = message.from_user.first_name
        user.last_name = message.from_user.last_name
        await session.commit()
        print(f"🔄 Обновлена информация пользователя: {message.from_user.full_name} (@{message.from_user.username})")

    await message.answer(
        "👋 Привет! Я бот для подписки на обновления файлов.\n\n"
        "Доступные команды:\n"
        "📁 /subscribe — подписаться на файл\n"
        "📋 /my_subs — посмотреть подписки\n"
        "🔄 /refresh_files — обновить список файлов",
        reply_markup=main_menu_kb
    )

# ---------------
# Сканирование файлов
# ---------------
async def scan_and_update_files(session: AsyncSession):
    """Сканирует файловую систему и обновляет информацию в БД"""
    if not os.path.exists(FILES_ROOT):
        print(f"⚠️ Директория не найдена: {FILES_ROOT}")
        return
    
    try:
        print(f"🔍 Начинаю сканирование папки: {FILES_ROOT}")
        added_files = 0
        updated_files = 0
        
        for order in os.listdir(FILES_ROOT):
            order_path = os.path.join(FILES_ROOT, order)
            if not os.path.isdir(order_path):
                print(f"  📁 Пропущен файл (не папка): {order}")
                continue
            
            print(f"  📂 Заказ: {order}")
            
            for stage in os.listdir(order_path):
                stage_path = os.path.join(order_path, stage)
                if not os.path.isdir(stage_path):
                    print(f"    📁 Пропущен файл (не папка): {stage}")
                    continue
                
                print(f"    🏗 Стадия: {stage}")
                
                for task in os.listdir(stage_path):
                    task_path = os.path.join(stage_path, task)
                    if not os.path.isdir(task_path):
                        print(f"      📁 Пропущен файл (не папка): {task}")
                        continue
                    
                    print(f"      📝 Задание: {task}")
                    
                    # Сканируем файлы в папке задания
                    try:
                        items = os.listdir(task_path)
                        print(f"        📁 Найдено {len(items)} элементов в папке")
                        
                        for filename in items:
                            file_path = os.path.join(task_path, filename)
                            if not os.path.isfile(file_path):
                                print(f"          📁 Пропущена папка: {filename}")
                                continue
                            
                            # Пропускаем временные файлы
                            if filename.startswith('~$') or filename.startswith('.'):
                                print(f"          🚫 Пропущен временный файл: {filename}")
                                continue
                            
                            print(f"        📄 Файл: {filename}")
                            
                            # Получаем информацию о файле
                            try:
                                stat = os.stat(file_path)
                                last_modified = datetime.fromtimestamp(stat.st_mtime)
                                size = stat.st_size
                                print(f"          📊 Размер: {size} байт, Изменен: {last_modified}")
                            except Exception as e:
                                print(f"          ❌ Ошибка получения информации о файле: {e}")
                                continue
                            
                            # Проверяем, существует ли файл в БД
                            stmt = select(FileInfo).where(FileInfo.path == file_path)
                            result = await session.execute(stmt)
                            existing_file = result.scalar_one_or_none()
                            
                            if existing_file:
                                # Обновляем информацию о файле
                                existing_file.last_modified = last_modified
                                existing_file.size = size
                                updated_files += 1
                                print(f"          🔄 Обновлен файл в БД")
                            else:
                                # Добавляем новый файл
                                new_file = FileInfo(
                                    order=order,
                                    stage=stage,
                                    task=task,
                                    filename=filename,
                                    path=file_path,
                                    last_modified=last_modified,
                                    size=size
                                )
                                session.add(new_file)
                                added_files += 1
                                print(f"          ➕ Добавлен новый файл в БД")
                    except Exception as e:
                        print(f"        ❌ Ошибка при сканировании папки {task_path}: {e}")
        
        await session.commit()
        print(f"✅ Сканирование завершено. Добавлено: {added_files}, Обновлено: {updated_files}")
        
    except Exception as e:
        print(f"❌ Ошибка при сканировании файлов: {e}")
        import traceback
        traceback.print_exc()
        await session.rollback()

# ---------------
# Команда: обновить файлы вручную
# ---------------
@router.message(Command("refresh_files"))
async def refresh_files_command(message: Message, session: AsyncSession):
    await message.answer("🔄 Обновляю список файлов...")
    await scan_and_update_files(session)
    await message.answer("✅ Файлы были обновлены из файловой системы.")

# ---------------
# Start /subscribe
# ---------------
@router.message(Command("subscribe"))
async def start_subscription(message: Message, state: FSMContext, session: AsyncSession):
    await state.clear()

    # Сохраняем/ищем пользователя
    stmt = select(User).where(User.tg_id == message.from_user.id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        user = User(
            tg_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name
        )
        session.add(user)
        await session.commit()

    # Выбор заказа
    if not os.path.exists(FILES_ROOT):
        await message.answer("❌ Директория с файлами не найдена. Проверьте настройки.")
        return
    
    orders = []
    try:
        for item in os.listdir(FILES_ROOT):
            item_path = os.path.join(FILES_ROOT, item)
            if os.path.isdir(item_path):
                orders.append(item)
    except Exception as e:
        await message.answer(f"❌ Ошибка при чтении директории: {e}")
        return
    
    if not orders:
        await message.answer(
            "📂 Нет доступных заказов. Сначала обновите список файлов командой /refresh_files"
        )
        return
    
    # Пагинация для заказов
    await show_orders_page(message, orders, 0, state)

async def show_orders_page(message: Message, orders: list, page: int, state: FSMContext):
    """Показать страницу с заказами"""
    total_pages = (len(orders) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    start_idx = page * ITEMS_PER_PAGE
    end_idx = min(start_idx + ITEMS_PER_PAGE, len(orders))
    current_orders = sorted(orders, key=lambda x: x.zfill(10) if x.isdigit() else x)[start_idx:end_idx]
    
    kb = InlineKeyboardBuilder()
    for order in current_orders:
        kb.button(text=order, callback_data=f"order:{order}")
    
    # Кнопки пагинации
    pagination_row = []
    if page > 0:
        pagination_row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"orders_page:{page-1}"))
    if page < total_pages - 1:
        pagination_row.append(InlineKeyboardButton(text="➡️ Далее", callback_data=f"orders_page:{page+1}"))
    
    if pagination_row:
        kb.row(*pagination_row)
    
    kb.adjust(2)
    
    page_info = f" (страница {page+1}/{total_pages})" if total_pages > 1 else ""
    await message.answer(f"🔢 Выберите номер заказа{page_info}:", reply_markup=kb.as_markup())
    await state.set_state(SubscribeState.order)

@router.callback_query(lambda c: c.data.startswith("orders_page:"))
async def handle_orders_pagination(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Обработка пагинации заказов"""
    page = int(callback.data.split(":")[1])
    
    # Получаем список заказов
    orders = []
    if os.path.exists(FILES_ROOT):
        try:
            for item in os.listdir(FILES_ROOT):
                item_path = os.path.join(FILES_ROOT, item)
                if os.path.isdir(item_path):
                    orders.append(item)
        except Exception as e:
            await callback.message.edit_text(f"❌ Ошибка при чтении директории: {e}")
            return
    
    await callback.message.delete()
    await show_orders_page(callback.message, orders, page, state)

# ---------------
# Выбор стадии
# ---------------
@router.callback_query(lambda c: c.data.startswith("order:"))
async def select_order(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    order = callback.data.split(":")[1]
    await state.update_data(order=order)
    
    # Получаем путь к папке заказа
    order_path = os.path.join(FILES_ROOT, order)
    
    if not os.path.exists(order_path):
        await callback.message.edit_text("❌ Папка заказа не найдена")
        return

    # Получаем список стадий
    stages = []
    try:
        for item in os.listdir(order_path):
            item_path = os.path.join(order_path, item)
            if os.path.isdir(item_path):
                stages.append(item)
    except Exception as e:
        await callback.message.edit_text(f"❌ Ошибка при чтении папки заказа: {e}")
        return
    
    if not stages:
        await callback.message.edit_text("❌ Нет доступных стадий для этого заказа")
        return
    
    # Пагинация для стадий
    await state.update_data(stages_list=stages)
    await show_stages_page(callback.message, callback.from_user.id, stages, 0, state)

async def show_stages_page(message: Message, user_id: int, stages: list, page: int, state: FSMContext):
    """Показать страницу со стадиями"""
    total_pages = (len(stages) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    start_idx = page * ITEMS_PER_PAGE
    end_idx = min(start_idx + ITEMS_PER_PAGE, len(stages))
    current_stages = sorted(stages)[start_idx:end_idx]
    
    kb = InlineKeyboardBuilder()
    for stage in current_stages:
        kb.button(text=stage, callback_data=f"stage:{stage}")
    
    # Кнопки пагинации
    pagination_row = []
    if page > 0:
        pagination_row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"stages_page:{page-1}"))
    if page < total_pages - 1:
        pagination_row.append(InlineKeyboardButton(text="➡️ Далее", callback_data=f"stages_page:{page+1}"))
    
    if pagination_row:
        kb.row(*pagination_row)
    
    kb.adjust(2)
    
    page_info = f" (страница {page+1}/{total_pages})" if total_pages > 1 else ""
    await message.edit_text(f"🏗 Выберите стадию{page_info}:", reply_markup=kb.as_markup())

@router.callback_query(lambda c: c.data.startswith("stages_page:"))
async def handle_stages_pagination(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Обработка пагинации стадий"""
    page = int(callback.data.split(":")[1])
    
    # Получаем список стадий из состояния
    data = await state.get_data()
    stages = data.get("stages_list", [])
    
    await show_stages_page(callback.message, callback.from_user.id, stages, page, state)

# ---------------
# Выбор задания
# ---------------
@router.callback_query(lambda c: c.data.startswith("stage:"))
async def select_stage(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    stage = callback.data.split(":")[1]
    await state.update_data(stage=stage)
    
    # Получаем список заданий
    data = await state.get_data()
    stage_path = os.path.join(FILES_ROOT, data["order"], stage)
    
    if not os.path.exists(stage_path):
        await callback.message.edit_text("❌ Папка стадии не найдена")
        return

    # Получаем список заданий
    tasks = []
    try:
        for item in os.listdir(stage_path):
            item_path = os.path.join(stage_path, item)
            if os.path.isdir(item_path):
                tasks.append(item)
    except Exception as e:
        await callback.message.edit_text(f"❌ Ошибка при чтении папки стадии: {e}")
        return
    
    if not tasks:
        await callback.message.edit_text("❌ Нет доступных заданий для этой стадии")
        return
    
    # Пагинация для заданий
    await state.update_data(tasks_list=tasks)
    await show_tasks_page(callback.message, callback.from_user.id, tasks, 0, state)

async def show_tasks_page(message: Message, user_id: int, tasks: list, page: int, state: FSMContext):
    """Показать страницу с заданиями"""
    total_pages = (len(tasks) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    start_idx = page * ITEMS_PER_PAGE
    end_idx = min(start_idx + ITEMS_PER_PAGE, len(tasks))
    current_tasks = sorted(tasks)[start_idx:end_idx]
    
    kb = InlineKeyboardBuilder()
    for task in current_tasks:
        kb.button(text=task, callback_data=f"task:{task}")
    
    # Кнопки пагинации
    pagination_row = []
    if page > 0:
        pagination_row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"tasks_page:{page-1}"))
    if page < total_pages - 1:
        pagination_row.append(InlineKeyboardButton(text="➡️ Далее", callback_data=f"tasks_page:{page+1}"))
    
    if pagination_row:
        kb.row(*pagination_row)
    
    kb.adjust(1)
    
    page_info = f" (страница {page+1}/{total_pages})" if total_pages > 1 else ""
    await message.edit_text(f"📝 Выберите задание{page_info}:", reply_markup=kb.as_markup())

@router.callback_query(lambda c: c.data.startswith("tasks_page:"))
async def handle_tasks_pagination(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Обработка пагинации заданий"""
    page = int(callback.data.split(":")[1])
    
    # Получаем список заданий из состояния
    data = await state.get_data()
    tasks = data.get("tasks_list", [])
    
    await show_tasks_page(callback.message, callback.from_user.id, tasks, page, state)

# ---------------
# Выбор файла
# ---------------
@router.callback_query(lambda c: c.data.startswith("task:"))
async def select_task(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    task = callback.data.split(":")[1]
    await state.update_data(task=task)
    data = await state.get_data()
    
    # Получаем путь к папке задания
    task_path = os.path.join(FILES_ROOT, data["order"], data["stage"], task)
    
    print(f"🔍 Проверка папки задания: {task_path}")
    
    if not os.path.exists(task_path):
        await callback.message.edit_text("❌ Папка задания не найдена")
        return

    # Принудительно сканируем файлы в этой папке
    try:
        print(f"🔄 Принудительное сканирование папки: {task_path}")
        added_files = 0
        
        # Получаем список файлов
        items = os.listdir(task_path)
        print(f"📁 Найдено {len(items)} элементов")
        
        for item in items:
            file_path = os.path.join(task_path, item)
            if not os.path.isfile(file_path):
                print(f"🚫 Пропущена папка: {item}")
                continue
            
            # Пропускаем временные файлы
            if item.startswith('~$') or item.startswith('.'):
                print(f"🚫 Пропущен временный файл: {item}")
                continue
            
            print(f"📄 Обрабатываю файл: {item}")
            
            try:
                stat = os.stat(file_path)
                last_modified = datetime.fromtimestamp(stat.st_mtime)
                size = stat.st_size
            except Exception as e:
                print(f"❌ Ошибка получения информации о файле {item}: {e}")
                continue
            
            # Проверяем, существует ли файл в БД
            stmt = select(FileInfo).where(FileInfo.path == file_path)
            result = await session.execute(stmt)
            existing_file = result.scalar_one_or_none()
            
            if existing_file:
                # Обновляем информацию о файле
                existing_file.last_modified = last_modified
                existing_file.size = size
                print(f"🔄 Обновлен файл в БД: {item}")
            else:
                # Добавляем новый файл
                new_file = FileInfo(
                    order=data["order"],
                    stage=data["stage"],
                    task=task,
                    filename=item,
                    path=file_path,
                    last_modified=last_modified,
                    size=size
                )
                session.add(new_file)
                added_files += 1
                print(f"➕ Добавлен новый файл в БД: {item}")
        
        if added_files > 0:
            await session.commit()
            print(f"✅ Добавлено {added_files} новых файлов в БД")
        
    except Exception as e:
        print(f"❌ Ошибка при сканировании папки: {e}")
        import traceback
        traceback.print_exc()
        await session.rollback()

    # Получаем список файлов в папке задания
    files_in_folder = []
    try:
        for item in os.listdir(task_path):
            item_path = os.path.join(task_path, item)
            if os.path.isfile(item_path):
                # Пропускаем временные файлы
                if not (item.startswith('~$') or item.startswith('.')):
                    files_in_folder.append(item)
    except Exception as e:
        await callback.message.edit_text(f"❌ Ошибка при чтении папки задания: {e}")
        return
    
    print(f"📊 Файлов в папке: {len(files_in_folder)}")
    if files_in_folder:
        print(f"📄 Файлы: {', '.join(files_in_folder)}")
    
    if not files_in_folder:
        # Показываем содержимое папки для отладки
        all_items = []
        try:
            all_items = os.listdir(task_path)
        except:
            pass
        
        if all_items:
            item_list = "\n".join([f"• {item}" for item in all_items[:10]])
            await callback.message.edit_text(
                f"❌ Нет подходящих файлов для подписки.\n\n"
                f"Содержимое папки ({len(all_items)} элементов):\n{item_list}"
            )
        else:
            await callback.message.edit_text("❌ Папка пуста")
        return
    
    # Получаем файлы из БД для этого задания
    stmt = select(FileInfo).where(
        FileInfo.order == data["order"],
        FileInfo.stage == data["stage"],
        FileInfo.task == task,
        FileInfo.filename.in_(files_in_folder)
    )
    result = await session.execute(stmt)
    db_files = result.scalars().all()
    
    print(f"💾 Файлов в БД для этого задания: {len(db_files)}")
    
    if not db_files:
        file_list = "\n".join([f"• {f}" for f in files_in_folder[:10]])
        await callback.message.edit_text(
            f"❌ Нет файлов в базе данных для этого задания.\n"
            f"Попробуйте обновить файлы командой /refresh_files\n\n"
            f"Файлы в папке:\n{file_list}"
        )
        return
    
    # Пагинация для файлов
    file_list = [(file.id, file.filename) for file in db_files]
    await state.update_data(files_list=file_list)
    await show_files_page(callback.message, callback.from_user.id, file_list, 0, state)

async def show_files_page(message: Message, user_id: int, files: list, page: int, state: FSMContext):
    """Показать страницу с файлами"""
    total_pages = (len(files) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    start_idx = page * ITEMS_PER_PAGE
    end_idx = min(start_idx + ITEMS_PER_PAGE, len(files))
    current_files = files[start_idx:end_idx]
    
    kb = InlineKeyboardBuilder()
    for file_id, filename in current_files:
        kb.button(text=filename, callback_data=f"file:{file_id}")
    
    # Кнопки пагинации
    pagination_row = []
    if page > 0:
        pagination_row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"files_page:{page-1}"))
    if page < total_pages - 1:
        pagination_row.append(InlineKeyboardButton(text="➡️ Далее", callback_data=f"files_page:{page+1}"))
    
    if pagination_row:
        kb.row(*pagination_row)
    
    kb.adjust(1)
    
    page_info = f" (страница {page+1}/{total_pages})" if total_pages > 1 else ""
    await message.edit_text(f"📄 Выберите файл для подписки{page_info}:", reply_markup=kb.as_markup())
    await state.set_state(SubscribeState.file)

@router.callback_query(lambda c: c.data.startswith("files_page:"))
async def handle_files_pagination(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Обработка пагинации файлов"""
    page = int(callback.data.split(":")[1])
    
    # Получаем список файлов из состояния
    data = await state.get_data()
    files = data.get("files_list", [])
    
    await show_files_page(callback.message, callback.from_user.id, files, page, state)

# ---------------
# Подписка на файл
# ---------------
@router.callback_query(lambda c: c.data.startswith("file:"))
async def subscribe_file(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    try:
        file_id = int(callback.data.split(":")[1])
        user_id = callback.from_user.id

        # Получаем пользователя
        stmt = select(User).where(User.tg_id == user_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        
        if not user:
            user = User(
                tg_id=user_id,
                username=callback.from_user.username if callback.from_user else None,
                first_name=callback.from_user.first_name if callback.from_user else None,
                last_name=callback.from_user.last_name if callback.from_user else None
            )
            session.add(user)
            await session.commit()

        # Получаем файл
        stmt = select(FileInfo).where(FileInfo.id == file_id)
        result = await session.execute(stmt)
        file = result.scalar_one()
        
        if not file:
            await callback.message.edit_text("❌ Файл не найден")
            return

        # Проверяем, есть ли уже подписка
        stmt = select(Subscription).where(
            Subscription.user_id == user.id,
            Subscription.file_path == file.path
        )
        result = await session.execute(stmt)
        sub = result.scalar_one_or_none()

        if not sub:
            new_subscription = Subscription(user_id=user.id, file_path=file.path)
            session.add(new_subscription)
            await session.commit()
            await callback.message.edit_text(
                f"✅ Подписка оформлена!\n\n"
                f"📁 Файл: <code>{file.filename}</code>\n"
                f"🔢 Заказ: {file.order}\n"
                f"🏗 Стадия: {file.stage}\n"
                f"📝 Задание: {file.task}"
            )
        else:
            await callback.message.edit_text(
                f"⚠️ Вы уже подписаны на этот файл!\n\n"
                f"📁 Файл: <code>{file.filename}</code>"
            )
            
    except Exception as e:
        await callback.message.edit_text(f"❌ Ошибка при оформлении подписки: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        await state.clear()

# ---------------
# Просмотр подписок
# ---------------
@router.message(Command("my_subs"))
async def my_subscriptions(message: Message, session: AsyncSession):
    try:
        # Получаем пользователя
        stmt = select(User).where(User.tg_id == message.from_user.id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        
        if not user:
            await message.answer("❌ Сначала начните работу с ботом командой /start")
            return

        # Получаем подписки
        stmt = select(Subscription).where(Subscription.user_id == user.id)
        result = await session.execute(stmt)
        subs = result.scalars().all()

        if not subs:
            await message.answer("📭 У вас нет подписок.\n\nИспользуйте команду /subscribe для подписки на файлы.")
        else:
            # Получаем информацию о файлах
            file_paths = [sub.file_path for sub in subs]
            stmt = select(FileInfo).where(FileInfo.path.in_(file_paths))
            result = await session.execute(stmt)
            files = result.scalars().all()
            
            # Создаем словарь для быстрого поиска
            files_dict = {file.path: file for file in files}
            
            # Формируем список подписок
            subscription_list = []
            for i, sub in enumerate(subs, 1):
                file_info = files_dict.get(sub.file_path)
                if file_info:
                    subscription_list.append(
                        f"{i}. <code>{file_info.filename}</code>\n"
                        f"   🔢 {file_info.order} | 🏗 {file_info.stage} | 📝 {file_info.task}"
                    )
                else:
                    filename = os.path.basename(sub.file_path)
                    subscription_list.append(f"{i}. <code>{filename}</code>\n   (файл удален)")
            
            text = "📄 Ваши подписки:\n\n" + "\n\n".join(subscription_list)
            await message.answer(text)
            
    except Exception as e:
        await message.answer(f"❌ Ошибка при получении подписок: {str(e)}")
        import traceback
        traceback.print_exc()

# Экспортируем роутер
def get_handlers_router():
    return router