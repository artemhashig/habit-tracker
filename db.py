"""SQLite-хранилище приложения: привычки, дневные логи, история чата.

База лежит в каталоге DATA_DIR (/data на Amvera сохраняется между деплоями),
поэтому прогресс пользователей не сбрасывается при перезапуске контейнера.

Изоляция устройств: каждый браузер шлёт свой X-Device-ID, и все привычки/логи/
история чата выдаются и меняются только в рамках этого идентификатора —
10 человек на одном сайте не видят и не меняют данные друг друга.
Старые записи (без device) остаются «ничьими» и никому не показываются.
"""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta

# --- Пути -------------------------------------------------------------------

DATA_DIR = os.getenv("DATA_DIR") or ("/data" if os.path.isdir("/data") else ".")
DB_PATH = os.path.join(DATA_DIR, "app.db")

DAY_CODES = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


@contextmanager
def connection():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    try:
        yield con
        con.commit()
    finally:
        con.close()


# канонические базовые формы единиц (единственное число, им. падеж)
_UNIT_CANON = {
    "минут": "минута", "минуты": "минута", "минуту": "минута", "мин": "минута",
    "страниц": "страница", "страницы": "страница", "страницу": "страница",
    "разов": "раз", "раза": "раз", "раз": "раз",
    "повторений": "повторение", "повторения": "повторение", "повторени": "повторение",
    "стаканов": "стакан", "стакана": "стакан",
    "километров": "километр", "километра": "километр", "км": "км",
    "сеансов": "сеанс", "сеанса": "сеанс",
    "книг": "книга", "книги": "книга",
    "часов": "минута", "часа": "минута", "час": "минута",
}


def init_db():
    """Создаёт таблицы (с демо-данными больше не сеем — люди начинают с нуля)."""
    with connection() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS habits (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                title       TEXT NOT NULL,
                category    TEXT NOT NULL DEFAULT 'Другое',
                emoji       TEXT NOT NULL DEFAULT '',
                days        TEXT NOT NULL,                 -- JSON: ["Пн","Вт"]
                target      INTEGER NOT NULL DEFAULT 1,    -- план на день
                unit        TEXT NOT NULL DEFAULT 'раз',   -- ед. изм. в ед. числе
                created_at  TEXT NOT NULL,                 -- YYYY-MM-DD
                device      TEXT NOT NULL DEFAULT ''       -- X-Device-ID владельца
            );
            CREATE TABLE IF NOT EXISTS habit_logs (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                habit_id  INTEGER NOT NULL REFERENCES habits(id) ON DELETE CASCADE,
                day       TEXT NOT NULL,                 -- YYYY-MM-DD
                count     INTEGER NOT NULL DEFAULT 0,
                UNIQUE (habit_id, day)
            );
            CREATE TABLE IF NOT EXISTS chat_messages (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                role        TEXT NOT NULL,               -- user / assistant
                content     TEXT NOT NULL,
                actions     TEXT,                        -- JSON применённых действий
                created_at  TEXT NOT NULL,
                device      TEXT NOT NULL DEFAULT ''     -- X-Device-ID владельца
            );
            """
        )
        # Миграция старых баз (созданных до появления device): добавляем колонку.
        for table in ("habits", "chat_messages"):
            cols = {r[1] for r in c.execute(f"PRAGMA table_info({table})")}
            if "device" not in cols:
                c.execute(
                    f"ALTER TABLE {table} ADD COLUMN device TEXT NOT NULL DEFAULT ''"
                )


# --- Вспомогательное ----------------------------------------------------------

def _plural_ru(n: int, one: str, few: str, many: str) -> str:
    """Формы счисления: 1 повторение / 2 повторения / 5 повторений."""
    n = abs(n) % 100
    if 11 <= n <= 14:
        return many
    d = n % 10
    if d == 1:
        return one
    if 2 <= d <= 4:
        return few
    return many


def plural_count(n: int, unit: str) -> str:
    """84 + 'повторение' → 'повторений' и т.п."""
    u = (unit or "раз").strip().lower()
    table = {
        "повторение": ("повторение", "повторения", "повторений"),
        "сеанс": ("сеанс", "сеанса", "сеансов"),
        "минута": ("минута", "минуты", "минут"),
        "минут": ("минута", "минуты", "минут"),
        "страница": ("страница", "страницы", "страниц"),
        "стакан": ("стакан", "стакана", "стаканов"),
        "километр": ("километр", "километра", "километров"),
        "км": ("километр", "километра", "километров"),
        "книга": ("книга", "книги", "книг"),
    }
    one, few, many = table.get(u, (u, u + "а", u + "ов"))
    return _plural_ru(n, one, few, many)


def days_label(days: list[str]) -> str:
    dayset = [d for d in DAY_CODES if d in days]
    if len(dayset) == 7:
        return "Каждый день"
    if len(dayset) == 6 and set(dayset) == set(DAY_CODES[:6]):
        return "Пн – Сб"
    if len(dayset) == 5 and set(dayset) == set(DAY_CODES[:5]):
        return "Пн – Пт"
    return ", ".join(dayset) if dayset else "Гибкий график"


def _weekday_ru(d: date) -> str:
    return DAY_CODES[d.weekday()]


def _owned_id(c: sqlite3.Connection, habit_id: int, device: str) -> int | None:
    """id привычки, если она принадлежит устройству; иначе None."""
    row = c.execute(
        "SELECT id FROM habits WHERE id=? AND device=?", (habit_id, device)
    ).fetchone()
    return row["id"] if row else None


# --- Привычки -----------------------------------------------------------------

def _calc_streak(c: sqlite3.Connection, habit_id: int, days: list[str], today: date) -> int:
    """Серия закрытых запланированных дней, от сегодня назад."""
    streak = 0
    d = today
    for _ in range(60):  # дальше 60 суток историю не считаем
        if _weekday_ru(d) in days:
            log = c.execute(
                "SELECT count FROM habit_logs WHERE habit_id=? AND day=?",
                (habit_id, d.isoformat()),
            ).fetchone()
            if not log or log["count"] == 0:
                if d == today:  # сегодня ещё никто не начинал — серия не сломана
                    break
                return streak
            streak += 1
        d -= timedelta(days=1)
    return streak


def _calc_deficit(
    c: sqlite3.Connection, habit_id: int, days: list[str], created: str, today: date
) -> int:
    """Сколько запланированных дней пропущено с даты создания до вчера."""
    try:
        start = date.fromisoformat(created)
    except (ValueError, TypeError):
        return 0
    target_row = c.execute(
        "SELECT target FROM habits WHERE id=?", (habit_id,)
    ).fetchone()
    target = target_row["target"] if target_row else 0
    missed = 0
    d = today - timedelta(days=1)
    while d >= start and (today - d).days <= 60:
        if _weekday_ru(d) in days:
            log = c.execute(
                "SELECT count FROM habit_logs WHERE habit_id=? AND day=?",
                (habit_id, d.isoformat()),
            ).fetchone()
            if not log or log["count"] < target:
                missed += 1
        d -= timedelta(days=1)
    return missed


def _row_to_habit(c: sqlite3.Connection, row: sqlite3.Row, today: date) -> dict:
    """Собирает полную карточку привычки: прогресс дня, серия, отставание."""
    days = json.loads(row["days"])
    log = c.execute(
        "SELECT count FROM habit_logs WHERE habit_id=? AND day=?",
        (row["id"], today.isoformat()),
    ).fetchone()
    current = log["count"] if log else 0
    scheduled_today = _weekday_ru(today) in days
    done = row["target"] > 0 and current >= row["target"]
    status = "done" if done and (scheduled_today or current > 0) else "behind"

    streak = _calc_streak(c, row["id"], days, today)
    deficit = _calc_deficit(c, row["id"], days, row["created_at"], today)

    label = days_label(days)
    schedule_text = (
        f"{label}, {current}/{row['target']} {plural_count(row['target'], row['unit'])}"
    )
    return {
        "id": row["id"],
        "title": row["title"],
        "category": row["category"],
        "emoji": row["emoji"],
        "days": days,
        "daysLabel": label,
        "target": row["target"],
        "unit": row["unit"],
        "current": current,
        "streak": streak,
        "deficit": deficit,
        "status": status,
        "scheduledToday": scheduled_today,
        "scheduleText": schedule_text,
    }


def list_habits(device: str) -> list[dict]:
    today = date.today()
    with connection() as c:
        rows = c.execute(
            "SELECT * FROM habits WHERE device=? ORDER BY id", (device,)
        ).fetchall()
        return [_row_to_habit(c, r, today) for r in rows]


def get_habit(habit_id: int, device: str) -> dict | None:
    today = date.today()
    with connection() as c:
        row = c.execute(
            "SELECT * FROM habits WHERE id=? AND device=?", (habit_id, device)
        ).fetchone()
        return _row_to_habit(c, row, today) if row else None


def find_habit(title: str | None, device: str) -> dict | None:
    """Нечувствительный к регистру поиск по подстроке названия (в рамках устройства)."""
    if not title:
        return None
    today = date.today()
    with connection() as c:
        rows = c.execute(
            "SELECT * FROM habits WHERE device=? ORDER BY id", (device,)
        ).fetchall()
        t = title.lower().strip()
        for row in rows:  # точное совпадение приоритетнее
            if row["title"].lower() == t:
                return _row_to_habit(c, row, today)
        for row in rows:
            if t in row["title"].lower():
                return _row_to_habit(c, row, today)
    return None


def add_habit(
    title: str,
    category: str = "Другое",
    emoji: str = "",
    days: list[str] | None = None,
    target: int = 1,
    unit: str = "раз",
    device: str = "",
) -> dict:
    """Создаёт привычку и возвращает её в формате выдачи API."""
    valid_days = [d for d in (days or []) if d in DAY_CODES] or list(DAY_CODES)
    title = (title or "").strip() or "Новая привычка"
    title = title[:1].upper() + title[1:]  # «медитация» → «Медитация»
    unit_raw = (unit or "раз").strip().lower()
    unit = _UNIT_CANON.get(unit_raw, unit_raw)  # «минут» → «минута»
    with connection() as c:
        cur = c.execute(
            "INSERT INTO habits (title, category, emoji, days, target, unit, created_at, device)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                title,
                (category or "Другое").strip() or "Другое",
                (emoji or "").strip(),
                json.dumps(valid_days),
                max(1, int(target or 1)),
                unit,
                date.today().isoformat(),
                device,
            ),
        )
        habit_id = cur.lastrowid
    return get_habit(habit_id, device)  # type: ignore[return-value]


def set_target(habit_id: int, new_target: int, device: str) -> dict | None:
    """Снижает/повышает план. Прогресс дня при этом не сбрасывается."""
    with connection() as c:
        c.execute(
            "UPDATE habits SET target=? WHERE id=? AND device=?",
            (max(1, int(new_target)), habit_id, device),
        )
    return get_habit(habit_id, device)


def delete_habit(habit_id: int, device: str) -> bool:
    with connection() as c:
        if _owned_id(c, habit_id, device) is None:
            return False
        c.execute("DELETE FROM habit_logs WHERE habit_id=?", (habit_id,))
        cur = c.execute("DELETE FROM habits WHERE id=? AND device=?", (habit_id, device))
        return cur.rowcount > 0


def delete_category(name: str, device: str) -> int:
    """Удаляет все привычки категории вместе с их прогрессом.

    Пустых категорий в приложении не бывает: как только удалена последняя
    привычка, категория исчезает сама (список категорий выводится из привычек).
    Возвращает число удалённых привычек."""
    with connection() as c:
        ids = [
            r["id"] for r in c.execute(
                "SELECT id FROM habits WHERE category=? AND device=?", (name, device)
            ).fetchall()
        ]
        for i in ids:
            c.execute("DELETE FROM habit_logs WHERE habit_id=?", (i,))
        cur = c.execute(
            "DELETE FROM habits WHERE category=? AND device=?", (name, device)
        )
        return cur.rowcount


def increment(habit_id: int, device: str, step: int = 1) -> dict | None:
    """Клик «+»: увеличивает сегодняшний счётчик, не трогая историю."""
    day = date.today().isoformat()
    with connection() as c:
        if _owned_id(c, habit_id, device) is None:
            return None
        c.execute(
            "INSERT INTO habit_logs (habit_id, day, count) VALUES (?, ?, ?)"
            " ON CONFLICT(habit_id, day) DO UPDATE SET count = count + excluded.count",
            (habit_id, day, step),
        )
    return get_habit(habit_id, device)


def complete_today(habit_id: int, device: str) -> dict | None:
    """Отмечает сегодняшний день выполненным (прогресс = план)."""
    habit = get_habit(habit_id, device)
    if not habit:
        return None
    return set_progress(habit_id, habit["target"], device)


def set_progress(habit_id: int, count: int, device: str) -> dict | None:
    with connection() as c:
        if _owned_id(c, habit_id, device) is None:
            return None
        c.execute(
            "INSERT INTO habit_logs (habit_id, day, count) VALUES (?, ?, ?)"
            " ON CONFLICT(habit_id, day) DO UPDATE SET count = excluded.count",
            (habit_id, date.today().isoformat(), max(0, int(count))),
        )
    return get_habit(habit_id, device)


# --- Чат -----------------------------------------------------------------------

def add_chat_message(role: str, content: str, actions: list | None, device: str) -> int:
    with connection() as c:
        cur = c.execute(
            "INSERT INTO chat_messages (role, content, actions, created_at, device)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                role,
                content,
                json.dumps(actions, ensure_ascii=False) if actions else None,
                date.today().isoformat(),
                device,
            ),
        )
        return cur.lastrowid


def get_chat_history(device: str, limit: int = 50) -> list[dict]:
    with connection() as c:
        rows = c.execute(
            "SELECT id, role, content, actions FROM chat_messages"
            " WHERE device=? ORDER BY id",
            (device,),
        ).fetchall()
    return [
        {
            "id": r["id"],
            "role": r["role"],
            "content": r["content"],
            "actions": json.loads(r["actions"]) if r["actions"] else [],
        }
        for r in rows[-limit:]
    ]


def clear_chat(device: str):
    with connection() as c:
        c.execute("DELETE FROM chat_messages WHERE device=?", (device,))


init_db()
