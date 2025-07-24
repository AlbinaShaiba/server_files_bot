from sqlalchemy import Column, Integer, BigInteger, String, Text, DateTime, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.ext.asyncio import AsyncAttrs, async_sessionmaker, create_async_engine
from datetime import datetime
import os
from config import DATABASE_URL

# Создание движка для SQLite
engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)

# Базовый класс
class Base(AsyncAttrs, DeclarativeBase):
    pass

# Таблица пользователей
class User(Base):
    __tablename__ = "users"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str] = mapped_column(String(255), nullable=True, index=True)
    first_name: Mapped[str] = mapped_column(String(255), nullable=True)
    last_name: Mapped[str] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

# Таблица файлов
class FileInfo(Base):
    __tablename__ = "files"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    order: Mapped[str] = mapped_column(String(50), index=True)
    stage: Mapped[str] = mapped_column(String(50), index=True)
    task: Mapped[str] = mapped_column(String(100), index=True)
    filename: Mapped[str] = mapped_column(String(255), index=True)
    path: Mapped[str] = mapped_column(Text, unique=True, index=True)
    last_modified: Mapped[datetime] = mapped_column(DateTime, index=True)
    size: Mapped[int] = mapped_column(Integer, default=0)

# Таблица подписок
class Subscription(Base):
    __tablename__ = "subscriptions"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    file_path: Mapped[str] = mapped_column(Text, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

# Функция инициализации БД
async def init_db():
    """Инициализация базы данных - создание всех таблиц"""
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        print("✅ База данных SQLite инициализирована")
    except Exception as e:
        print(f"❌ Ошибка инициализации базы данных SQLite: {e}")
        raise

# Функция для получения сессии
async def get_session():
    """Получение асинхронной сессии"""
    async with async_session() as session:
        yield session