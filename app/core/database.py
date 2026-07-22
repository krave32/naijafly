from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://naijafly:naijafly@localhost:5432/naijafly")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

from app.models.models import Base


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
