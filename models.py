from sqlalchemy import Integer, BigInteger, String, Text, DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.ext.asyncio import AsyncAttrs, async_sessionmaker, create_async_engine
from datetime import datetime
from config import DATABASE_URL

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)

class Base(AsyncAttrs, DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str] = mapped_column(String(255), nullable=True, index=True)
    first_name: Mapped[str] = mapped_column(String(255), nullable=True)
    last_name: Mapped[str] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

#class FileInfo(Base):
#    __tablename__ = "files"
 #   id: Mapped[int] = mapped_column(primary_key=True)
 #   order: Mapped[str] = mapped_column(String)
 #   stage: Mapped[str] = mapped_column(String)
#    task: Mapped[str] = mapped_column(String)
#    foldername: Mapped[str] = mapped_column(String)
 #   path: Mapped[str] = mapped_column(String, unique=True)
 #   hash: Mapped[str] = mapped_column(String, nullable=True)


class FolderSubscription(Base):
    __tablename__ = "folder_subscriptions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    folder_path: Mapped[str] = mapped_column(Text, index=True)
    last_modified: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)



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