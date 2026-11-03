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
LLM_MODEL = os.getenv("LLM_MODEL", "llama70b")  # llama 3.3 70B у Amvera Inference
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "60"))

DAY_CODES = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

SYSTEM_PROMPT = """Ты — эмпатичный ассистент дневника и трекера привычек Grit.
Пользователь пишет потоком сознания: жалобы на усталость, эмоции, планы на себя.

Твоя работа:
1) Поддержать человека тёплой короткой фразой (1–3 предложения, по-русски, без markdown
   и без эмодзи).
2) Извлечь из текста действия над привычками и вернуть СТРОГИЙ JSON без пояснений:

{
  "reply": "<твоя поддерживающая реплика>",
  "actions": [
    {"type": "add_habit", "title": "...", "category": "...", "emoji": "",
     "days": ["Пн", "Вт"], "target": 10, "unit": "минут"},
    {"type": "reduce_habit", "habit_title": "...", "new_target": 40, "reason": "..."}
  ]
}

Правила:
- days — только из ["Пн","Вт","Ср","Чт","Пт","Сб","Вс"].
  «каждый день/ежедневно» → все 7; «по выходным» → ["Сб","Вс"];
  «по будням» → ["Пн","Вт","Ср","Чт","Пт"]; дни из текста («по вт», «раз в пн»,
  «среда и пятница») → укажи ТОЛЬКО их, даже если это один день. Все 7 дней —
  только если в тексте нет ни одного названного дня; день назван → все 7 запрещены.
- target — количество СТРОГО из явного числа с единицей: «3/д» = 3 раза,
  «10 минут», «5 страниц», «30 повторений». Время суток — НЕ количество:
  «в 13:00 вечера», «в 8 утра», «к 21:00» — это упоминание времени; включи его
  в название привычки и никогда не подставляй его цифру в target.
- title — само занятие, без служебного: без «создай/добавь», без «раз в», «по вт»,
  без голых чисел и единиц измерения. Детали вроде времени можно оставить в
  названии красиво: «Прыгать на скакалке в 13:00», «Прыгать».
- unit — единица: "раз", "минут", "страниц", "стаканов", "километров", "повторений"
  или своё существительное (в родительном падеже множественного числа).
- category подбери: Спорт, Саморазвитие, Здоровье, Учеба, Работа, Дом или Другое.
- emoji — всегда пустая строка: эмодзи в приложении не используются.
- reduce_habit: если человек устал, выгорел, перегружен, не успевает, болеет или явно
  просит снизить/упростить нагрузку — снизь план на день. new_target = примерно половина
  текущего плана (округли вверх) ЛИБО конкретное число из текста. habit_title бери ТОЧНО
  из списка привычек. Прогресс пользователя никогда не сбрасывается — меняется только план.
  Если усталость сильная («устал как собака», «выгорание», «болею», «нет сил») — снижение
  должно быть заметным (например 50–60% от плана).
- add_habit: добавляй только то, что пользователь хочет отслеживать. В одном ответе
  допустимы и добавление привычки, и снижение нагрузки одновременно.
- freeze_habit: {"type": "freeze_habit", "habit_title": "...", "days": 7} — временная
  пауза привычки на N дней (обычно 3–14). Прогресс, серия и история сохраняются,
  дни заморозки не считаются ни планом, ни пропуском. Названия бери точно из списка.
- set_checkpoint: {"type": "set_checkpoint", "days": 3, "note": "что наблюдаем"} —
  контрольная точка ре-анализа через N дней (2–7). После корректировок плана,
  усталости или восстановления предлагаешь её, чтобы честно сравнить статистику
  «до/после» и не потерять пользователя.
- Политика заботы (без токсичной продуктивности): планку никогда не повышаешь сам;
  при усталости — согласие и бережность, никаких «просто возьми себя в руки»;
  хвалишь за реальные сдвиги, а не за количество.
- Wellbeing-зоне посвящён отдельный блок в системном контексте: green/желтая/red —
  следуй его инструкциям по строгости вмешательства.
- Если действий не нужно — один элемент {"type": "none"}.
Примеры (разбор похожих формулировок):
- «создай привычку в 13:00 вечера прыгать на скакалке по вт 3/д» →
  {"type":"add_habit","title":"Прыгать на скакалке в 13:00","category":"Спорт","days":["Вт"],"target":3,"unit":"раз"}
- «создай привычку раз в пн 3 раза прыгать» →
  {"type":"add_habit","title":"Прыгать","category":"Спорт","days":["Пн"],"target":3,"unit":"раз"}
- Список текущих привычек пользователя (id, название, план, единица, дни) приложен
  в конце системного контекста. Используй его для reduce/delete/freeze.
- Верни только JSON, без markdown-обёртки."""


def habits_summary(habits: list[dict]) -> str:
    """Краткая сводка привычек для промпта (что LLM может менять)."""
    if not habits:
        return "У пользователя пока нет привычек."
    lines = []
    for h in habits:
        frozen = " — НА ПАУЗЕ (не планируй на неё reduce/delete)" if h.get("frozen") else ""
        lines.append(
            f"- id={h['id']} «{h['title']}» — план {h['target']} {h['unit']}/день, "
            f"дни: {', '.join(h['days'])}, сегодня {h['current']}/{h['target']}"
            f"{frozen}"
        )
    return "Текущие привычки пользователя:\n" + "\n".join(lines)


def detect_fatigue(message: str) -> bool:
    """Прямой сигнал усталости/выгорания в тексте пользователя."""
    return bool(_FATIGUE_RE.search(message.lower()))


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

async def llm_parse(
    message: str, habits: list[dict], history: list[dict], wellbeing_prompt: str = ""
) -> dict:
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
                + (("\n\n" + wellbeing_prompt) if wellbeing_prompt else "")
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

# --- Помощники разбора: время суток, «N/д», дни в фразах, количество ---------------

# время суток: «в 13:00», «в 13 часов вечера», «к 21:00», «в 8 утра» —
# никогда не количество (частая ошибка LLM: target = час_time)
_TW_RE = re.compile(
    r"\b(?:в|к|около|примерно)\s*"
    r"(?:(\d{1,2})\s*:\s*(\d{2})|(\d{1,2})\s*час\w*)"
    r"(?:\s+(утр\w*|вечер\w*|ноч\w*|попол\w*|днём?|дн\w*))?",
    re.IGNORECASE,
)

# «3/д» → «3 раза в день» (короткая запись цели)
_SHORTHAND_TARGET_RE = re.compile(r"(\d{1,3})\s*/\s*(?:д|дн|день)\b", re.IGNORECASE)

# «раз в пн», «по вт», «в среду», «каждую пятницу» — фразы с днём недели
_DAYS_PHRASE_RE = re.compile(
    r"(?:\bраз\b\s*)?(?:\bв\b|\bво\b|\bпо\b|\bкажд[аоую]\w*)\s*"
    r"(?:понедельник\w*|вторник\w*|среду?|сред\w*|четверг\w*|пятниц\w*|суббот\w*"
    r"|воскресень\w*|пн|вт|ср|чт|пт|сб|вс)\b",
    re.IGNORECASE,
)

# «3 раза», «10 минут», «5 страниц» — числовая цель (после очистки времени)
_QUANTITY_RE = re.compile(
    r"\b\d{1,3}\s*(?:/\s*(?:д|дн|день)\b"
    r"|\s*(?:раз\w*|мин\w*|страниц\w*|стакан\w*|километр\w*|км\b|повторени\w*"
    r"|сеанс\w*|штук\w*|час\w*))"
    r"(?:\s*(?:в|на)?\s*(?:день|недел\w*))?",
    re.IGNORECASE,
)

# явная числовая цель НЕ из времени — «3/д», «10 минут», «5 страниц»…
_QUANTITY_HINT_RE = re.compile(
    r"\b\d{1,3}\s*(?:/\s*(?:д|дн|день)\b"
    r"|\s*(?:раз\w*|мин\w*|страниц\w*|стакан\w*|километр\w*|км\b|повторени\w*"
    r"|сеанс\w*|штук\w*|час\w*))",
    re.IGNORECASE,
)

# служебные слова: глаголы-команды, «раз», предлоги, дни, повседневность
_SERVICE_TOKENS = set(
    """создай создать добавь добавить добавлю заведу завед поставь поставить
    привычку привычка привычки привычек новая новый новые
    хочу буду надо нужно начну начать давай пора
    раз раза разов в во к по на за из с со о об и или а но
    каждый каждое каждую каждые ежедневно ежедневн
    день дни дня дне
    утро утра утром утрам вечер вечера вечером днём ночью ночи
    пн вт ср чт пт сб вс
    сегодня вчера завтра потом также снова еще ещё
    """.split()
)

# повелительные/вводные слова в начале кандидата-названия
_LEAD_CLEAN_RES = [
    re.compile(r"^(?:созда\w*|добав\w*|завед\w*|постав\w*|запис\w*)\b\s*", re.I),
    re.compile(r"^(?:привычку|привычка|привычки)\b\s*", re.I),
    re.compile(r"^(?:хочу|буд\S*|надо|нужно|давай|пора|начн\w*)\b\s*", re.I),
    re.compile(r"^(?:(?:чтобы|что\s+бы)\b\s*)+", re.I),
]


def _title_is_service(title: str) -> bool:
    """Название-мусор? («В 13», «Раз в пн 3 раза прыгнуть») — метрика служебных
    токенов: если плохих токенов больше половины, название бесполезно."""
    toks = re.findall(r"[0-9а-яё]+", (title or "").lower())
    if not toks:
        return True
    bad = sum(
        1 for t in toks
        if t in _SERVICE_TOKENS or any(ch.isdigit() for ch in t) or len(t) < 2
    )
    return bad * 2 > len(toks)


def _normalize_shorthand(text: str) -> str:
    """«3/д» → «3 раза в день», чтобы quantity-паттерны видели цель."""
    text = _SHORTHAND_TARGET_RE.sub(r"\g<1> раза в день", text)
    return text


def _split_time(text: str) -> tuple[str, str]:
    """Отрезает упоминания времени суток («в 13:00 вечера») от текста.
    Возвращает (текст без времени, хвост вида « в 13:00»)."""
    tail = ""

    def repl(m: re.Match) -> str:
        nonlocal tail
        if m.group(1) is not None:
            hour, minute = int(m.group(1)), int(m.group(2))
            tod = m.group(4) or ""
        else:
            hour, minute = int(m.group(3) or 12), 0
            tod = m.group(4) or ""
        hour = min(23, max(0, hour))
        # днём/вечером час до 12 надо перевести в 24-часовой формат
        low = tod.lower()
        if low.startswith(("дн", "попо", "веч")) and hour < 12:
            hour += 12
        tail = f" в {hour}:{minute:02d}"
        return " "

    cleaned = _TW_RE.sub(repl, text)
    return cleaned.strip(), tail


def _has_explicit_quantity(text: str) -> bool:
    """В тексте есть числовая цель, не похожая на время («3/д», «10 минут»)."""
    cleaned, _ = _split_time(text)
    return bool(_QUANTITY_HINT_RE.search(_normalize_shorthand(cleaned)))


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


def _clean_title_candidate(candidate: str) -> str:
    """Чистит кандидат-название от времени, дней, количества, ежедневности
    и вводных слов. Возвращает пустую строку, если после чистки ничего нет."""
    tail = ""
    text, tail = _split_time(candidate)
    text = _normalize_shorthand(text)

    # дни недели в любом падеже и конструкции «раз в пн»
    text = _DAYS_PHRASE_RE.sub(" ", text)
    # числовая цель: «3 раза в день», «10 минут»
    text = _QUANTITY_RE.sub(" ", text)
    # хвостовое «...в день» без числа после снятия количества
    text = re.sub(r"\b(?:раз\w*\s+)?(?:в|на)\s+день\b", " ", text, flags=re.I)
    # повседневная частота до конца строки: «каждый день», «по утрам»…
    text = re.sub(
        r"\s+(?:кажд\w*|ежедневн\w*|еже\w*|завтр\w*|сегодня|утр\w*|вечер\w*).*$",
        " ", text, flags=re.IGNORECASE,
    )
    # вводные/повелительные слова в начале
    for _ in range(4):
        for lead in _LEAD_CLEAN_RES:
            text = lead.sub("", text).lstrip()
    text = text.strip(" \t.,;:!?«»\"'-—")
    if not text:
        return ""
    # висячий предлог в конце убираем («...скакалке на» — не бывает нормально)
    words = text.split()
    while words and words[-1].lower() in {"в", "во", "на", "по", "к", "за", "и"}:
        words.pop()
    text = " ".join(words).strip(" \t.,;:!?«»\"'-—")
    if not text:
        return ""
    out = (text + tail).strip()
    return out[:1].upper() + out[1:]


def _extract_title(text: str) -> str:
    """Название новой привычки: последовательность стратегий —
    1) кавычки («Медитация»);
    2) текст после «привычку», почищенный от служебного + хвост времени;
    3) весь текст после глагола добавления, почищенный так же."""
    quote = _QUOTED_RE.search(text)
    if quote:
        return quote.group(1).strip()

    m = re.search(r"привычк\w*\s+(.+)$", text, re.IGNORECASE)
    if m:
        title = _clean_title_candidate(m.group(1))
        if title:
            return title
    # иначе — всё, что после глагола добавления, той же чисткой
    m = re.search(
        r"^(?:.*?\b(?:добав\w*|завед\w*|постав\w*|созда\w*|нача\w*|начн\w*)\b)(.+)$",
        text, re.IGNORECASE,
    )
    if m:
        title = _clean_title_candidate(m.group(1))
        if title:
            return title
    return _clean_title_candidate(text)


def _extract_target_unit(text: str) -> tuple[int, str]:
    """Число + единица: «20 минут», «3 страницы», «3/д» → 3 раза в день.
    Время суток игнорируется: сначала отрезаем его, потом ищем цель."""
    cleaned, _ = _split_time(text)
    cleaned = _normalize_shorthand(cleaned)
    for m in _TARGET_RE.finditer(cleaned):
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
    # число без единицы (после удаления времени и «/д» — это уже не часы)
    m = re.search(r"\b(\d{1,3})\b", _QUANTITY_RE.sub(" ", cleaned))
    if m:
        return max(1, int(m.group(1))), "раз"
    return 1, "раз"


def fallback_parse(
    message: str, habits: list[dict], wellbeing: dict | None = None
) -> dict:
    """Эвристики без LLM: добавление привычки, снижение нагрузки,
    заморозка привычки и контрольные точки. Зона wellbeing задаёт тон ответа
    при отсутствии явных действий (чек-ин / реабилитация)."""
    text = message.lower()
    today = date.today()
    actions: list[dict] = []
    zone = (wellbeing or {}).get("zone", "green")

    wants_add = bool(_ADD_RE.search(text)) or "привычку" in text
    fatigue = bool(_FATIGUE_RE.search(text))
    explicit_reduce = bool(_REDUCE_RE.search(text))
    heavy = bool(re.search(r"выгор\S*|устал\s+как\s+\S+|нет\s+сил|болю", text))

    # --- заморозка: «заморозь английский на неделю/3 дня», «поставь на паузу» ---
    if re.search(r"замор\S*|на\s+пау[зкс]\S*|передышк\w+", text):
        frozen = None
        if habits:
            q = _QUOTED_RE.search(message)
            if q:
                needle = q.group(1).lower()
                frozen = next(
                    (h for h in habits if h["title"].lower() == needle), None
                ) or next(
                    (h for h in habits if needle in h["title"].lower()), None
                )
            else:
                frozen = habits[0] if len(habits) == 1 else None
        if frozen:
            m = re.search(r"(\d{1,2})\s*(дн\w*|недел\w*)", text)
            days = 7
            if m:
                days = int(m.group(1)) * (7 if m.group(2).startswith("нед") else 1)
            actions.append(
                {
                    "type": "freeze_habit",
                    "habit_title": frozen["title"],
                    "days": max(1, min(30, days)),
                }
            )
            wants_add = False  # «заморозь привычку X» — не про создание новой

    # --- контрольная точка: «через 4 дня вернись», «контрольная точка» ----------
    m_point = re.search(r"(\d{1,2})\s*дн\S*", text)
    asked_checkpoint = bool(
        re.search(r"контрольн\w*\s*точк\S*|верн\w+\s*(?:к|через)|напомн\S*\s*через|провер\S*\s*(?:меня|статистику)", text)
    )
    if asked_checkpoint and m_point:
        actions.append(
            {"type": "set_checkpoint", "days": max(1, int(m_point.group(1)))}
        )

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
                "emoji": "",
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
            if h.get("frozen"):
                continue
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
        # сильная усталость без явного запроса → помним о ней и следим:
        # в системе самим приложением ставится контрольная точка ре-анализа
        if heavy and not explicit_reduce:
            actions.append(
                {"type": "set_checkpoint", "days": 3, "reason": "усталость — проследим"}
            )

    # --- реплики ---
    has_checkpoint = any(a["type"] == "set_checkpoint" for a in actions)
    has_freeze = any(a["type"] == "freeze_habit" for a in actions)
    if has_freeze:
        reply = (
            "Слышу тебя. Привычка на паузе — прогресс, серия и история сохранены, "
            "дни заморозки не считаются пропущенными. Вернёшься, когда будешь готов(а)."
        )
    elif has_checkpoint and not any(
        a["type"] in ("add_habit", "reduce_habit") for a in actions
    ):
        days = next(a["days"] for a in actions if a["type"] == "set_checkpoint")
        reply = (
            f"Договорились: контрольная точка через {days} дн. — вернусь "
            "с честным сравнением статистики и мягким решением."
        )
    elif actions:
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
    elif zone in ("yellow", "red"):
        from wellbeing import SUPPORT  # локальный импорт — без циклов
        reply = SUPPORT.get(zone) or _SUPPORT_REPLIES["none"]
    elif fatigue:
        reply = _SUPPORT_REPLIES["fatigue_care"] if heavy else _SUPPORT_REPLIES["none"]
    else:
        reply = _SUPPORT_REPLIES["none"]

    return {"reply": reply, "actions": actions or [{"type": "none"}]}


def reconcile_add_actions(plan: dict, message: str) -> dict:
    """Детерминированный перекрёстный контроль add_habit после разбора (LLM или
    fallback): дни, название и цель перепроверяются по исходному тексту
    пользователя. LLM часто путает время суток с количеством и «размазывает»
    дни на всю неделю — здесь ОДИН раз это чиним по правилам, а не по просьбам."""
    actions = plan.get("actions") or []
    if not any(isinstance(a, dict) and a.get("type") == "add_habit" for a in actions):
        return plan

    fb_days = _extract_days(message)
    fb_title = _extract_title(message)
    fb_qty = _extract_target_unit(message) if _has_explicit_quantity(message) else None

    for act in actions:
        if not (isinstance(act, dict) and act.get("type") == "add_habit"):
            continue
        if fb_days != list(DAY_CODES) and act.get("days") != fb_days:
            # в тексте названы конкретные дни — только они, никакого «все 7»
            act["days"] = fb_days
        cur_title = (act.get("title") or "").strip()
        if fb_title and _title_is_service(cur_title):
            act["title"] = fb_title
        if fb_qty is not None:
            act["target"], act["unit"] = fb_qty
    return plan


async def parse_intent(
    message: str, habits: list[dict], history: list[dict], wellbeing: dict | None = None
) -> dict:
    """Точка входа NLP: LLM → при ошибке/отсутствии ключа локальные правила.
    Оба пути проходят через reconcile_add_actions — перекрёстную проверку
    add_habit по исходному тексту."""
    wellbeing = wellbeing or {}
    if LLM_API_KEY:
        try:
            plan = await llm_parse(message, habits, history, wellbeing.get("prompt", ""))
        except Exception as e:  # noqa: BLE001 — любой сбой уводит в fallback
            log.warning("LLM недоступна, транзакция ушла в fallback: %s", e)
            plan = fallback_parse(message, habits, wellbeing)
    else:
        plan = fallback_parse(message, habits, wellbeing)
    return reconcile_add_actions(plan, message)
