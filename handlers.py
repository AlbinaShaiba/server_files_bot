# handlers.py
from aiogram import Router, F
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


# Клавиатура с командами
main_menu_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="/subscribe")],
        [KeyboardButton(text="/my_subs")],
    ],
    resize_keyboard=True
)


async def get_or_create_user(session: AsyncSession, user_data) -> User:
    """Получает или создаёт пользователя в БД"""
    stmt = select(User).where(User.tg_id == user_data.id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        user = User(
            tg_id=user_data.id,
            username=user_data.username,
            first_name=user_data.first_name,
            last_name=user_data.last_name
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        print(f"➕ Новый пользователь: {user_data.full_name} (@{user_data.username})")
    else:
        # Обновляем данные
        user.username = user_data.username
        user.first_name = user_data.first_name
        user.last_name = user_data.last_name
        session.add(user)
        await session.commit()
    return user


@router.message(Command("start"))
async def cmd_start(message: Message, session: AsyncSession):
    user = await get_or_create_user(session, message.from_user)

    await message.answer(
        f"👋 Привет, {user.first_name}!\n\n"
        "Я бот для отслеживания изменений в папках на сервере.\n"
        "Доступные команды:\n"
        "📁 /subscribe — подписаться на папку\n"
        "📋 /my_subs — посмотреть и управлять подписками",
        reply_markup=main_menu_kb
    )


@router.message(Command("subscribe"))
async def start_subscription(message: Message, state: FSMContext, session: AsyncSession):
    await state.clear()
    user = await get_or_create_user(session, message.from_user)

    if not os.path.exists(FILES_ROOT):
        await message.answer("❌ Директория с файлами не найдена. Проверьте настройки.")
        return

    # Получаем список проектов (первый уровень)
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
        await message.answer("📭 Нет доступных проектов.")
        return

    await show_orders_page(message, sorted(orders), 0, state)


async def show_orders_page(message: Message, orders: list, page: int, state: FSMContext):
    total_pages = (len(orders) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    start_idx = page * ITEMS_PER_PAGE
    end_idx = min(start_idx + ITEMS_PER_PAGE, len(orders))
    current_orders = orders[start_idx:end_idx]

    kb = InlineKeyboardBuilder()
    for order in current_orders:
        kb.button(text=order, callback_data=f"order:{order}")
    pagination_row = []
    if page > 0:
        pagination_row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"orders_page:{page-1}"))
    if page < total_pages - 1:
        pagination_row.append(InlineKeyboardButton(text="Далее ➡️", callback_data=f"orders_page:{page+1}"))
    if pagination_row:
        kb.row(*pagination_row)
    kb.adjust(2)

    page_info = f" (страница {page+1}/{total_pages})" if total_pages > 1 else ""
    await message.answer(f"📁 Выберите проект{page_info}:", reply_markup=kb.as_markup())
    await state.set_state(SubscribeState.order)


@router.callback_query(lambda c: c.data.startswith("orders_page:"))
async def handle_orders_pagination(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    page = int(callback.data.split(":")[1])
    orders = []
    try:
        for item in os.listdir(FILES_ROOT):
            item_path = os.path.join(FILES_ROOT, item)
            if os.path.isdir(item_path):
                orders.append(item)
    except Exception as e:
        await callback.message.edit_text(f"❌ Ошибка: {e}")
        return

    await callback.message.delete()
    await show_orders_page(callback.message, sorted(orders), page, state)


@router.callback_query(lambda c: c.data.startswith("order:"))
async def select_order(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    order = callback.data.split(":", 1)[1]
    await state.update_data(order=order)
    order_path = os.path.join(FILES_ROOT, order)

    if not os.path.exists(order_path):
        await callback.message.edit_text("❌ Папка проекта не найдена.")
        return

    # Получаем стадии
    stages = []
    try:
        for item in os.listdir(order_path):
            item_path = os.path.join(order_path, item)
            if os.path.isdir(item_path):
                stages.append(item)
    except Exception as e:
        await callback.message.edit_text(f"❌ Ошибка при чтении стадий: {e}")
        return

    if not stages:
        await callback.message.edit_text("📭 Нет стадий в этом проекте.")
        return

    await state.update_data(stages_list=stages)
    await show_stages_page(callback.message, stages, 0, state)


async def show_stages_page(message: Message, stages: list, page: int, state: FSMContext):
    total_pages = (len(stages) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    start_idx = page * ITEMS_PER_PAGE
    end_idx = min(start_idx + ITEMS_PER_PAGE, len(stages))
    current_stages = sorted(stages)[start_idx:end_idx]

    kb = InlineKeyboardBuilder()
    for stage in current_stages:
        kb.button(text=stage, callback_data=f"stage:{stage}")
    pagination_row = []
    if page > 0:
        pagination_row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"stages_page:{page-1}"))
    if page < total_pages - 1:
        pagination_row.append(InlineKeyboardButton(text="Далее ➡️", callback_data=f"stages_page:{page+1}"))
    if pagination_row:
        kb.row(*pagination_row)
    kb.adjust(2)

    page_info = f" (страница {page+1}/{total_pages})" if total_pages > 1 else ""
    await message.edit_text(f"🔧 Выберите стадию{page_info}:", reply_markup=kb.as_markup())


@router.callback_query(lambda c: c.data.startswith("stages_page:"))
async def handle_stages_pagination(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    page = int(callback.data.split(":")[1])
    data = await state.get_data()
    stages = data.get("stages_list", [])
    await show_stages_page(callback.message, stages, page, state)


@router.callback_query(lambda c: c.data.startswith("stage:"))
async def select_stage(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    stage = callback.data.split(":", 1)[1]
    await state.update_data(stage=stage)
    data = await state.get_data()
    stage_path = os.path.join(FILES_ROOT, data["order"], stage)

    if not os.path.exists(stage_path):
        await callback.message.edit_text("❌ Папка стадии не найдена.")
        return

    # Получаем папки-задания (например, Задание АР, КЖ и т.д.)
    tasks = []
    try:
        for item in os.listdir(stage_path):
            item_path = os.path.join(stage_path, item)
            if os.path.isdir(item_path):
                tasks.append(item)
    except Exception as e:
        await callback.message.edit_text(f"❌ Ошибка при чтении заданий: {e}")
        return

    if not tasks:
        await callback.message.edit_text("📭 Нет заданий в этой стадии.")
        return

    await state.update_data(tasks_list=tasks)
    await show_tasks_page(callback.message, tasks, 0, state)


async def show_tasks_page(message: Message, tasks: list, page: int, state: FSMContext):
    total_pages = (len(tasks) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    start_idx = page * ITEMS_PER_PAGE
    end_idx = min(start_idx + ITEMS_PER_PAGE, len(tasks))
    current_tasks = sorted(tasks)[start_idx:end_idx]

    kb = InlineKeyboardBuilder()
    for task in current_tasks:
        kb.button(text=f"📁 {task}", callback_data=f"task:{task}")
    pagination_row = []
    if page > 0:
        pagination_row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"tasks_page:{page-1}"))
    if page < total_pages - 1:
        pagination_row.append(InlineKeyboardButton(text="Далее ➡️", callback_data=f"tasks_page:{page+1}"))
    if pagination_row:
        kb.row(*pagination_row)
    kb.adjust(1)

    page_info = f" (страница {page+1}/{total_pages})" if total_pages > 1 else ""
    await message.edit_text(f"📌 Выберите задание{page_info}:", reply_markup=kb.as_markup())
    await state.set_state(SubscribeState.task)


@router.callback_query(lambda c: c.data.startswith("tasks_page:"))
async def handle_tasks_pagination(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    page = int(callback.data.split(":")[1])
    data = await state.get_data()
    tasks = data.get("tasks_list", [])
    await show_tasks_page(callback.message, tasks, page, state)


@router.callback_query(lambda c: c.data.startswith("task:"))
async def select_task(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    task = callback.data.split(":", 1)[1]
    data = await state.get_data()
    task_path = os.path.join(FILES_ROOT, data["order"], data["stage"], task)

    if not os.path.exists(task_path) or not os.path.isdir(task_path):
        await callback.message.edit_text("❌ Папка не найдена.")
        return

    # Сохраняем относительный путь
    relative_path = os.path.relpath(task_path, FILES_ROOT)

    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Подписаться", callback_data="confirm_subscribe")
    kb.adjust(1)

    await state.update_data(
        task=task,
        task_path=relative_path
    )

    await callback.message.edit_text(
        f"Вы выбрали папку:\n"
        f"<b>{task}</b>\n\n"
        f"Подпишитесь, чтобы получать уведомления при любых изменениях внутри.",
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )


@router.callback_query(lambda c: c.data == "confirm_subscribe")
async def confirm_subscribe(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    user = await get_or_create_user(session, callback.from_user)
    data = await state.get_data()
    relative_path = data["task_path"]
    task_name = data["task"]

    # Проверяем, нет ли уже такой подписки
    stmt = select(FolderSubscription).where(
        FolderSubscription.user_id == user.id,
        FolderSubscription.folder_path == relative_path
    )
    result = await session.execute(stmt)
    sub = result.scalar_one_or_none()

    if not sub:
        new_sub = FolderSubscription(
            user_id=user.id,
            folder_path=relative_path,
            last_modified=None
        )
        session.add(new_sub)
        await session.commit()
        await callback.message.edit_text(
            f"✅ Вы успешно подписаны на папку:\n"
            f"<code>{task_name}</code>\n\n"
            f"Теперь вы будете получать уведомления о любых изменениях внутри.",
            parse_mode="HTML"
        )
    else:
        await callback.message.edit_text(
            f"ℹ️ Вы уже подписаны на <code>{task_name}</code>.",
            parse_mode="HTML"
        )

    await state.clear()


@router.message(Command("my_subs"))
async def my_subscriptions(message: Message, session: AsyncSession):
    user = await get_or_create_user(session, message.from_user)

    stmt = select(FolderSubscription).where(FolderSubscription.user_id == user.id)
    result = await session.execute(stmt)
    subs = result.scalars().all()

    if not subs:
        await message.answer("📭 У вас нет активных подписок.")
        return

    kb = InlineKeyboardBuilder()
    for sub in subs:
        try:
            rel_path = os.path.relpath(sub.folder_path, "")
            parts = rel_path.split(os.sep)
            display_name = f"{parts[0]}/{parts[1]}/<b>{parts[2]}</b>"
        except Exception:
            display_name = f"<code>{sub.folder_path}</code>"

        kb.button(
            text=f"🗑️ Удалить: {os.path.basename(sub.folder_path)}",
            callback_data=f"delete_sub:{sub.id}"
        )
    kb.adjust(1)

    await message.answer(
        "📋 <b>Ваши подписки:</b>\n\n"
        "Нажмите на кнопку, чтобы удалить подписку.",
        reply_markup=kb.as_markup(),
        parse_mode="HTML"
    )


@router.callback_query(lambda c: c.data.startswith("delete_sub:"))
async def delete_subscription(callback: CallbackQuery, session: AsyncSession):
    try:
        sub_id = int(callback.data.split(":", 1)[1])
        user = await get_or_create_user(session, callback.from_user)

        stmt = select(FolderSubscription).where(
            FolderSubscription.id == sub_id,
            FolderSubscription.user_id == user.id
        )
        result = await session.execute(stmt)
        sub = result.scalar_one_or_none()

        if not sub:
            await callback.answer("❌ Подписка не найдена.")
            return

        folder_name = os.path.basename(sub.folder_path)
        await session.delete(sub)
        await session.commit()

        await callback.message.edit_text(
            f"✅ Подписка на папку <code>{folder_name}</code> удалена.",
            parse_mode="HTML"
        )
    except Exception as e:
        await callback.message.edit_text(f"❌ Ошибка при удалении: {e}")