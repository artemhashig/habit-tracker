"""Grit — FastAPI backend: трекер привычек + чат-дневник с ИИ.

Маршруты:
  GET    /api/habits        — привычки с прогрессом за сегодня
  POST   /api/habits/{id}/increment   — клик «+»
  POST   /api/habits/{id}/complete    — отметить день выполненным
  POST   /api/habits/{id}/set-target  — изменить план (прогресс сохраняется)
  DELETE /api/habits/{id}   — удалить привычку
  POST   /api/chat          — «вылить душу»: текст → действия над привычками
  GET    /api/chat/history  — история диалога

Статика: собранный фронтенд (frontend/dist) раздаётся как PWA.
"""
import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import db
from llm import parse_intent

logging.basicConfig(level=logging.INFO)

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Grit — Habits & Diary API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Схемы запросов -----------------------------------------------------------

class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class HabitIn(BaseModel):
    """Ручное создание привычки из формы «Новая привычка»."""
    title: str = Field(min_length=1, max_length=120)
    category: str = Field(default="Другое", max_length=60)
    emoji: str = Field(default="", max_length=8)
    days: list[str] | None = None      # None → все 7 дней
    target: int = Field(default=1, ge=1, le=100000)
    unit: str = Field(default="раз", max_length=40)


# --- Привычки -----------------------------------------------------------------

@app.get("/api/habits")
async def get_habits():
    return db.list_habits()


@app.post("/api/habits", status_code=201)
async def create_habit(body: HabitIn):
    """Создание привычки вручную (форма «Новая привычка»)."""
    return db.add_habit(
        title=body.title,
        category=body.category,
        emoji=body.emoji,
        days=body.days,
        target=body.target,
        unit=body.unit,
    )


@app.post("/api/habits/{habit_id}/increment")
async def increment_habit(habit_id: int):
    habit = db.increment(habit_id)
    if not habit:
        return {"error": "Not found"}
    return habit


@app.post("/api/habits/{habit_id}/complete")
async def complete_habit(habit_id: int):
    habit = db.complete_today(habit_id)
    if not habit:
        return {"error": "Not found"}
    return habit


@app.post("/api/habits/{habit_id}/set-target")
async def set_habit_target(habit_id: int, body: dict[str, int] | None = None):
    target = int((body or {}).get("target", 1))
    habit = db.set_target(habit_id, target)
    if not habit:
        return {"error": "Not found"}
    return habit


@app.delete("/api/habits/{habit_id}")
async def delete_habit(habit_id: int):
    return {"deleted": db.delete_habit(habit_id)}


@app.delete("/api/categories/{category}")
async def delete_category(category: str):
    """Удаление категории: все её привычки и их прогресс исчезают."""
    return {"deleted": db.delete_category(category)}


# --- Чат-модуль ----------------------------------------------------------------

def _coerce_days(raw) -> list[str] | None:
    """Дни от LLM → список кодов недели или None («каждый день»)."""
    if raw is None:
        return None
    if isinstance(raw, list):
        text = " ".join(str(d).lower() for d in raw)
    else:
        text = str(raw).lower()
    days = [d for d in db.DAY_CODES if d.lower() in text]
    if days:
        return days
    if "выходн" in text:
        return ["Сб", "Вс"]
    if "будням" in text or "будни" in text:
        return list(db.DAY_CODES[:5])
    if any(word in text for word in ("каждый", "ежедневно", "каждый день", "все")):
        return None  # все 7 дней
    return None


def _apply_actions(actions: list[dict]) -> list[dict]:
    """Применяет действия из разбора к базе. Возвращает описание в UI-чипах."""
    applied: list[dict] = []

    for act in actions or []:
        kind = (act.get("type") or "").lower().strip()
        if kind == "add_habit":
            title = str(act.get("title") or "").strip()
            if not title:
                continue
            days = _coerce_days(act.get("days"))
            unit = str(act.get("unit") or "раз")
            habit = db.add_habit(
                title=title,
                category=str(act.get("category") or "Другое"),
                emoji=str(act.get("emoji") or ""),
                days=days,
                target=int(act.get("target") or 1),
                unit=unit,
            )
            applied.append({
                "type": "add_habit",
                "habit_id": habit["id"],
                "text": (
                    f"Добавлена привычка «{habit['title']}» — "
                    f"{habit['daysLabel'].lower()}, "
                    f"{habit['target']} {db.plural_count(habit['target'], habit['unit'])} в день"
                ),
            })
        elif kind == "reduce_habit":
            habit = None
            habit_id = act.get("habit_id")
            habit_title = act.get("habit_title")
            if isinstance(habit_id, int) or (
                isinstance(habit_id, str) and habit_id.isdigit()
            ):
                habit = db.get_habit(int(habit_id))
            if habit is None and habit_title:
                habit = db.find_habit(str(habit_title))
            if not habit:
                continue
            new_target = act.get("new_target")
            if new_target is None:
                new_target = max(1, round(habit["target"] / 2))
            new_target = max(1, int(new_target))
            if new_target >= habit["target"]:
                continue  # снижение должно быть снижением
            old = habit["target"]
            updated = db.set_target(habit["id"], new_target)
            applied.append({
                "type": "reduce_habit",
                "habit_id": updated["id"],
                "text": f"Планка снижена: «{updated['title']}» {old} → {new_target} за день",
            })
        elif kind == "delete_habit":
            habit = db.find_habit(str(act.get("habit_title") or ""))
            if habit and db.delete_habit(habit["id"]):
                applied.append({
                    "type": "delete_habit",
                    "habit_id": habit["id"],
                    "text": f"Привычка «{habit['title']}» удалена",
                })
        # «none» / неизвестные типы — просто пропускаем

    return applied


@app.post("/api/chat")
async def chat(body: ChatIn):
    """Приём сообщения: поток сознания → NLP → structured habits в базе."""
    message = body.message.strip()
    user_msg_id = db.add_chat_message("user", message)

    habits = db.list_habits()
    history = db.get_chat_history(limit=12)

    try:
        plan = await parse_intent(message, habits, history[:-1])
    except Exception:
        logging.getLogger("chat").exception("NLP parse failed")
        plan = {
            "reply": "Я временно не в форме, но я всё записал. Давай попробуем ещё раз чуть позже.",
            "actions": [{"type": "none"}],
        }

    applied = _apply_actions(plan.get("actions") or [])
    reply = plan.get("reply") or "Принял."

    assistant_msg_id = db.add_chat_message(
        "assistant", reply, actions=applied or None
    )

    return {
        "reply": reply,
        "applied": applied,
        "user_message_id": user_msg_id,
        "assistant_message_id": assistant_msg_id,
    }


@app.get("/api/chat/history")
async def chat_history():
    return db.get_chat_history()


@app.delete("/api/chat/history")
async def chat_clear():
    db.clear_chat()
    return {"ok": True}


# --- Статика PWA ----------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
frontend_dist = os.path.join(BASE_DIR, "frontend", "dist")

if os.path.exists(frontend_dist):
    assets_dir = os.path.join(frontend_dist, "assets")
    if os.path.exists(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}")
    async def serve_react_app(full_path: str):
        file_path = os.path.join(frontend_dist, full_path)
        if os.path.exists(file_path) and os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(frontend_dist, "index.html"))
