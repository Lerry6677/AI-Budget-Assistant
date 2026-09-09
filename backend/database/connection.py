import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is required")


# 生产环境需关闭 SQL echo 日志；由环境变量 DB_ECHO 控制（默认关闭，本地调试可显式开启）
DB_ECHO = os.getenv("DB_ECHO", "false").strip().lower() in ("1", "true", "yes")

engine = create_engine(DATABASE_URL, echo=DB_ECHO)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
