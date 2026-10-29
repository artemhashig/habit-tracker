"""NLP-модуль: превращает поток сознания из чата в действия над привычками.

Два уровня:
1. LLM (по умолчанию Amvera LLM Inference, OpenAI-совместимый API) — основной
   разбор текста: эмоциональный контекст + структурированные действия.
2. Локальный rule-based fallback — работает без API-ключа. Им пользуемся
   в автотестах и если LLM недоступна.
"""
import json
import logging
import os
import re
from datetime import date

log = logging.getLogger("llm")

# --- Конфигурация LLM (переменные окружения) ------------------------------------

LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://inference.waw0.amvera.ru/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4.1")
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "60"))

DAY_CODES = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

SYSTEM_PROMPT = """Ты — эмпатичный ассистент дневника и трекера привычек Grit.
Пользователь пишет потоком сознания: жалобы на усталость, эмоции, планы на себя.

Твоя работа:
1) Поддержать человека тёплой короткой фразой (1–3 предложения, по-русски, без markdown).
2) Извлечь из текста действия над привычками и вернуть СТРОГИЙ JSON без пояснений:

{
  "reply": "<твоя поддерживающая реплика>",
  "actions": [
    {"type": "add_habit", "title": "...", "category": "...", "emoji": "🧘",
     "days": ["Пн", "Вт"], "target": 10, "unit": "минут"},
    {"type": "reduce_habit", "habit_title": "...", "new_target": 40, "reason": "..."}
  ]
}

Правила:
- days — только из ["Пн","Вт","Ср","Чт","Пт","Сб","Вс"].
  «каждый день/ежедневно/по утрам» → все 7; «по выходным» → ["Сб","Вс"];
  «по будням» → ["Пн","Вт","Ср","Чт","Пт"]; дни из текста → перечисли их;
  если срок не ясен → все 7.
- target — сколько раз/минут/страниц в день; если не указано, поставь 1.
- unit — единица: "раз", "минут", "страниц", "стаканов", "километров", "повторений"
  или своё существительное (в родительном падеже множественного числа).
- category подбери: Спорт, Саморазвитие, Здоровье, Учеба, Работа, Дом или Другое.
- emoji — один уместный эмодзи-иконка привычки.
- reduce_habit: если человек устал, выгорел, перегружен, не успевает, болеет или явно
  просит снизить/упростить нагрузку — снизь план на день. new_target = примерно половина
  текущего плана (округли вверх) ЛИБО конкретное число из текста. habit_title бери ТОЧНО
  из списка привычек. Прогресс пользователя никогда не сбрасывается — меняется только план.
  Если усталость сильная («устал как собака», «выгорание», «болею», «нет сил») — снижение
  должно быть заметным (например 50–60% от плана).
- add_habit: добавляй только то, что пользователь хочет отслеживать. В одном ответе
  допустимы и добавление привычки, и снижение нагрузки одновременно.
- Если действий не нужно — один элемент {"type": "none"}.
- Список текущих привычек пользователя (id, название, план, единица, дни) приложен
  в конце системного контекста. Используй его для reduce/delete.
- Верни только JSON, без markdown-обёртки."""


def habits_summary(habits: list[dict]) -> str:
    """Краткая сводка привычек для промпта (что LLM может менять)."""
    if not habits:
        return "У пользователя пока нет привычек."
    lines = []
    for h in habits:
        lines.append(
            f"- id={h['id']} «{h['title']}» — план {h['target']} {h['unit']}/день, "
            f"дни: {', '.join(h['days'])}, сегодня {h['current']}/{h['target']}"
        )
    return "Текущие привычки пользователя:\n" + "\n".join(lines)


def _extract_json(text: str) -> dict | None:
    """Достаёт JSON из ответа модели (умеет ```json ...``` и мусор вокруг)."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


# --- Основной разбор через LLM ---------------------------------------------------

async def llm_parse(message: str, habits: list[dict], history: list[dict]) -> dict:
    """Спрашивает LLM о действиях. Бросает исключение при недоступности."""
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        base_url=LLM_BASE_URL,
        api_key=LLM_API_KEY,
        timeout=LLM_TIMEOUT,
        max_retries=1,
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        # короткая история диалога — чтобы ассистент помнил контекст
        *[
            {"role": m["role"], "content": m["content"]}
            for m in history[-8:]
            if m["role"] in ("user", "assistant")
        ],
        {
            "role": "system",
            "content": (
                f"Дата сегодня: {date.today().strftime('%d.%m.%Y')}. "
                + habits_summary(habits)
            ),
        },
        {"role": "user", "content": message},
    ]
    completion = await client.chat.completions.create(
        model=LLM_MODEL,
        messages=messages,  # type: ignore[arg-type]
        temperature=0.3,
    )
    raw = completion.choices[0].message.content or ""
    parsed = _extract_json(raw)
    if not parsed or not isinstance(parsed.get("reply"), str):
        raise ValueError(f"LLM вернул не JSON: {raw[:200]}")
    if not isinstance(parsed.get("actions"), list):
        parsed["actions"] = [{"type": "none"}]
    return parsed


# --- Локальный rule-based fallback (тесты / нет ключа) -----------------------------

_FATIGUE_RE = re.compile(
    r"устал\S*|выгор\S*|нет\s+сил|не\s+(?:успеваю|могу\s*больше|вывоз\w*)"
    r"|тяжело|истощ\S*|боле\w|температур\S*|мало\s+сплю|перегруж\S*|не\s+одихнул",
    re.IGNORECASE,
)
_ADD_RE = re.compile(
    r"добав\w+|завед\w+|постав\w+\s+(?:привычку|напомин\w*)|"
    r"хочу\s+(?:начать|добавить|следить)|буд\w+\s|начн\w+|надо\s+начать|"
    r"нач\w+\s+(?:с|бег|занима)|трек\w*|привычку",
    re.IGNORECASE,
)
_REDUCE_RE = re.compile(
    r"снизь\S*|уменьши\S*|сократи\S*|меньше\s+нагруз\w*|полегче|попроще"
    r"|сбав\S*|опусти\s+планку|послабл\S*",
    re.IGNORECASE,
)
_WEEKENDS_RE = re.compile(r"по\s+выходным|в\s+выходные", re.IGNORECASE)
_WEEKDAYS_RE = re.compile(r"по\s+будням|в\s+будни|рабоч\w+\s+дн\S*", re.IGNORECASE)
_EVERYDAY_RE = re.compile(
    r"кажд\w+\s*день|ежедневно|еже\w+|каждый\s+день|весь\s+день", re.IGNORECASE
)
_QUOTED_RE = re.compile("[«\"]([^«»\"]{2,60})[»\"]")
_DAY_NAME_RE = re.compile(
    r"\b(понедельник\w*|вторник\w*|сред\w*|четверг\w*|пятниц\w*|суббот\w*"
    r"|воскресенье\w*|воскрес\w*|пн|вт|ср|чт|пт|сб|вс)\b",
    re.IGNORECASE,
)
_TARGET_RE = re.compile(
    r"(\d{1,3})\s*(мин\w*|страниц\w*|раз\w*|стакан\w*|км|километр\w*|повторени\w*"
    r"|сеанс\w*|час\w*|штук\w*)?",
    re.IGNORECASE,
)
_UNIT_MAP = {
    "мин": "минута", "минут": "минута", "минуты": "минута", "минутах": "минута",
    "страниц": "страница", "страница": "страница", "страницы": "страница",
    "раз": "раз", "раза": "раз", "разов": "раз",
    "стакан": "стакан", "стакана": "стакан", "стаканов": "стакан",
    "км": "км", "километр": "километр", "километра": "километр",
    "повторение": "повторение", "повторения": "повторение", "повторений": "повторение",
    "сеанс": "сеанс", "сеанса": "сеанс", "сеансов": "сеанс",
    "штук": "раз", "час": "минута", "часа": "минута",
}

_DAY_STEMS = [
    ("понедельни", "Пн"), ("пн", "Пн"),
    ("вторник", "Вт"), ("вт", "Вт"),
    ("сред", "Ср"), ("ср", "Ср"),
    ("четверг", "Чт"), ("чт", "Чт"),
    ("пятниц", "Пт"), ("пт", "Пт"),
    ("суббот", "Сб"), ("сб", "Сб"),
    ("воскрес", "Вс"), ("вс", "Вс"),
]

_SUPPORT_REPLIES = {
    "add": "Отличная идея для себя! Забрал в трекер — теперь не потеряется.",
    "reduce": "Слышу тебя. Снизил планку на сегодня — весь твой прогресс сохранён.",
    "both": "Понимаю тебя. Добавил то, что просил, и аккуратно снизил нагрузку — прогресс сохранён.",
    "none": "Спасибо, что доверяешь. Расскажи, как ты, — я рядом и помогу подстроить план.",
    "fatigue_care": "Ты выложился на максимум — так и есть. День будет полегче: план смягчён, но ничего не сгорело.",
}


def _extract_days(text: str) -> list[str]:
    """Извлекает дни недели; по умолчанию — каждый день."""
    if _WEEKENDS_RE.search(text):
        return ["Сб", "Вс"]
    if _WEEKDAYS_RE.search(text):
        return list(DAY_CODES[:5])
    days: list[str] = []
    for m in _DAY_NAME_RE.finditer(text):
        low = m.group(1).lower()
        for stem, code in _DAY_STEMS:
            if low.startswith(stem):
                if code not in days:
                    days.append(code)
    if days:
        return days
    return list(DAY_CODES)


def _extract_title(text: str) -> str:
    """Название новой привычки: из кавычек, иначе текст после «привычку»."""
    quote = _QUOTED_RE.search(text)
    if quote:
        return quote.group(1).strip()
    m = re.search(
        r"привычку\s+(.+?)(?=$|[,.;:!?]|\s(?:по|каждый|ежедневно|еже|начин|вместо))",
        text,
        re.IGNORECASE,
    )
    if m:
        title = m.group(1).strip()
        title = re.sub(
            r"\s+(кажд\w+|ежеднев\w*|завтр\w*|сегодня|утро|вечер).*$", "", title,
            flags=re.IGNORECASE,
        )
        return title.strip(" .,")
    return ""


def _extract_target_unit(text: str) -> tuple[int, str]:
    """Число + единица: «20 минут», «3 страницы», «84 повторения»."""
    for m in _TARGET_RE.finditer(text):
        num = int(m.group(1))
        unit_raw = (m.group(2) or "").lower()
        if not unit_raw:
            continue
        stem = next(
            (s for s in _UNIT_MAP if unit_raw.startswith(s)), None
        )
        if stem is None:
            continue
        unit = _UNIT_MAP[stem]
        target = num * 60 if stem == "час" else num
        return max(1, target), unit
    # число без единицы
    m = re.search(r"\b(\d{1,3})\b", text)
    if m:
        return max(1, int(m.group(1))), "раз"
    return 1, "раз"


def fallback_parse(message: str, habits: list[dict]) -> dict:
    """Эвристики без LLM: добавление привычки и снижение нагрузки."""
    text = message.lower()
    today = date.today()
    actions: list[dict] = []

    wants_add = bool(_ADD_RE.search(text)) or "привычку" in text
    fatigue = bool(_FATIGUE_RE.search(text))
    explicit_reduce = bool(_REDUCE_RE.search(text))
    heavy = bool(re.search(r"выгор\S*|устал\s+как\s+\S+|нет\s+сил|болю", text))

    if wants_add:
        title = _extract_title(text)
        if not title:
            title = "Новая привычка"
        days = _extract_days(text)
        target, unit = _extract_target_unit(text)
        actions.append(
            {
                "type": "add_habit",
                "title": title,
                "category": "Другое",
                "emoji": "✨",
                "days": days,
                "target": target,
                "unit": unit,
            }
        )

    if fatigue or explicit_reduce:
        # снижаем всё, что ещё не закрыто на сегодня (и «до N», если указано)
        explicit_target = None
        m = re.search(r"(?:до|на)\s+(\d{1,3})\b", text)
        if explicit_reduce and m:
            explicit_target = int(m.group(1))
        for h in habits:
            done_today = h["current"] >= h["target"]
            if done_today:
                continue
            if explicit_target is not None:
                new_target = explicit_target
            else:
                new_target = max(1, round(h["target"] * (0.4 if heavy else 0.5)))
            if new_target < h["target"]:
                actions.append(
                    {
                        "type": "reduce_habit",
                        "habit_title": h["title"],
                        "new_target": new_target,
                        "reason": "усталость — оставим силы, прогресс сохранён",
                    }
                )

    if actions:
        has_add = any(a["type"] == "add_habit" for a in actions)
        has_reduce = any(a["type"] == "reduce_habit" for a in actions)
        if has_add and has_reduce:
            reply = _SUPPORT_REPLIES["both"]
        elif has_add:
            reply = _SUPPORT_REPLIES["add"]
        elif heavy:
            reply = _SUPPORT_REPLIES["fatigue_care"]
        else:
            reply = _SUPPORT_REPLIES["reduce"]
    elif fatigue:
        reply = _SUPPORT_REPLIES["fatigue_care"] if heavy else _SUPPORT_REPLIES["none"]
    else:
        reply = _SUPPORT_REPLIES["none"]

    return {"reply": reply, "actions": actions or [{"type": "none"}]}


async def parse_intent(message: str, habits: list[dict], history: list[dict]) -> dict:
    """Точка входа NLP: LLM → при ошибке/отсутствии ключа локальные правила."""
    if LLM_API_KEY:
        try:
            return await llm_parse(message, habits, history)
        except Exception as e:  # noqa: BLE001 — любой сбой уводит в fallback
            log.warning("LLM недоступна, транзакция ушла в fallback: %s", e)
    return fallback_parse(message, habits)
