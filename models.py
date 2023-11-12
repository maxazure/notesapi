from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()

class Note(Base):
    __tablename__ = "notes"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), index=True)
    body = Column(String(10240), default="None")
    url = Column(String(255), default="")
    timestamp = Column(DateTime, default=datetime.now)
    category = Column(String(255), default="Personal")
    username = Column(String(255), default="user1")

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True)
    hashed_password = Column(String(255)) 
