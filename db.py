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
import re
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
    "подходов": "подход", "подхода": "подход", "подход": "подход",
    "отжиманий": "отжимание", "отжимания": "отжимание", "отжимание": "отжимание",
    "упражнений": "упражнение", "упражнения": "упражнение",
    "звонков": "звонок", "звонка": "звонок", "звонки": "звонок", "звонок": "звонок",
    "звонку": "звонок",
}


def canon_unit(unit_raw: str) -> str:
    """Единица к именительному падежу: словарь, затем грубая нормализация
    незнакомых слов («лабу», «лабы» → «лаба»; «подходы» → «подход»)."""
    u = (unit_raw or "раз").strip().lower()
    canon = _UNIT_CANON.get(u)
    if canon:
        return canon
    for suf, repl in (("у", "а"), ("ю", "я"), ("ы", "а")):
        if u.endswith(suf) and len(u) > 3:
            cand = u[:-1] + repl
            if cand in _UNIT_CANON:
                return _UNIT_CANON[cand]
            return cand
    return u


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
                device      TEXT NOT NULL DEFAULT '',      -- X-Device-ID владельца
                frozen_from TEXT,                          -- пауза «с» (YYYY-MM-DD)
                frozen_until TEXT                           -- пауза «до» (включительно)
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
            CREATE TABLE IF NOT EXISTS chat_drafts (
                device     TEXT PRIMARY KEY,
                kind       TEXT NOT NULL DEFAULT 'habit',
                data       TEXT NOT NULL,           -- JSON незавершённого интервью
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS users (
                id         TEXT PRIMARY KEY,            -- X-Device-ID из localStorage
                name       TEXT NOT NULL DEFAULT 'Гость',
                created_at TEXT NOT NULL                -- YYYY-MM-DD
            );
            CREATE TABLE IF NOT EXISTS checkpoints (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                device           TEXT NOT NULL,
                created_at       TEXT NOT NULL,          -- YYYY-MM-DD
                due_at           TEXT NOT NULL,          -- когда нужен ре-анализ
                baseline_pct     REAL,                   -- % выполнения на момент создания
                baseline_skipped INTEGER,                -- пропусков на момент создания
                note             TEXT DEFAULT '',
                processed        INTEGER NOT NULL DEFAULT 0
            );
            """
        )
        # Миграция старых баз: недостающие колонки добавляем на месте.
        for table, column, ddl in (
            ("habits", "device", "TEXT NOT NULL DEFAULT ''"),
            ("habits", "frozen_from", "TEXT"),
            ("habits", "frozen_until", "TEXT"),
            ("habits", "step", "INTEGER NOT NULL DEFAULT 1"),
            ("chat_messages", "device", "TEXT NOT NULL DEFAULT ''"),
        ):
            cols = {r[1] for r in c.execute(f"PRAGMA table_info({table})")}
            if column not in cols:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


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
        "подход": ("подход", "подхода", "подходов"),
        "отжимание": ("отжимание", "отжимания", "отжиманий"),
        "упражнение": ("упражнение", "упражнения", "упражнений"),
        "звонок": ("звонок", "звонка", "звонков"),
    }
    forms = table.get(u)
    if forms is None:
        # наивное склонение незнакомой единицы («лаба» → «лабы», «лаб»)
        if u.endswith("а"):
            forms = (u, u[:-1] + "ы", u[:-1])
        elif u.endswith("я"):
            forms = (u, u[:-1] + "и", u[:-1] + "й")
        elif u.endswith("о"):
            forms = (u, u[:-1] + "а", u[:-1])
        else:
            forms = (u, u + "а", u + "ов")
    one, few, many = forms
    return _plural_ru(n, one, few, many)


_DAYS_INTERVAL_RE = re.compile(r"^каждые(\d{1,2})$")


def _scheduled_on(d: date, days: list[str], created: date | None = None) -> bool:
    """День d попадает в график привычки.

    График хранится токенами:
      «Пн»…«Вс»  — дни недели;
      «1»…«31»   — дни месяца;
      «каждыеN»  — интервал «каждые N дней» (отсчёт от даты создания).
    Смешанный график: достаточно любого совпавшего токена."""
    for tok in days or []:
        if tok in DAY_CODES:
            if _weekday_ru(d) == tok:
                return True
        elif tok.isdigit():
            if d.day == int(tok):
                return True
        else:
            m = _DAYS_INTERVAL_RE.match(tok)
            if m:
                base = created or d
                if d >= base and (d - base).days % max(1, int(m.group(1))) == 0:
                    return True
    return False


def days_label(days: list[str]) -> str:
    weekdays = [d for d in DAY_CODES if d in days]
    month_days = sorted(int(t) for t in days if str(t).isdigit())
    interval = next(
        (t for t in days if _DAYS_INTERVAL_RE.match(str(t))), None
    )
    parts: list[str] = []
    if interval:
        parts.append(f"каждые {_DAYS_INTERVAL_RE.match(interval).group(1)} дн.")
    if weekdays:
        if len(weekdays) == 7:
            parts.append("каждый день")
        elif len(weekdays) == 6 and set(weekdays) == set(DAY_CODES[:6]):
            parts.append("Пн – Сб")
        elif len(weekdays) == 5 and set(weekdays) == set(DAY_CODES[:5]):
            parts.append("Пн – Пт")
        else:
            parts.append(", ".join(weekdays))
    if month_days:
        if len(month_days) <= 2:
            nums = " и ".join(f"{n}-го" for n in month_days)
        else:
            nums = ", ".join(f"{n}-го" for n in month_days[:-1]) + f" и {month_days[-1]}-го"
        parts.append(f"{nums} числа месяца")
    if not parts:
        return "Гибкий график"
    out = ", ".join(parts)
    return out[:1].upper() + out[1:]


def _weekday_ru(d: date) -> str:
    return DAY_CODES[d.weekday()]


def _owned_id(c: sqlite3.Connection, habit_id: int, device: str) -> int | None:
    """id привычки, если она принадлежит устройству; иначе None."""
    row = c.execute(
        "SELECT id FROM habits WHERE id=? AND device=?", (habit_id, device)
    ).fetchone()
    return row["id"] if row else None


# --- Пользователи (гостевая система без паролей) ---------------------------------

def ensure_user(device: str, name: str = "Гость") -> str | None:
    """Регистрирует гостя при первом запросе: id = X-Device-ID из localStorage.

    Паролей нет — идентификатор устройства сам является профилем; повторные
    вызовы ничего не перезаписывают."""
    if not device:
        return None
    with connection() as c:
        c.execute(
            "INSERT INTO users (id, name, created_at) VALUES (?, ?, ?)"
            " ON CONFLICT(id) DO NOTHING",
            (device, (name or "Гость")[:60], date.today().isoformat()),
        )
    return device


def get_user(device: str) -> dict | None:
    """Профиль гостя: id, имя, дата первого визита."""
    with connection() as c:
        row = c.execute(
            "SELECT id, name, created_at FROM users WHERE id=?", (device,)
        ).fetchone()
    return dict(row) if row else None


# --- Заморозка (пауза привычки без потери прогресса) ----------------------------

def _frozen_window(row: sqlite3.Row) -> tuple[date | None, date | None]:
    """(от, до) окна заморозки привычки; None — заморозки нет."""
    start = end = None
    try:
        if row["frozen_from"]:
            start = date.fromisoformat(row["frozen_from"])
    except (ValueError, TypeError):
        pass
    try:
        if row["frozen_until"]:
            end = date.fromisoformat(row["frozen_until"])
    except (ValueError, TypeError):
        pass
    return start, end


def _on_freeze(d: date, window: tuple[date | None, date | None]) -> bool:
    """Попадает ли день в окно заморозки (нейтральный день: не план, не пропуск)."""
    start, end = window
    if not end:
        return False
    if start and d < start:
        return False
    return d <= end


# --- Привычки -----------------------------------------------------------------

def _calc_streak(
    c: sqlite3.Connection, habit_id: int, days: list[str], today: date,
    window: tuple[date | None, date | None] = (None, None),
    created: date | None = None,
) -> int:
    """Серия закрытых запланированных дней, от сегодня назад (заморозка — нейтрально)."""
    streak = 0
    d = today
    for _ in range(60):  # дальше 60 суток историю не считаем
        if _scheduled_on(d, days, created) and not _on_freeze(d, window):
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
    c: sqlite3.Connection, habit_id: int, days: list[str], created: str, today: date,
    window: tuple[date | None, date | None] = (None, None),
) -> int:
    """Сколько запланированных дней пропущено с даты создания до вчера.

    Дни в окне заморозки не считаются пропущенными — пауза без наказания."""
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
        if _scheduled_on(d, days, start) and not _on_freeze(d, window):
            log = c.execute(
                "SELECT count FROM habit_logs WHERE habit_id=? AND day=?",
                (habit_id, d.isoformat()),
            ).fetchone()
            if not log or log["count"] < target:
                missed += 1
        d -= timedelta(days=1)
    return missed


def _row_to_habit(c: sqlite3.Connection, row: sqlite3.Row, day: date) -> dict:
    """Карточка привычки с прогрессом на конкретный день (не только сегодня)."""
    days = json.loads(row["days"])
    log = c.execute(
        "SELECT count FROM habit_logs WHERE habit_id=? AND day=?",
        (row["id"], day.isoformat()),
    ).fetchone()
    current = log["count"] if log else 0
    window = _frozen_window(row)
    _, freeze_end = window
    frozen = bool(freeze_end and freeze_end >= day)
    try:
        created = date.fromisoformat(row["created_at"])
    except (ValueError, TypeError):
        created = None
    # привычка существует только с даты создания и позже: задним числом
    # она не «запланирована» и не числится пропущенной
    scheduled_today = (
        _scheduled_on(day, days, created)
        and not frozen
        and (created is None or day >= created)
    )
    done = row["target"] > 0 and current >= row["target"]
    status = (
        "frozen" if frozen
        else ("done" if done and (scheduled_today or current > 0) else "behind")
    )

    streak = _calc_streak(c, row["id"], days, day, window, created)
    deficit = _calc_deficit(c, row["id"], days, row["created_at"], day, window)

    label = days_label(days)
    schedule_text = (
        f"{label}, {current}/{row['target']} {plural_count(row['target'], row['unit'])}"
    )
    if frozen:
        schedule_text = f"пауза до {freeze_end.strftime('%d.%m')}, {label}, {current}/{row['target']}"
    return {
        "id": row["id"],
        "title": row["title"],
        "category": row["category"],
        "emoji": row["emoji"],
        "days": days,
        "daysLabel": label,
        "target": row["target"],
        "unit": row["unit"],
        "step": (row["step"] if "step" in row.keys() else 1) or 1,
        "createdAt": row["created_at"],
        "current": current,
        "streak": streak,
        "deficit": deficit,
        "status": status,
        "scheduledToday": scheduled_today,
        "scheduleText": schedule_text,
        "frozen": frozen,
        "frozenUntil": (freeze_end.isoformat() if frozen and freeze_end else None),
    }


def list_habits(device: str, day: date | None = None) -> list[dict]:
    """Привычки устройства с прогрессом на день (по умолчанию — сегодня)."""
    day = day or date.today()
    with connection() as c:
        rows = c.execute(
            "SELECT * FROM habits WHERE device=? ORDER BY id", (device,)
        ).fetchall()
        return [_row_to_habit(c, r, day) for r in rows]


def get_habit(habit_id: int, device: str, day: date | None = None) -> dict | None:
    day = day or date.today()
    with connection() as c:
        row = c.execute(
            "SELECT * FROM habits WHERE id=? AND device=?", (habit_id, device)
        ).fetchone()
        return _row_to_habit(c, row, day) if row else None


def find_habit(title: str | None, device: str, day: date | None = None) -> dict | None:
    """Нечувствительный к регистру поиск по подстроке названия (в рамках устройства)."""
    if not title:
        return None
    day = day or date.today()
    with connection() as c:
        rows = c.execute(
            "SELECT * FROM habits WHERE device=? ORDER BY id", (device,)
        ).fetchall()
        t = title.lower().strip()
        for row in rows:  # точное совпадение приоритетнее
            if row["title"].lower() == t:
                return _row_to_habit(c, row, day)
        for row in rows:
            if t in row["title"].lower():
                return _row_to_habit(c, row, day)
    return None


def add_habit(
    title: str,
    category: str = "Другое",
    emoji: str = "",
    days: list[str] | None = None,
    target: int = 1,
    unit: str = "раз",
    step: int = 1,
    device: str = "",
) -> dict:
    """Создаёт привычку и возвращает её в формате выдачи API."""
    valid_days: list[str] = []
    for tok in days or []:
        tok = str(tok).strip()
        if tok in DAY_CODES or (tok.isdigit() and 1 <= int(tok) <= 31) or _DAYS_INTERVAL_RE.match(tok):
            if tok not in valid_days:
                valid_days.append(tok)
    valid_days = valid_days or list(DAY_CODES)
    # канонический порядок: дни недели (Пн…Вс), потом дни месяца, потом интервал
    valid_days = (
        [d for d in DAY_CODES if d in valid_days]
        + sorted((t for t in valid_days if t.isdigit()), key=int)
        + [t for t in valid_days if _DAYS_INTERVAL_RE.match(t)]
    )
    title = (title or "").strip() or "Новая привычка"
    title = title[:1].upper() + title[1:]  # «медитация» → «Медитация»
    unit = canon_unit(unit)  # «минут» → «минута», «лабу» → «лаба»
    step = max(1, min(10000, int(step or 1)))
    with connection() as c:
        cur = c.execute(
            "INSERT INTO habits (title, category, emoji, days, target, unit, step, created_at, device)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                title,
                (category or "Другое").strip() or "Другое",
                "",  # эмодзи убраны из продукта: храним всегда пусто
                json.dumps(valid_days),
                max(1, int(target or 1)),
                unit,
                step,
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


def increment(habit_id: int, device: str, step: int = 1, day: date | None = None) -> dict | None:
    """Клик «+»: увеличивает счётчик на день (по умолчанию — сегодня)."""
    day = day or date.today()
    with connection() as c:
        if _owned_id(c, habit_id, device) is None:
            return None
        c.execute(
            "INSERT INTO habit_logs (habit_id, day, count) VALUES (?, ?, ?)"
            " ON CONFLICT(habit_id, day) DO UPDATE SET count = count + excluded.count",
            (habit_id, day.isoformat(), step),
        )
    return get_habit(habit_id, device, day)


def complete_today(habit_id: int, device: str, day: date | None = None) -> dict | None:
    """Отмечает день выполненным (прогресс = план). Прогресс прошлых дней не трогает."""
    habit = get_habit(habit_id, device, day)
    if not habit:
        return None
    return set_progress(habit_id, habit["target"], device, day)


def set_progress(habit_id: int, count: int, device: str, day: date | None = None) -> dict | None:
    day = day or date.today()
    with connection() as c:
        if _owned_id(c, habit_id, device) is None:
            return None
        c.execute(
            "INSERT INTO habit_logs (habit_id, day, count) VALUES (?, ?, ?)"
            " ON CONFLICT(habit_id, day) DO UPDATE SET count = excluded.count",
            (habit_id, day.isoformat(), max(0, int(count))),
        )
    return get_habit(habit_id, device, day)


def set_freeze(habit_id: int, device: str, days: int = 7) -> dict | None:
    """Временная пауза привычки: дни в окне заморозки не план и не пропуск.

    Прогресс, серия и история остаются нетронутыми; после даты «до» привычка
    снова входит в график как раньше. Замораживать повторно — просто обновит окно
    (стартует с сегодня)."""
    days = max(1, int(days or 7))
    today = date.today()
    with connection() as c:
        if _owned_id(c, habit_id, device) is None:
            return None
        c.execute(
            "UPDATE habits SET frozen_from=?, frozen_until=? WHERE id=? AND device=?",
            (today.isoformat(), (today + timedelta(days=days - 1)).isoformat(), habit_id, device),
        )
    return get_habit(habit_id, device)


# --- Чат -----------------------------------------------------------------------

def list_categories(device: str) -> list[str]:
    """Категории устройства (порядок появления), для вопроса при создании."""
    with connection() as c:
        rows = c.execute(
            "SELECT DISTINCT category FROM habits WHERE device=? ORDER BY id",
            (device,),
        ).fetchall()
    return [r["category"] for r in rows if r["category"]]


def get_draft(device: str) -> dict | None:
    """Незавершённое интервью создания привычки (JSON-черновик)."""
    with connection() as c:
        row = c.execute(
            "SELECT data FROM chat_drafts WHERE device=?", (device,)
        ).fetchone()
    return json.loads(row["data"]) if row else None


def set_draft(device: str, data: dict):
    with connection() as c:
        c.execute(
            "INSERT INTO chat_drafts (device, kind, data, updated_at)"
            " VALUES (?, 'habit', ?, ?)"
            " ON CONFLICT(device) DO UPDATE SET data=excluded.data,"
            " updated_at=excluded.updated_at",
            (device, json.dumps(data, ensure_ascii=False), date.today().isoformat()),
        )


def clear_draft(device: str):
    with connection() as c:
        c.execute("DELETE FROM chat_drafts WHERE device=?", (device,))


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


# --- Контрольные точки (ре-анализ нагрузки) --------------------------------------

def add_checkpoint(
    device: str,
    due_at: date,
    note: str = "",
    baseline_pct: float | None = None,
    baseline_skipped: int | None = None,
) -> int:
    """Ставит контрольную точку: в due_at система сравнит статистику с baseline."""
    with connection() as c:
        cur = c.execute(
            "INSERT INTO checkpoints"
            " (device, created_at, due_at, baseline_pct, baseline_skipped, note, processed)"
            " VALUES (?, ?, ?, ?, ?, ?, 0)",
            (
                device,
                date.today().isoformat(),
                due_at.isoformat(),
                baseline_pct,
                baseline_skipped,
                (note or "")[:500],
            ),
        )
        return cur.lastrowid


def has_pending_checkpoint(device: str) -> bool:
    """Есть ли ещё необработанная контрольная точка (не нужен дубль)."""
    with connection() as c:
        row = c.execute(
            "SELECT 1 FROM checkpoints WHERE device=? AND processed=0 LIMIT 1",
            (device,),
        ).fetchone()
        return row is not None


def get_due_checkpoints(device: str) -> list[sqlite3.Row]:
    """Контрольные точки, срок которых наступил и которые ещё не отработаны."""
    with connection() as c:
        return c.execute(
            "SELECT * FROM checkpoints WHERE device=? AND processed=0 AND due_at<=?"
            " ORDER BY id",
            (device, date.today().isoformat()),
        ).fetchall()


def list_checkpoints(device: str, limit: int = 10) -> list[dict]:
    """Последние контрольные точки (для GET /api/wellbeing)."""
    with connection() as c:
        rows = c.execute(
            "SELECT id, created_at, due_at, baseline_pct, baseline_skipped, note, processed"
            " FROM checkpoints WHERE device=? ORDER BY id DESC LIMIT ?",
            (device, limit),
        ).fetchall()
    return [
        {
            "id": r["id"],
            "createdAt": r["created_at"],
            "dueAt": r["due_at"],
            "baselinePct": r["baseline_pct"],
            "baselineSkipped": r["baseline_skipped"],
            "note": r["note"],
            "processed": bool(r["processed"]),
        }
        for r in rows
    ]


def mark_checkpoint_processed(checkpoint_id: int):
    with connection() as c:
        c.execute(
            "UPDATE checkpoints SET processed=1 WHERE id=?", (checkpoint_id,)
        )


init_db()
