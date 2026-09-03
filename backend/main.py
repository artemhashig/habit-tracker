from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List
import os

app = FastAPI(title="Habits Tracker API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class Habit(BaseModel):
    id: int
    title: str
    category: str
    schedule: str
    current: int
    total: int
    color: str

habits_db: List[Habit] = [
    Habit(
        id=1,
        title="Абхазский язык",
        category="Саморазвитие",
        schedule="Пн — Сб, 0/3 сеанса",
        current=0,
        total=3,
        color="green"
    ),
    Habit(
        id=2,
        title="Отжимания",
        category="Спорт",
        schedule="Пн, Ср, Пт, 28/70 повторений",
        current=28,
        total=70,
        color="yellow"
    )
]

@app.get("/api/habits")
async def get_habits():
    return habits_db

@app.post("/api/habits/{habit_id}/increment")
async def increment_habit(habit_id: int):
    for habit in habits_db:
        if habit.id == habit_id:
            if habit.current < habit.total:
                habit.current += 1
            return habit
    return {"error": "Not found"}

# Путь к скомпилированному фронтенду
frontend_dist = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")

if os.path.exists(frontend_dist):
    app.mount("/assets", StaticFiles(directory=os.path.join(frontend_dist, "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_react_app(full_path: str):
        return FileResponse(os.path.join(frontend_dist, "index.html"))