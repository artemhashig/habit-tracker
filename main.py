"""Grit — FastAPI backend: трекер привычек + чат-дневник с ИИ.

Маршруты:
  GET    /api/me                — гостевой профиль (id + имя из таблицы users)
  GET    /api/habits?date=…     — привычки с прогрессом за день (по умолчанию сегодня)
  POST   /api/habits            — создание привычки (для тестов/LLM; UI создаёт только чат)
  POST   /api/habits/{id}/increment?date=…  — клик «+» на конкретный день
  POST   /api/habits/{id}/complete?date=…   — отметить день выполненным
  POST   /api/habits/{id}/set-target  — изменить план (прогресс сохраняется)
  DELETE /api/habits/{id}   — удалить привычку
  POST   /api/chat          — «вылить душу»: текст → действия над привычками
  GET    /api/chat/history  — история диалога
  GET    /api/wellbeing          — зона + статистика недели (green/yellow/red)
  GET    /api/wellbeing/pending  — ре-анализ по созревшим контрольным точкам

Гостевая система вместо паролей: браузер хранит X-Device-ID в localStorage и шлёт
его в каждом запросе; при первом визите в таблице users создаётся запись-гость.
Все привычки/логи/история чата изолированы по этому идентификатору — устройства
не видят и не меняют данные друг друга. Статика: frontend/dist как PWA.
"""
import logging
import os
from datetime import date, timedelta

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import db
import llm
import wellbeing
from llm import parse_intent

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Grit — Habits & Diary API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

log = logging.getLogger("app")
log.info(
    "LLM: model=%s base=%s key=%s",
    llm.LLM_MODEL,
    llm.LLM_BASE_URL,
    "задан (нейронка подключена)" if llm.LLM_API_KEY else "нет — работает fallback-парсер",
)


# --- Схемы запросов -----------------------------------------------------------

class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class HabitIn(BaseModel):
    """Создание привычки через API (интерфейс создаёт привычки только через чат)."""
    title: str = Field(min_length=1, max_length=120)
    category: str = Field(default="Другое", max_length=60)
    emoji: str = Field(default="", max_length=8)
    days: list[str] | None = None      # None → все 7 дней
    target: int = Field(default=1, ge=1, le=100000)
    unit: str = Field(default="раз", max_length=40)


def _device(request: Request) -> str:
    """Идентификатор устройства из заголовка X-Device-ID (браузер хранит его в localStorage).

    Заодно регистрирует гостя в таблице users: первая запись создаётся один раз,
    дальше «ON CONFLICT DO NOTHING»."""
    device = (request.headers.get("X-Device-ID") or "").strip()[:64]
    db.ensure_user(device)
    return device


def _parse_day(raw: str) -> date | None:
    """YYмм-DD строка запроса → date; кривое значение → None (сервер возьмёт сегодня)."""
    try:
        return date.fromisoformat((raw or "").strip())
    except ValueError:
        return None


# --- Пользователи ----------------------------------------------------------------

@app.get("/api/me")
async def me(request: Request):
    """Гостевой профиль устройства (создаётся автоматически при первом запросе)."""
    device = _device(request)
    return db.get_user(device) or {"id": device, "name": "Гость", "created_at": None}


# --- Привычки -----------------------------------------------------------------

@app.get("/api/habits")
async def get_habits(request: Request, day: str = Query(default="", alias="date")):
    """Привычки с прогрессом за указанный день (?date=YYYY-MM-DD, по умолчанию сегодня)."""
    return db.list_habits(_device(request), _parse_day(day))


@app.post("/api/habits", status_code=201)
async def create_habit(body: HabitIn, request: Request):
    """Создание привычки вручную (форма «Новая привычка»)."""
    return db.add_habit(
        title=body.title,
        category=body.category,
        emoji=body.emoji,
        days=body.days,
        target=body.target,
        unit=body.unit,
        device=_device(request),
    )


@app.post("/api/habits/{habit_id}/increment")
async def increment_habit(
    habit_id: int, request: Request, day: str = Query(default="", alias="date")
):
    """Клик «+» на конкретный день (?date=YYYY-MM-DD, по умолчанию сегодня)."""
    habit = db.increment(habit_id, _device(request), day=_parse_day(day))
    if not habit:
        return {"error": "Not found"}
    return habit


@app.post("/api/habits/{habit_id}/complete")
async def complete_habit(
    habit_id: int, request: Request, day: str = Query(default="", alias="date")
):
    """Отметить день выполненным (?date=YYYY-MM-DD, по умолчанию сегодня)."""
    habit = db.complete_today(habit_id, _device(request), day=_parse_day(day))
    if not habit:
        return {"error": "Not found"}
    return habit


@app.post("/api/habits/{habit_id}/set-target")
async def set_habit_target(habit_id: int, request: Request, body: dict[str, int] | None = None):
    target = int((body or {}).get("target", 1))
    habit = db.set_target(habit_id, target, _device(request))
    if not habit:
        return {"error": "Not found"}
    return habit


@app.delete("/api/habits/{habit_id}")
async def delete_habit(habit_id: int, request: Request):
    return {"deleted": db.delete_habit(habit_id, _device(request))}


@app.delete("/api/categories/{category}")
async def delete_category(category: str, request: Request):
    """Удаление категории: все её привычки и их прогресс исчезают."""
    return {"deleted": db.delete_category(category, _device(request))}


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


def _apply_actions(actions: list[dict], device: str = "") -> list[dict]:
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
                device=device,
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
                habit = db.get_habit(int(habit_id), device)
            if habit is None and habit_title:
                habit = db.find_habit(str(habit_title), device)
            if not habit:
                continue
            new_target = act.get("new_target")
            if new_target is None:
                new_target = max(1, round(habit["target"] / 2))
            new_target = max(1, int(new_target))
            if new_target >= habit["target"]:
                continue  # снижение должно быть снижением
            old = habit["target"]
            updated = db.set_target(habit["id"], new_target, device)
            applied.append({
                "type": "reduce_habit",
                "habit_id": updated["id"],
                "text": f"Планка снижена: «{updated['title']}» {old} → {new_target} за день",
            })
        elif kind == "delete_habit":
            habit = db.find_habit(str(act.get("habit_title") or ""), device)
            if habit and db.delete_habit(habit["id"], device):
                applied.append({
                    "type": "delete_habit",
                    "habit_id": habit["id"],
                    "text": f"Привычка «{habit['title']}» удалена",
                })
        elif kind == "freeze_habit":
            # Временная заморозка: пауза без потери прогресса.
            habit = None
            habit_id = act.get("habit_id")
            habit_title = act.get("habit_title")
            if isinstance(habit_id, int) or (
                isinstance(habit_id, str) and habit_id.isdigit()
            ):
                habit = db.get_habit(int(habit_id), device)
            if habit is None and habit_title:
                habit = db.find_habit(str(habit_title), device)
            if habit:
                days = max(1, int(act.get("days") or 7))
                updated = db.set_freeze(habit["id"], device, days)
                until = (
                    (date.today() + timedelta(days=days - 1)).strftime("%d.%m")
                )
                applied.append({
                    "type": "freeze_habit",
                    "habit_id": updated["id"],
                    "text": (
                        f"«{updated['title']}» на паузе до {until} — "
                        "прогресс и серия сохранены, дни заморозки не считаются пропущенными"
                    ),
                })
        elif kind == "set_checkpoint":
            # Контрольная точка: ре-анализ через N дней со сравнением статистики.
            days = min(14, max(1, int(act.get("days") or 3)))
            if db.has_pending_checkpoint(device):
                applied.append({
                    "type": "set_checkpoint",
                    "text": "Контрольная точка уже активна — продолжаю наблюдение и вернусь вовремя",
                })
            else:
                info = wellbeing.overview(device)
                db.add_checkpoint(
                    device,
                    due_at=date.today() + timedelta(days=days),
                    note=str(act.get("note") or act.get("reason") or "")[:200],
                    baseline_pct=info["pct"],
                    baseline_skipped=info["skippedDays"],
                )
                applied.append({
                    "type": "set_checkpoint",
                    "text": (
                        f"Контрольная точка через {days} дн. — вернусь со сравнением "
                        f"статистики (сейчас: {info['pct'] if info['pct'] is not None else '—'}%)"
                    ),
                })
        # «none» / неизвестные типы — просто пропускаем

    return applied


@app.post("/api/chat")
async def chat(body: ChatIn, request: Request):
    """Приём сообщения: поток сознания → NLP → structured habits в базе."""
    device = _device(request)
    message = body.message.strip()
    user_msg_id = db.add_chat_message("user", message, None, device)

    habits = db.list_habits(device)
    history = db.get_chat_history(device, limit=12)

    # Проактивная модель: зона недели + прямой сигнал усталости
    fatigue = llm.detect_fatigue(message)
    info = wellbeing.overview(device, fatigue=fatigue)
    wellbeing_ctx = {"zone": info["zone"], "stats": info, "prompt": info["prompt"]}

    try:
        plan = await parse_intent(message, habits, history[:-1], wellbeing_ctx)
    except Exception:
        logging.getLogger("chat").exception("NLP parse failed")
        plan = {
            "reply": "Я временно не в форме, но я всё записал. Давай попробуем ещё раз чуть позже.",
            "actions": [{"type": "none"}],
        }

    applied = _apply_actions(plan.get("actions") or [], device)
    reply = plan.get("reply") or "Принял."

    assistant_msg_id = db.add_chat_message(
        "assistant", reply, applied or None, device
    )

    return {
        "reply": reply,
        "applied": applied,
        "user_message_id": user_msg_id,
        "assistant_message_id": assistant_msg_id,
    }


@app.get("/api/chat/history")
async def chat_history(request: Request):
    return db.get_chat_history(_device(request))


@app.delete("/api/chat/history")
async def chat_clear(request: Request):
    db.clear_chat(_device(request))
    return {"ok": True}


# --- Wellbeing: проактивная модель ----------------------------------------------

@app.get("/api/wellbeing")
async def wellbeing_status(request: Request):
    """Зона green/yellow/red + статистика недели + активные контрольные точки."""
    device = _device(request)
    info = wellbeing.overview(device)
    info["checkpoints"] = db.list_checkpoints(device)
    return info


@app.get("/api/wellbeing/pending")
async def wellbeing_pending(request: Request):
    """Созревшие контрольные точки → сравнение «до/после» и реплика ассистента.

    Фронтенд вызывает при открытии приложения; точка помечается отработанной,
    сразу ставится следующая — наблюдение продолжается автоматически."""
    return wellbeing.consume_pending(_device(request))


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
        # index.html — всегда свежий (Safari любит кэшировать его мёртвым грузом,
        # тогда после обновления интерфейс остаётся старым)
        return FileResponse(
            os.path.join(frontend_dist, "index.html"),
            headers={"Cache-Control": "no-store"},
        )
