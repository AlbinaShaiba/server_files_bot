import os
import asyncio
from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select, delete
from models import User, FolderSubscription, async_session
from config import FILES_ROOT, CHECK_INTERVAL

router = Router()
ITEMS_PER_PAGE = 6  # Кол-во проектов/подписок на странице


def paginate_items(items, page):
    start = (page - 1) * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    return items[start:end], len(items)


# ---------------- Start / Menu ----------------

@router.message(Command("start"))
async def cmd_start(message: Message):
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="/subscribe")],
            [KeyboardButton(text="/my_subs")]
        ],
        resize_keyboard=True
    )
    user = message.from_user
    await message.answer(
        f"👋 Привет, {user.first_name}!\n\n"
        "Я бот для отслеживания изменений в папках на сервере выдачи заданий.\n"
        "Доступные команды:\n"
        "📁 /subscribe — подписаться на папку\n"
        "📋 /my_subs — посмотреть и управлять подписками"
    )


# ---------------- Subscribe ----------------

@router.message(Command("subscribe"))
async def cmd_subscribe(message: Message, state):
    projects = sorted([d for d in os.listdir(FILES_ROOT) if os.path.isdir(os.path.join(FILES_ROOT, d))])
    if not projects:
        await message.answer("❌ Нет доступных проектов.")
        return

    await state.update_data(projects=projects, page=1)
    await show_projects_page(message, state)


async def show_projects_page(message_or_callback, state):
    data = await state.get_data()
    page = data["page"]
    projects = data["projects"]

    page_items, total = paginate_items(projects, page)
    kb = InlineKeyboardBuilder()
    for proj in page_items:
        kb.button(text=proj, callback_data=f"proj:{proj}")

    if page > 1:
        kb.button(text="⬅️ Назад", callback_data="page_prev")
    if page * ITEMS_PER_PAGE < total:
        kb.button(text="➡️ Вперёд", callback_data="page_next")

    kb.adjust(2)
    text = "Выберите проект:"
    if isinstance(message_or_callback, Message):
        await message_or_callback.answer(text, reply_markup=kb.as_markup())
    elif isinstance(message_or_callback, CallbackQuery):
        await message_or_callback.message.edit_text(text, reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("page_"))
async def paginate_callback(callback: CallbackQuery, state):
    data = await state.get_data()
    page = data.get("page", 1)
    if callback.data == "page_prev":
        page -= 1
    elif callback.data == "page_next":
        page += 1
    await state.update_data(page=page)
    await callback.answer()
    await show_projects_page(callback, state)


@router.callback_query(F.data.startswith("proj:"))
async def project_selected(callback: CallbackQuery, state):
    project = callback.data.split("proj:")[1]
    await state.update_data(selected_project=project)

    stages_path = os.path.join(FILES_ROOT, project)
    stages = sorted([d for d in os.listdir(stages_path) if os.path.isdir(os.path.join(stages_path, d))])
    if not stages:
        await callback.message.edit_text("❌ Нет доступных стадий для проекта.")
        await callback.answer()
        return

    kb = InlineKeyboardBuilder()
    for st in stages:
        kb.button(text=st, callback_data=f"stage:{st}")
    kb.adjust(2)
    await callback.message.edit_text("Выберите стадию:", reply_markup=kb.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("stage:"))
async def stage_selected(callback: CallbackQuery, state):
    stage = callback.data.split("stage:")[1]
    data = await state.get_data()
    await state.update_data(selected_stage=stage)

    tasks_path = os.path.join(FILES_ROOT, data["selected_project"], stage)
    tasks = sorted([d for d in os.listdir(tasks_path) if os.path.isdir(os.path.join(tasks_path, d))])
    if not tasks:
        await callback.message.edit_text("❌ Нет доступных заданий для стадии.")
        await callback.answer()
        return

    kb = InlineKeyboardBuilder()
    for t in tasks:
        kb.button(text=t, callback_data=f"task:{t}")
    kb.adjust(2)
    await callback.message.edit_text("Выберите задание:", reply_markup=kb.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("task:"))
async def task_selected(callback: CallbackQuery, state):
    task = callback.data.split("task:")[1]
    data = await state.get_data()
    project, stage = data["selected_project"], data["selected_stage"]
    folder_path = os.path.join(project, stage, task)

    async with async_session() as session:
        user_result = await session.execute(select(User).where(User.tg_id == callback.from_user.id))
        user = user_result.scalar_one_or_none()
        if not user:
            user = User(tg_id=callback.from_user.id)
            session.add(user)
            await session.commit()

        sub_result = await session.execute(
            select(FolderSubscription).where(FolderSubscription.user_id == user.id,
                                            FolderSubscription.folder_path == folder_path)
        )
        subscription = sub_result.scalar_one_or_none()
        if not subscription:
            subscription = FolderSubscription(user_id=user.id, folder_path=folder_path)
            session.add(subscription)
            await session.commit()

    await callback.message.edit_text(
        f"✅ Теперь вы будете получать уведомления о любых изменениях в папке:\n<code>{folder_path}</code>",
        parse_mode="HTML"
    )
    await callback.answer()


# ---------------- My Subs ----------------

@router.message(Command("my_subs"))
async def cmd_my_subs(message: Message, state):
    async with async_session() as session:
        user_result = await session.execute(select(User).where(User.tg_id == message.from_user.id))
        user = user_result.scalar_one_or_none()
        if not user:
            await message.answer("❌ У вас нет подписок.")
            return
        result = await session.execute(select(FolderSubscription).where(FolderSubscription.user_id == user.id))
        subs = [s.folder_path for s in result.scalars().all()]

    if not subs:
        await message.answer("❌ У вас нет подписок.")
        return

    await state.update_data(subs=subs, page=1)
    await show_subs_page(message, state)


async def show_subs_page(message_or_callback, state):
    data = await state.get_data()
    page = data["page"]
    subs = data["subs"]

    page_items, total = paginate_items(subs, page)
    kb = InlineKeyboardBuilder()
    for s in page_items:
        kb.button(text=f"❌ {s}", callback_data=f"delete_sub:{s}")

    if page > 1:
        kb.button(text="⬅️ Назад", callback_data="subs_page_prev")
    if page * ITEMS_PER_PAGE < total:
        kb.button(text="➡️ Вперёд", callback_data="subs_page_next")

    kb.adjust(1)
    text = "Ваши подписки (нажмите для удаления):"
    if isinstance(message_or_callback, Message):
        await message_or_callback.answer(text, reply_markup=kb.as_markup())
    elif isinstance(message_or_callback, CallbackQuery):
        await message_or_callback.message.edit_text(text, reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("subs_page_"))
async def subs_paginate_callback(callback: CallbackQuery, state):
    data = await state.get_data()
    page = data.get("page", 1)
    if callback.data == "subs_page_prev":
        page -= 1
    elif callback.data == "subs_page_next":
        page += 1
    await state.update_data(page=page)
    await callback.answer()
    await show_subs_page(callback, state)


@router.callback_query(F.data.startswith("delete_sub:"))
async def delete_subscription(callback: CallbackQuery, state):
    folder_path = callback.data.split("delete_sub:")[1]

    async with async_session() as session:
        user_result = await session.execute(select(User).where(User.tg_id == callback.from_user.id))
        user = user_result.scalar_one_or_none()
        if not user:
            await callback.answer("❌ Пользователь не найден.")
            return

        await session.execute(delete(FolderSubscription).where(
            FolderSubscription.user_id == user.id,
            FolderSubscription.folder_path == folder_path
        ))
        await session.commit()

    # Обновляем список подписок в state
    data = await state.get_data()
    subs = [s for s in data.get("subs", []) if s != folder_path]
    await state.update_data(subs=subs)
    await callback.answer(f"✅ Подписка на {folder_path} удалена.")
    await show_subs_page(callback, state)


# ---------------- Monitoring ----------------

class FileWatcher:
    def __init__(self, bot):
        self.bot = bot

    def get_full_path(self, relative_path: str) -> str:
        return os.path.join(FILES_ROOT, relative_path)

    def get_folder_mtime_recursive(self, folder_path: str) -> float:
        if not os.path.exists(folder_path):
            return 0.0
        latest = 0.0
        for root, _, files in os.walk(folder_path):
            try:
                mtime = os.path.getmtime(root)
                if mtime > latest:
                    latest = mtime
            except OSError:
                pass
            for file in files:
                try:
                    mtime = os.path.getmtime(os.path.join(root, file))
                    if mtime > latest:
                        latest = mtime
                except OSError:
                    pass
        return latest

    async def notify_subscribers(self, sub, changed_folder, current_mtime):
        try:
            async with async_session() as session:
                result = await session.execute(select(User).where(User.id == sub.user_id))
                user = result.scalar_one_or_none()
                if not user:
                    return

            # Добавляем +1 час
            current_mtime += timedelta(hours=1)

            rel_path = os.path.relpath(changed_folder, FILES_ROOT)
            message = (
                "🔄 <b>Обнаружено изменение в папке Задание!</b>\n\n"
                f"📌 Путь: <code>{rel_path}</code>\n"
                f"🕒 Время изменения: {current_mtime.strftime('%d.%m.%Y %H:%M')}\n"
                f"💬 Вы подписаны на это задание."
            )

            await self.bot.send_message(user.tg_id, message, parse_mode="HTML")

        except Exception as e:
            print("Ошибка уведомления:", e)

    async def check_folder_updates(self):
        async with async_session() as session:
            result = await session.execute(select(FolderSubscription))
            subscriptions = result.scalars().all()

            for sub in subscriptions:
                task_full_path = self.get_full_path(sub.folder_path)
                if not os.path.exists(task_full_path):
                    continue
                subfolders = [d for d in os.listdir(task_full_path) if os.path.isdir(os.path.join(task_full_path, d))]

                latest_mtime = 0.0
                changed_folder = None
                for sf in subfolders:
                    data_path = os.path.join(task_full_path, sf, "Data")
                    if not os.path.isdir(data_path):
                        continue
                    mtime = self.get_folder_mtime_recursive(data_path)
                    if mtime > latest_mtime:
                        latest_mtime = mtime
                        changed_folder = os.path.join(task_full_path, sf)

                if latest_mtime == 0.0:
                    continue

                current_mtime = datetime.fromtimestamp(latest_mtime)
                if sub.last_modified is None:
                    sub.last_modified = current_mtime
                    session.add(sub)
                    await session.commit()
                    continue

                if latest_mtime > sub.last_modified.timestamp():
                    sub.last_modified = current_mtime
                    session.add(sub)
                    await session.commit()
                    await self.notify_subscribers(sub, changed_folder, current_mtime)

    async def start_monitoring(self):
        while True:
            try:
                await self.check_folder_updates()
                await asyncio.sleep(CHECK_INTERVAL)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print("Ошибка мониторинга:", e)
                await asyncio.sleep(CHECK_INTERVAL)
