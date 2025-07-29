from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from models import User, FolderSubscription
import os
from config import FILES_ROOT

router = Router()
ITEMS_PER_PAGE = 6


class SubscribeState(StatesGroup):
    order = State()
    stage = State()
    task = State()
    file = State()


main_menu_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="/subscribe")],
        [KeyboardButton(text="/my_subs")]
    ],
    resize_keyboard=True
)


@router.message(Command("start"))
async def cmd_start(message: Message, session: AsyncSession):
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
        print(f"Новый пользователь: {message.from_user.full_name} (@{message.from_user.username})")
    else:
        user.username = message.from_user.username
        user.first_name = message.from_user.first_name
        user.last_name = message.from_user.last_name
        await session.commit()
        print(f"Обновлена информация пользователя: {message.from_user.full_name} (@{message.from_user.username})")

    await message.answer(
        "👋 Привет! Я бот для подписки на обновления файлов.\n"
        "Доступные команды:\n"
        "📁 /subscribe — подписаться на файл\n"
        "📋 /my_subs — посмотреть подписки\n"
        "🔄 /refresh_files — обновить список файлов",
        reply_markup=main_menu_kb
    )



@router.message(Command("subscribe"))
async def start_subscription(message: Message, state: FSMContext, session: AsyncSession):
    await state.clear()
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

    if not os.path.exists(FILES_ROOT):
        await message.answer("Директория с файлами не найдена. Проверьте настройки.")
        return

    orders = []
    try:
        for item in os.listdir(FILES_ROOT):
            item_path = os.path.join(FILES_ROOT, item)
            if os.path.isdir(item_path):
                orders.append(item)
    except Exception as e:
        await message.answer(f"Ошибка при чтении директории: {e}")
        return

    if not orders:
        await message.answer(
            "Нет доступных заказов. Сначала обновите список файлов командой /refresh_files"
        )
        return

    await show_orders_page(message, orders, 0, state)


async def show_orders_page(message: Message, orders: list, page: int, state: FSMContext):
    total_pages = (len(orders) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    start_idx = page * ITEMS_PER_PAGE
    end_idx = min(start_idx + ITEMS_PER_PAGE, len(orders))
    current_orders = sorted(orders, key=lambda x: x.zfill(10) if x.isdigit() else x)[start_idx:end_idx]
    kb = InlineKeyboardBuilder()
    for order in current_orders:
        kb.button(text=order, callback_data=f"order:{order}")
    pagination_row = []
    if page > 0:
        pagination_row.append(InlineKeyboardButton(text="Назад", callback_data=f"orders_page:{page-1}"))
    if page < total_pages - 1:
        pagination_row.append(InlineKeyboardButton(text="Далее", callback_data=f"orders_page:{page+1}"))
    if pagination_row:
        kb.row(*pagination_row)
    kb.adjust(2)
    page_info = f" (страница {page+1}/{total_pages})" if total_pages > 1 else ""
    await message.answer(f"Выберите номер заказа{page_info}:", reply_markup=kb.as_markup())
    await state.set_state(SubscribeState.order)


@router.callback_query(lambda c: c.data.startswith("orders_page:"))
async def handle_orders_pagination(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    page = int(callback.data.split(":")[1])
    orders = []
    if os.path.exists(FILES_ROOT):
        try:
            for item in os.listdir(FILES_ROOT):
                item_path = os.path.join(FILES_ROOT, item)
                if os.path.isdir(item_path):
                    orders.append(item)
        except Exception as e:
            await callback.message.edit_text(f"Ошибка при чтении директории: {e}")
            return
    await callback.message.delete()
    await show_orders_page(callback.message, orders, page, state)


@router.callback_query(lambda c: c.data.startswith("order:"))
async def select_order(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    order = callback.data.split(":")[1]
    await state.update_data(order=order)
    order_path = os.path.join(FILES_ROOT, order)
    if not os.path.exists(order_path):
        await callback.message.edit_text("Папка заказа не найдена")
        return

    stages = []
    try:
        for item in os.listdir(order_path):
            item_path = os.path.join(order_path, item)
            if os.path.isdir(item_path):
                stages.append(item)
    except Exception as e:
        await callback.message.edit_text(f"Ошибка при чтении папки заказа: {e}")
        return

    if not stages:
        await callback.message.edit_text("Нет доступных стадий для этого заказа")
        return

    await state.update_data(stages_list=stages)
    await show_stages_page(callback.message, callback.from_user.id, stages, 0, state)


async def show_stages_page(message: Message, user_id: int, stages: list, page: int, state: FSMContext):
    total_pages = (len(stages) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    start_idx = page * ITEMS_PER_PAGE
    end_idx = min(start_idx + ITEMS_PER_PAGE, len(stages))
    current_stages = sorted(stages)[start_idx:end_idx]
    kb = InlineKeyboardBuilder()
    for stage in current_stages:
        kb.button(text=stage, callback_data=f"stage:{stage}")
    pagination_row = []
    if page > 0:
        pagination_row.append(InlineKeyboardButton(text="Назад", callback_data=f"stages_page:{page-1}"))
    if page < total_pages - 1:
        pagination_row.append(InlineKeyboardButton(text="Далее", callback_data=f"stages_page:{page+1}"))
    if pagination_row:
        kb.row(*pagination_row)
    kb.adjust(2)
    page_info = f" (страница {page+1}/{total_pages})" if total_pages > 1 else ""
    await message.edit_text(f"Выберите стадию{page_info}:", reply_markup=kb.as_markup())


@router.callback_query(lambda c: c.data.startswith("stages_page:"))
async def handle_stages_pagination(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    page = int(callback.data.split(":")[1])
    data = await state.get_data()
    stages = data.get("stages_list", [])
    await show_stages_page(callback.message, callback.from_user.id, stages, page, state)


@router.callback_query(lambda c: c.data.startswith("stage:"))
async def select_stage(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    stage = callback.data.split(":")[1]
    await state.update_data(stage=stage)
    data = await state.get_data()
    stage_path = os.path.join(FILES_ROOT, data["order"], stage)
    if not os.path.exists(stage_path):
        await callback.message.edit_text("Папка стадии не найдена")
        return

    tasks = []
    try:
        for item in os.listdir(stage_path):
            item_path = os.path.join(stage_path, item)
            if os.path.isdir(item_path):
                tasks.append(item)
    except Exception as e:
        await callback.message.edit_text(f"Ошибка при чтении папки стадии: {e}")
        return

    if not tasks:
        await callback.message.edit_text("Нет доступных заданий для этой стадии")
        return

    await state.update_data(tasks_list=tasks)
    await show_tasks_page(callback.message, callback.from_user.id, tasks, 0, state)


async def show_tasks_page(message: Message, user_id: int, tasks: list, page: int, state: FSMContext):
    total_pages = (len(tasks) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    start_idx = page * ITEMS_PER_PAGE
    end_idx = min(start_idx + ITEMS_PER_PAGE, len(tasks))
    current_tasks = sorted(tasks)[start_idx:end_idx]
    kb = InlineKeyboardBuilder()
    for task in current_tasks:
        kb.button(text=task, callback_data=f"task:{task}")
    pagination_row = []
    if page > 0:
        pagination_row.append(InlineKeyboardButton(text="Назад", callback_data=f"tasks_page:{page-1}"))
    if page < total_pages - 1:
        pagination_row.append(InlineKeyboardButton(text="Далее", callback_data=f"tasks_page:{page+1}"))
    if pagination_row:
        kb.row(*pagination_row)
    kb.adjust(1)
    page_info = f" (страница {page+1}/{total_pages})" if total_pages > 1 else ""
    await message.edit_text(f"Выберите задание{page_info}:", reply_markup=kb.as_markup())


@router.callback_query(lambda c: c.data.startswith("tasks_page:"))
async def handle_tasks_pagination(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    page = int(callback.data.split(":")[1])
    data = await state.get_data()
    tasks = data.get("tasks_list", [])
    await show_tasks_page(callback.message, callback.from_user.id, tasks, page, state)


async def show_subfolders_page(message: Message, user_id: int, folders: list, page: int, state: FSMContext):
    total_pages = (len(folders) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    start_idx = page * ITEMS_PER_PAGE
    end_idx = min(start_idx + ITEMS_PER_PAGE, len(folders))
    current_folders = sorted(folders)[start_idx:end_idx]
    kb = InlineKeyboardBuilder()
    for folder in current_folders:
        kb.button(text=f"{folder}", callback_data=f"subfolder:{folder}")
    pagination_row = []
    if page > 0:
        pagination_row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"subfolders_page:{page-1}"))
    if page < total_pages - 1:
        pagination_row.append(InlineKeyboardButton(text="Далее ➡️", callback_data=f"subfolders_page:{page+1}"))
    if pagination_row:
        kb.row(*pagination_row)
    kb.adjust(1)
    page_info = f" (страница {page+1}/{total_pages})" if total_pages > 1 else ""
    await message.edit_text(f"Выберите файл для подписки{page_info}:", reply_markup=kb.as_markup())


@router.callback_query(lambda c: c.data.startswith("task:"))
async def select_task(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    task = callback.data.split(":")[1]
    await state.update_data(task=task)
    data = await state.get_data()
    task_path = os.path.join(FILES_ROOT, data["order"], data["stage"], task)

    if not os.path.exists(task_path):
        await callback.message.edit_text("Папка задания не найдена")
        return
    if not os.path.isdir(task_path):
        await callback.message.edit_text("Указанный путь не является папкой")
        return

    # Получаем подпапки
    subfolders = []
    try:
        for item in os.listdir(task_path):
            item_path = os.path.join(task_path, item)
            if os.path.isdir(item_path):
                subfolders.append(item)
    except Exception as e:
        await callback.message.edit_text(f"Ошибка при чтении папки: {e}")
        return

    if not subfolders:
        await callback.message.edit_text(
            "В этой папке нет файлов для подписки."
        )
        return

    # Показываем подпапки с пагинацией
    await state.update_data(subfolders_list=subfolders)
    await show_subfolders_page(callback.message, callback.from_user.id, subfolders, 0, state)


@router.callback_query(lambda c: c.data == "subscribe_to_folder")
async def subscribe_to_folder(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    try:
        user_id = callback.from_user.id
        data = await state.get_data()
        task_path = os.path.join(FILES_ROOT, data["order"], data["stage"], data["task"])

        stmt = select(User).where(User.tg_id == user_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        if not user:
            user = User(
                tg_id=user_id,
                username=callback.from_user.username,
                first_name=callback.from_user.first_name,
                last_name=callback.from_user.last_name
            )
            session.add(user)
            await session.commit()

        # Проверяем, есть ли уже подписка
        stmt = select(FolderSubscription).where(
            FolderSubscription.user_id == user.id,
            FolderSubscription.folder_path == task_path
        )
        result = await session.execute(stmt)
        sub = result.scalar_one_or_none()

        if not sub:
            new_sub = FolderSubscription(user_id=user.id, folder_path=task_path)
            session.add(new_sub)
            await session.commit()
            await callback.message.edit_text(
                f"✅ Вы подписаны на изменения в файле:\n"
                f"<code>{os.path.basename(task_path)}</code>\n"
                f"Теперь вы будете получать уведомления о любых изменениях файла.",
                parse_mode="HTML"
            )
        else:
            await callback.message.edit_text(
                f"ℹ️ Вы уже подписаны на этот файл."
            )
    except Exception as e:
        await callback.message.edit_text(f"Ошибка: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        await state.clear()

async def show_files_page(message: Message, user_id: int, files: list, page: int, state: FSMContext):
    total_pages = (len(files) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    start_idx = page * ITEMS_PER_PAGE
    end_idx = min(start_idx + ITEMS_PER_PAGE, len(files))
    current_files = files[start_idx:end_idx]
    kb = InlineKeyboardBuilder()
    for file_id, filename in current_files:
        kb.button(text=filename, callback_data=f"file:{file_id}")
    pagination_row = []
    if page > 0:
        pagination_row.append(InlineKeyboardButton(text="Назад", callback_data=f"files_page:{page-1}"))
    if page < total_pages - 1:
        pagination_row.append(InlineKeyboardButton(text="Далее", callback_data=f"files_page:{page+1}"))
    if pagination_row:
        kb.row(*pagination_row)
    kb.adjust(1)
    page_info = f" (страница {page+1}/{total_pages})" if total_pages > 1 else ""
    await message.edit_text(f"Выберите файл для подписки{page_info}:", reply_markup=kb.as_markup())
    await state.set_state(SubscribeState.file)



@router.callback_query(lambda c: c.data.startswith("subfolders_page:"))
async def handle_subfolders_pagination(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    page = int(callback.data.split(":")[1])
    data = await state.get_data()
    folders = data.get("subfolders_list", [])
    await show_subfolders_page(callback.message, callback.from_user.id, folders, page, state)

@router.callback_query(lambda c: c.data.startswith("subfolder:"))
async def select_subfolder(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    subfolder = callback.data.split(":")[1]
    data = await state.get_data()
    # Путь к выбранной подпапке
    folder_path = os.path.join(FILES_ROOT, data["order"], data["stage"], data["task"], subfolder)

    if not os.path.exists(folder_path):
        await callback.message.edit_text("Файл не найден")
        return

    # Кнопка подписки
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Подписаться на этот файл", callback_data="subscribe_to_subfolder")
    kb.adjust(1)

    await state.update_data(subfolder_path=folder_path, subfolder_name=subfolder)

    await callback.message.edit_text(
        f"Вы выбрали файл:\n"
        f"<b>{subfolder}</b>\n\n"
        f"Подпишитесь, чтобы получать уведомления при любых изменениях.",
        reply_markup=kb.as_markup(),
        parse_mode="HTML"
    )

@router.message(Command("my_folder_subs"))
async def my_folder_subscriptions(message: Message, session: AsyncSession):
    stmt = select(User).where(User.tg_id == message.from_user.id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        await message.answer("Сначала начните с /start")
        return

    stmt = select(FolderSubscription).where(FolderSubscription.user_id == user.id)
    result = await session.execute(stmt)
    subs = result.scalars().all()

    if not subs:
        await message.answer("Вы не подписаны на папки.")
        return

    subs_list = []
    for i, sub in enumerate(subs, 1):
        folder_name = os.path.basename(sub.folder_path)
        last_mod = sub.last_modified.strftime("%d.%m.%Y %H:%M") if sub.last_modified else "—"
        subs_list.append(f"{i}. <code>{folder_name}</code> (обновлено: {last_mod})")

    await message.answer("Ваши подписки на папки:\n" + "\n".join(subs_list))

@router.callback_query(lambda c: c.data == "subscribe_to_subfolder")
async def subscribe_to_subfolder(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    try:
        user_id = callback.from_user.id
        data = await state.get_data()
        folder_path = data["subfolder_path"]
        folder_name = data["subfolder_name"]

        # Получаем или создаём пользователя
        stmt = select(User).where(User.tg_id == user_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        if not user:
            user = User(
                tg_id=user_id,
                username=callback.from_user.username,
                first_name=callback.from_user.first_name,
                last_name=callback.from_user.last_name
            )
            session.add(user)
            await session.commit()

        # Проверяем, есть ли уже подписка
        stmt = select(FolderSubscription).where(
            FolderSubscription.user_id == user.id,
            FolderSubscription.folder_path == folder_path
        )
        result = await session.execute(stmt)
        sub = result.scalar_one_or_none()

        if not sub:
            new_sub = FolderSubscription(user_id=user.id, folder_path=folder_path)
            session.add(new_sub)
            await session.commit()
            await callback.message.edit_text(
                f"✅ Вы подписаны на файл:\n"
                f"<code>{folder_name}</code>\n"
                f"Теперь вы будете получать уведомления о любых изменениях в этом файле.",
                parse_mode="HTML"
            )
        else:
            await callback.message.edit_text(
                f"ℹ️ Вы уже подписаны на файл <code>{folder_name}</code>.",
                parse_mode="HTML"
            )
    except Exception as e:
        await callback.message.edit_text(f"❌ Ошибка: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        await state.clear()


@router.callback_query(lambda c: c.data.startswith("files_page:"))
async def handle_files_pagination(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    page = int(callback.data.split(":")[1])
    data = await state.get_data()
    files = data.get("files_list", [])
    await show_files_page(callback.message, callback.from_user.id, files, page, state)




@router.message(Command("my_subs"))
async def my_subscriptions(message: Message, session: AsyncSession):
    try:
        # Получаем пользователя
        stmt = select(User).where(User.tg_id == message.from_user.id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        if not user:
            await message.answer("Сначала начните работу с ботом командой /start")
            return

        # Получаем подписки на папки
        stmt = select(FolderSubscription).where(FolderSubscription.user_id == user.id)
        result = await session.execute(stmt)
        subs = result.scalars().all()

        if not subs:
            await message.answer("У вас нет подписок.\nИспользуйте команду /subscribe для подписки на файлы.")
            return

        subscription_list = []

        for i, sub in enumerate(subs, 1):
            folder_path = sub.folder_path
            folder_name = os.path.basename(folder_path)

            # Проверяем, существует ли папка
            folder_exists = os.path.exists(folder_path) and os.path.isdir(folder_path)

            # Пытаемся извлечь order, stage, task из пути
            try:
                # Удаляем корневую директорию
                rel_path = os.path.relpath(folder_path, FILES_ROOT).split(os.sep)
                if len(rel_path) >= 3:
                    order = rel_path[0]
                    stage = rel_path[1]
                    task = rel_path[2]
                else:
                    order = stage = task = "неизвестно"
            except Exception:
                order = stage = task = "неизвестно"

            if folder_exists:
                subscription_list.append(
                    f"{i}. <code>{folder_name}</code>\n"
                    f"📦 {order} | 🔧 {stage} | 📂 {task}"
                )
            else:
                subscription_list.append(
                    f"{i}. <code>{folder_name}</code>\n"
                    f"❌ (папка удалена или недоступна)"
                )

        text = "Ваши подписки на файлы:\n" + "\n".join(subscription_list)
        await message.answer(text)

    except Exception as e:
        await message.answer(f"❌ Ошибка при получении подписок: {str(e)}")
        import traceback
        traceback.print_exc()


def get_handlers_router():
    return router