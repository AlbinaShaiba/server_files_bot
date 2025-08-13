import os
from aiogram.fsm.context import FSMContext
import re
import asyncio
from datetime import datetime
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select, delete
from models import User, FolderSubscription, async_session

import hashlib

from config import FILES_ROOT, CHECK_INTERVAL

router = Router()
ITEMS_PER_PAGE = 6
MAX_CALLBACK_LEN = 64

# ---------------- Helpers ----------------

def paginate_items(items, page):
    start = (page - 1) * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    return items[start:end], len(items)

def make_callback_hash(value: str) -> str:
    """Создает короткий безопасный хэш для callback_data."""
    return hashlib.sha256(value.encode('utf-8')).hexdigest()[:16]

async def safe_edit(message_or_callback, text, reply_markup=None):
    if isinstance(message_or_callback, Message):
        await message_or_callback.answer(text, reply_markup=reply_markup)
    elif isinstance(message_or_callback, CallbackQuery):
        try:
            await message_or_callback.message.edit_text(text, reply_markup=reply_markup)
        except Exception as e:
            if "message is not modified" in str(e):
                await message_or_callback.answer()  # просто подтвердить callback
            else:
                raise

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
        "📋 /my_subs — посмотреть и управлять подписками",
        reply_markup=kb
    )

# ---------------- Subscribe ----------------

@router.message(Command("subscribe"))
async def cmd_subscribe(message: Message, state: FSMContext):
    projects = sorted([d for d in os.listdir(FILES_ROOT) if os.path.isdir(os.path.join(FILES_ROOT, d))])
    if not projects:
        await message.answer("❌ Нет доступных проектов.")
        return
    await state.update_data(projects=projects, page=1)
    await show_projects_page(message, state)
# ---------------- Projects Pagination ----------------

async def show_projects_page(message_or_callback, state: FSMContext):
    data = await state.get_data()
    page = data.get("page", 1)
    projects = data.get("projects", [])

    page_items, total = paginate_items(projects, page)
    kb = InlineKeyboardBuilder()
    hash_map = {}

    for proj in page_items:
        h = make_callback_hash(proj)
        hash_map[h] = proj
        kb.button(text=proj, callback_data=f"proj:{h}")

    # Навигация
    if page > 1:
        kb.button(text="⬅️ Назад", callback_data="page_prev")
    if page * ITEMS_PER_PAGE < total:
        kb.button(text="➡️ Вперёд", callback_data="page_next")

    kb.adjust(2)
    await state.update_data(hash_map_projects=hash_map, page=page)
    await safe_edit(message_or_callback, "Выберите проект:", reply_markup=kb.as_markup())


# ---------------- Pagination Callbacks ----------------

@router.callback_query(F.data == "page_next")
async def page_next(callback: CallbackQuery, state):
    data = await state.get_data()
    page = data.get("page", 1)
    await state.update_data(page=page + 1)
    await show_projects_page(callback, state)
    await callback.answer()

@router.callback_query(F.data == "page_prev")
async def page_prev(callback: CallbackQuery, state):
    data = await state.get_data()
    page = data.get("page", 1)
    if page > 1:
        await state.update_data(page=page - 1)
        await show_projects_page(callback, state)
    await callback.answer()


@router.callback_query(F.data.startswith("proj:"))
async def project_selected(callback: CallbackQuery, state):
    h = callback.data.split("proj:")[1]
    data = await state.get_data()
    project = data["hash_map_projects"].get(h)
    if not project:
        await callback.answer("❌ Проект не найден.", show_alert=True)
        return

    await state.update_data(selected_project=project)

    stages_path = os.path.join(FILES_ROOT, project)
    stages = sorted([d for d in os.listdir(stages_path) if os.path.isdir(os.path.join(stages_path, d))])
    if not stages:
        await callback.message.edit_text("❌ Нет доступных стадий для проекта.")
        await callback.answer()
        return

    kb = InlineKeyboardBuilder()
    hash_map = {}
    for st in stages:
        h = make_callback_hash(st)
        hash_map[h] = st
        kb.button(text=st, callback_data=f"stage:{h}")
    kb.adjust(2)
    await state.update_data(hash_map_stages=hash_map)
    await callback.message.edit_text("Выберите стадию:", reply_markup=kb.as_markup())
    await callback.answer()

@router.callback_query(F.data.startswith("stage:"))
async def stage_selected(callback: CallbackQuery, state):
    h = callback.data.split("stage:")[1]
    data = await state.get_data()
    stage = data["hash_map_stages"].get(h)
    if not stage:
        await callback.answer("❌ Стадия не найдена.", show_alert=True)
        return

    await state.update_data(selected_stage=stage)

    tasks_path = os.path.join(FILES_ROOT, data["selected_project"], stage)
    tasks = sorted([d for d in os.listdir(tasks_path) if os.path.isdir(os.path.join(tasks_path, d))])
    if not tasks:
        await callback.message.edit_text("❌ Нет доступных заданий для стадии.")
        await callback.answer()
        return

    kb = InlineKeyboardBuilder()
    hash_map = {}
    for t in tasks:
        h = make_callback_hash(t)
        hash_map[h] = t
        kb.button(text=t, callback_data=f"task:{h}")
    kb.adjust(2)
    await state.update_data(hash_map_tasks=hash_map)
    await callback.message.edit_text("Выберите задание:", reply_markup=kb.as_markup())
    await callback.answer()

@router.callback_query(F.data.startswith("task:"))
async def task_selected(callback: CallbackQuery, state):
    h = callback.data.split("task:")[1]
    data = await state.get_data()
    task = data["hash_map_tasks"].get(h)
    if not task:
        await callback.answer("❌ Задание не найдено.", show_alert=True)
        return

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
    await safe_edit(message_or_callback, "Ваши подписки (нажмите для удаления):", reply_markup=kb.as_markup())

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

    async def notify_subscribers(self, sub, changed_folder):
        try:
            async with async_session() as session:
                result = await session.execute(select(User).where(User.id == sub.user_id))
                user = result.scalar_one_or_none()
                if not user:
                    return
            rel_path = os.path.relpath(changed_folder, FILES_ROOT)
            message = (
                "🔄 <b>Обнаружено изменение в папке Задание!</b>\n\n"
                f"📌 Путь: <code>{rel_path}</code>\n"
                f"🕒 Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
            await self.bot.send_message(user.tg_id, message, parse_mode="HTML")
        except Exception as e:
            print("Notify error:", e)

    async def monitor(self):
        last_mtimes = {}
        while True:
            async with async_session() as session:
                result = await session.execute(select(FolderSubscription))
                subs = result.scalars().all()
            for sub in subs:
                folder_path = self.get_full_path(sub.folder_path)
                current_mtime = self.get_folder_mtime_recursive(folder_path)
                if sub.folder_path not in last_mtimes:
                    last_mtimes[sub.folder_path] = current_mtime
                    continue
                if current_mtime > last_mtimes[sub.folder_path]:
                    await self.notify_subscribers(sub, folder_path)
                    last_mtimes[sub.folder_path] = current_mtime
            await asyncio.sleep(CHECK_INTERVAL)
