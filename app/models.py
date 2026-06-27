from datetime import datetime
from typing import Optional
from sqlmodel import Field, SQLModel, create_engine, Session
from sqlalchemy import text as sql_text
from .config import settings


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True)
    name: str = ""
    password_hash: str = ""
    auth_provider: str = "password"
    google_sub: str = ""
    is_admin: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ContentPiece(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(default=None, index=True)
    keyword: str
    content_type: str = "blog"
    title: str = ""
    meta_description: str = ""
    slug: str = ""
    draft: str = ""
    score: int = 0
    status: str = "draft"
    is_public: bool = False
    likes: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class PieceLike(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    piece_id: int = Field(index=True)
    user_id: int = Field(index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class GenerationLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    day: str = Field(index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)


def _migrate_sqlite():
    if not settings.database_url.startswith("sqlite"):
        return
    adds = {"user_id": "INTEGER", "is_public": "BOOLEAN DEFAULT 0", "likes": "INTEGER DEFAULT 0"}
    with engine.connect() as conn:
        cols = {row[1] for row in conn.execute(sql_text("PRAGMA table_info(contentpiece)"))}
        for col, decl in adds.items():
            if col not in cols:
                conn.execute(sql_text(f"ALTER TABLE contentpiece ADD COLUMN {col} {decl}"))
        ucols = {row[1] for row in conn.execute(sql_text("PRAGMA table_info(user)"))}
        if "is_admin" not in ucols:
            conn.execute(sql_text("ALTER TABLE user ADD COLUMN is_admin BOOLEAN DEFAULT 0"))
        conn.commit()


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    _migrate_sqlite()


def get_session() -> Session:
    return Session(engine)
