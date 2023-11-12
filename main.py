from fastapi import FastAPI, Depends, HTTPException, Security, Request
from fastapi.security import OAuth2PasswordBearer, HTTPAuthorizationCredentials
from fastapi.security import  OAuth2PasswordRequestForm
from fastapi.security.api_key import APIKeyQuery, APIKey
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from datetime import datetime, timedelta
import jwt
from passlib.context import CryptContext
from json.decoder import JSONDecodeError

from database import AsyncSessionLocal, engine
from models import Note, Base, User  # 确保导入了 User 模型
from pydantic import BaseModel
from typing import List, Optional

from config import API_KEY, API_KEY_NAME, SECRET_KEY

# 安全性和密码

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


class NoteCreate(BaseModel):
    title: str
    body: Optional[str] = ""
    url: Optional[str] = ""
    category: Optional[str] = "Personal"
    username: Optional[str] = "user1"

class NoteUpdate(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None
    category: Optional[str] = None
    
class NoteResponse(BaseModel):
    id: int
    title: str
    body: Optional[str] = ""
    url: Optional[str] = ""
    category: Optional[str] = "Personal"
    username: Optional[str] = "user1"
    timestamp: datetime

class PaginationResponse(BaseModel):
    total_pages: int
    current_page: int
    data: List[NoteResponse]
    
class UserCreate(BaseModel):
    username: str
    password: str

class LoginRequest(BaseModel):
    username: str
    password: str
    
app = FastAPI()

api_key_query = APIKeyQuery(name=API_KEY_NAME, auto_error=True)

def get_password_hash(password):
    return pwd_context.hash(password)
def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

# Token 创建函数
def create_access_token(data: dict):
    to_encode = data.copy()
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_api_key(api_key: str = Depends(api_key_query)):
    if api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API Key")
    return api_key


# Token 验证依赖项
async def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Invalid authentication credentials")
        return username
    except jwt.PyJWTError:
        raise HTTPException(status_code=403, detail="Could not validate credentials")

# Dependency
async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

@app.on_event("startup")
async def on_startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

@app.post("/notes/", response_model=NoteCreate)
async def create_note(request: Request, db: AsyncSession = Depends(get_db)):
    try:
        note_data = await request.json()
        new_note = Note(**note_data)
    except JSONDecodeError:
        body = await request.body()
        note_data = {
            "title": datetime.now().strftime("%Y-%m-%d"),
            "body": body.decode("utf-8")  # 假设 body 是 UTF-8 编码
        }
        new_note = Note(**note_data)

    db.add(new_note)
    await db.commit()
    await db.refresh(new_note)
    return NoteResponse(**new_note.__dict__)

@app.get("/notes/", response_model=PaginationResponse)
async def read_notes(username: str, page: int = 1, page_size: int = 10, db: AsyncSession = Depends(get_db)):
    # 确保 page_size 至少为 1
    page_size = max(1, page_size)

    total_count_query = select(func.count(Note.id)).where(Note.username == username)
    total_count_result = await db.execute(total_count_query)
    total_count = total_count_result.scalar_one()

    total_pages = (total_count + page_size - 1) // page_size
    current_page = max(1, min(page, total_pages))

    skip = (current_page - 1) * page_size

    notes_query = select(Note).where(Note.username == username).order_by(Note.id.desc()).offset(skip).limit(page_size)
    notes_result = await db.execute(notes_query)
    notes = notes_result.scalars().all()

    return PaginationResponse(total_pages=total_pages, current_page=current_page, data=[NoteResponse(**note.__dict__) for note in notes])


@app.get("/notes/{note_id}", response_model=NoteCreate)
async def read_note(note_id: int, api_key: str = Depends(get_api_key), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Note).filter(Note.id == note_id))
    note = result.scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")
    return NoteCreate(**note.__dict__)

@app.put("/notes/{note_id}", response_model=NoteCreate)
async def update_note(note_id: int, note_update: NoteUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Note).filter(Note.id == note_id))
    note = result.scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")
    note_data = note_update.dict(exclude_unset=True)
    for key, value in note_data.items():
        setattr(note, key, value)
    await db.commit()
    await db.refresh(note)
    return NoteCreate(**note.__dict__)

@app.delete("/notes/{note_id}", response_model=NoteCreate)
async def delete_note(note_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Note).filter(Note.id == note_id))
    note = result.scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")
    await db.delete(note)
    await db.commit()
    return NoteCreate(**note.__dict__)

async def get_user_by_username(username: str, db: AsyncSession):
    result = await db.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()

@app.post("/token")
async def login_for_access_token(login_request: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = await get_user_by_username(login_request.username, db)
    if not user or not verify_password(login_request.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/register")
async def create_user(user: UserCreate, db: AsyncSession = Depends(get_db)):
    hashed_password = get_password_hash(user.password)
    new_user = User(username=user.username, hashed_password=hashed_password)
    db.add(new_user)
    await db.commit()
    return {"message": "User created successfully"}

@app.get("/")
async def read_protected():
    return {"message": f"Hello"}