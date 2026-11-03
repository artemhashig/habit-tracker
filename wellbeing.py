"""Проактивная модель ментального здоровья и предотвращение выгорания.

Неделя пользователя (7 полных дней: от (сегодня-7) до вчера) разбивается
на плановые «слоты» (привычка × запланированный день) и закрывается логами.

Три зоны:
  • green  — выполнение ≥80% (или ≤1 полному пропуску дня) → минимальное
             вмешательство;
  • yellow — 2–3 полных пропуска → мягкий эмпатичный чек-ин, без токсичной
             продуктивности;
  • red    — ≥4 пропуска или прямой сигнал усталости → сценарий реабилитации.

При спаде ассистент в диалоге выявляет корень (когнитивная перегрузка
vs потеря мотивации) и через вызов функций применяет:
  • freeze_habit  — временная заморозка без потери прогресса;
  • reduce_habit  — снижение планки (прогресс сохраняется);
  • set_checkpoint — контрольная точка: через N дней ре-анализ, сравнение
    статистики «до/после» и следующая корректировка, чтобы не потерять
    пользователя.
"""
import json
from datetime import date, timedelta

import db

WINDOW_DAYS = 7

SUPPORT = {
    "yellow": (
        "Вижу, что неделя получилась труднее обычного. Это нормально — так бывает. "
        "Как ты сейчас? Мне важно понять, что за этим стоит: сил не хватает "
        "(перегруз) или желание делать ушло (мотивация)? "
        "Сделаем план бережнее: могу временно заморозить привычку или снизить "
        "планку — прогресс при этом не теряется."
    ),
    "red": (
        "Похоже, на этом темпе было тяжело держаться последние дни. "
        "Это не провал, а сигнал — и мы его вовремя поймали. "
        "Давай режим реабилитации: часть привычек можно положить на паузу, "
        "планку — снизить до комфортной. Расскажи пару слов, как ты — "
        "разберёмся вместе, без стыда и спешки."
    ),
    "green": "",
}


def _slots(
    c, device: str, today: date
) -> tuple[int, int, int, list[str], list[dict], list[dict]]:
    """(всего слотов, закрыто, число полных пропусков дня, названия привычек
    с выполнением <50%, per-habit статистика, худшие привычки)."""
    window = [today - timedelta(days=offset) for offset in range(7, 0, -1)]
    rows = c.execute(
        "SELECT * FROM habits WHERE device=? ORDER BY id", (device,)
    ).fetchall()

    total = done = 0
    day_total: dict[date, int] = {}
    day_done: dict[date, int] = {}
    habit_stats: list[dict] = []

    for row in rows:
        days = json.loads(row["days"])
        if not days:
            continue
        try:
            created = date.fromisoformat(row["created_at"])
        except (ValueError, TypeError):
            created = date.min
        window_pair = db._frozen_window(row)

        h_total = h_done = 0
        for d in window:
            if d < created:
                continue
            if db._weekday_ru(d) not in days:
                continue
            if db._on_freeze(d, window_pair):
                continue  # пауза — день не считается ни планом, ни пропуском
            log = c.execute(
                "SELECT count FROM habit_logs WHERE habit_id=? AND day=?",
                (row["id"], d.isoformat()),
            ).fetchone()
            cnt = log["count"] if log else 0
            h_total += 1
            day_total[d] = day_total.get(d, 0) + 1
            if cnt >= row["target"] > 0:
                h_done += 1
                day_done[d] = day_done.get(d, 0) + 1
        total += h_total
        done += h_done
        if h_total:
            habit_stats.append({
                "title": row["title"],
                "done": h_done,
                "total": h_total,
                "pct": round(h_done / h_total * 100),
            })

    skipped = sum(
        1 for d, t in day_total.items() if t > 0 and day_done.get(d, 0) == 0
    )
    worst = sorted(habit_stats, key=lambda h: h["pct"])[:3]
    missed_titles = [
        h["title"] for h in habit_stats if h["pct"] < 50
    ]
    return total, done, skipped, missed_titles, habit_stats, worst


def overview(device: str, fatigue: bool = False) -> dict:
    """Снимок состояния: зона, статистика недели и prompt для NLP."""
    today = date.today()
    with db.connection() as c:
        total, done, skipped, missed_titles, habit_stats, worst = _slots(c, device, today)

    pct = round(done / total * 100) if total else None
    zone = zone_of(pct, skipped, fatigue)
    return {
        "zone": zone,
        "pct": pct,
        "slotsTotal": total,
        "slotsDone": done,
        "skippedDays": skipped,
        "missedHabits": missed_titles,
        "fatigue": fatigue,
        "prompt": context_text(zone, pct, skipped, missed_titles, today),
    }


def zone_of(pct: int | None, skipped: int, fatigue: bool = False) -> str:
    """green / yellow / red по правилам продукта."""
    if fatigue or skipped >= 4:
        return "red"
    if skipped in (2, 3):
        return "yellow"
    if pct is not None and pct < 50:
        # выполняет, но совсем мало — тоже повод присмотреться
        return "yellow"
    return "green"


def context_text(
    zone: str, pct: int | None, skipped: int, missed_titles: list[str], today: date
) -> str:
    """Технический контекст для LLM: зона + что с ней делать."""
    if zone == "green":
        return (
            "Wellbeing-зона: green (выполнение "
            f"{pct if pct is not None else '—'}%, полных пропусков {skipped} за 7 дней). "
            "Прогресс стабильный: хвали по делу, минимальное вмешательство, планку "
            "не повышай без явной просьбы пользователя."
        )
    stem = (
        f"Wellbeing-зона: {'yellow' if zone == 'yellow' else 'red'} "
        f"(выполнение {pct if pct is not None else '—'}%, полных пропусков {skipped} "
        f"за 7 дней)."
    )
    diag = (
        " Сначала мягкий чек-ин и ОДИН открытый вопрос, чтобы выявить корень: "
        "когнитивная перегрузка (сил не хватает) или потеря мотивации (смысл ушёл). "
        "Не дави, не стыдь, никакого «надо просто взять себя в руки»."
        if zone == "yellow"
        else " Сценарий реабилитации: тон бережный, никакого стыда и токсичной "
        "продуктивности. Помоги разгрузить план, а не догнать график."
    )
    options = (
        " После ответа пользователя предложи КОНКРЕТНОЕ из двух:"
        " 1) freeze_habit — временная заморозка на N дней (прогресс сохраняется),"
        " 2) reduce_habit — снижение планки.Применяй действие сразу, если пользователь"
        " явно попросил, иначе сначала предложи и дождись согласия."
        " Потом поставь set_checkpoint (3–5 дней) для повторного анализа."
    )
    missed = (
        f" Хуже всего идёт: {', '.join(f'«{t}»' for t in missed_titles)}."
        if missed_titles
        else ""
    )
    return f"{stem}{diag}{options}{missed} Сегодня: {today.strftime('%d.%m.%Y')}."


def reanalysis_text(
    baseline_pct: float | None,
    baseline_skipped: int | None,
    now: dict,
) -> str:
    """Текст ре-анализа: сравнение статистики «до контрольной точки» и «сейчас»."""
    old = f"{round(baseline_pct)}%" if baseline_pct is not None else "—"
    new = f"{now['pct']}%" if now["pct"] is not None else "—"
    improved = (
        baseline_pct is not None
        and now["pct"] is not None
        and now["pct"] - baseline_pct >= 10
    ) or (
        baseline_skipped is not None and now["skippedDays"] < baseline_skipped - 1
    )
    worsened = (
        baseline_pct is not None
        and now["pct"] is not None
        and now["pct"] < baseline_pct - 5
    )
    if now["zone"] == "green":
        return f"Сравнил: {old} → {new}. Твой темп держится — класс, ничего не трогаю."
    if improved:
        return (
            f"Сравнил: было {old}, стало {new}. Полезный сдвиг — так держать, "
            "текущий план подходит."
        )
    if worsened or now["zone"] == "red":
        return (
            f"Сравнил: было {old}, стало {new}. Похоже, план всё ещё тяжёлый. "
            "Давай ещё бережнее: заморозим часть привычек или снизим планку — "
            "как ты? Прогресс сохраняется."
        )
    return (
        f"Сравнил: было {old}, стало {new}. Оставляем план как есть и продолжаю "
        "наблюдать мягко — если захочешь разгрузиться, скажи словом."
    )


def consume_pending(device: str) -> dict:
    """Обрабатывает созревшие контрольные точки.

    Сравнивает базовую и текущую статистику, формирует сообщение ассистента,
    помечает точки отработанными и ставит следующую (чтобы наблюдение
    продолжалось и отток был замечен вовремя)."""
    due = db.get_due_checkpoints(device)
    if not due:
        return {"due": False}

    now = overview(device)
    parts = [reanalysis_text(cp["baseline_pct"], cp["baseline_skipped"], now) for cp in due]
    for cp in due:
        db.mark_checkpoint_processed(cp["id"])

    next_in = 5
    created_new = False
    if not db.has_pending_checkpoint(device):
        db.add_checkpoint(
            device,
            date.today() + timedelta(days=next_in),
            note="авто-контроль после ре-анализа",
            baseline_pct=now["pct"],
            baseline_skipped=now["skippedDays"],
        )
        created_new = True

    reply = "\n\n".join(parts)
    reply += (
        f" Поставил следующую контрольную точку — вернусь через {next_in} дней."
        if created_new
        else " Наблюдение продолжаю."
    )
    return {
        "due": True,
        "reply": reply,
        "zone": now["zone"],
        "stats": {"pct": now["pct"], "skippedDays": now["skippedDays"]},
    }
