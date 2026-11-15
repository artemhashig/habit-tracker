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
from datetime import date, timedelta

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
- ТОЛЬКО ФАКТЫ, никаких галлюцинаций: тебе даны сводка привычек, wellbeing-статистика
  и история диалога — ВСЁ. Запрещено утверждать что-либо о неделе, прогрессе,
  усталости или настроении пользователя, чего нет в этих данных. Если зона green
  или статистики нет — НЕ говори «неделя была трудной», «вижу спад», «ты выгорел».
  Не хватает данных — честно скажи об этом одним словом и задай вопрос.
- reply — ТОЛЬКО финальный текст пользователю (1–3 предложения), без внутренних
  рассуждений, без упоминаний JSON/действий/системных правил, без markdown и эмодзи.
- Создание привычки идёт пошаговым интервью: система сама по очереди спрашивает
  категорию, график, цель и шаг. Тебе НЕ нужно возвращать add_habit — если
  пользователь просит создать привычку или отвечает на вопросы интервью,
  верни {"type": "none"} и короткую фактическую реплику. Заглушки
  («Новая привычка») и дефолтные план/дни за пользователя запрещены.
- delete_habit: {"type": "delete_habit", "habit_title": "..."} — удалить привычку;
  название ТОЧНО из списка привычек. «удали все привычки» → по ОДНОМУ delete_habit
  на каждую привычку из списка (без пропусков). Удалять то, чего нет в списке,
  запрещено.
- Если действий не нужно — один элемент {"type": "none"}.
Примеры (разбор похожих формулировок):
- «создай привычку в 13:00 вечера прыгать на скакалке по вт 3/д» →
  {"type":"add_habit","title":"Прыгать на скакалке в 13:00","category":"Спорт","days":["Вт"],"target":3,"unit":"раз"}
- «создай привычку раз в пн 3 раза прыгать» →
  {"type":"add_habit","title":"Прыгать","category":"Спорт","days":["Пн"],"target":3,"unit":"раз"}
- «каждый пн хочу прыгать 1 раз в день» →
  {"type":"add_habit","title":"Прыгать","category":"Спорт","days":["Пн"],"target":1,"unit":"раз"}
- «создай привычку» / «создай» / «привычка» (команда без деталей) →
  {"type":"none"}, в reply уточняющий вопрос: «Какую привычку добавить и как часто?
  Например: медитация 10 минут каждый день или бег по вт 3 раза.»
- «добавь привычку смотреть» (нет графика и количества) →
  {"type":"none"}, в reply уточни: «Смотреть что и по каким дням? Сколько раз в день?»
- «удали все привычки» (в списке «Бег» и «Вода») →
  {"type":"delete_habit","habit_title":"Бег"}, {"type":"delete_habit","habit_title":"Вода"}
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


# --- LLM-консультант внутри интервью (ключ есть) -----------------------------------
# Стратегия: не словарь, а понимание свободного языка + предложение значений
# по умолчанию с просьбой подтвердить. Детерминированный разбор — страховка.

_STAGE_RU = {
    "category": "какая категория",
    "schedule": "по каким дням выполнять",
    "quantity": "сколько в день и в чём мерить",
    "step": "шаг одного нажатия «+»",
}


def _interview_prompt(
    title: str, stage: str, collected: dict, suggest: dict | None,
    categories: list[str], missing: list[str],
) -> str:
    cat_list = ", ".join(categories) if categories else "пока нет"
    miss = ", ".join(_STAGE_RU.get(s, s) for s in missing) or "ничего"
    return (
        "Ты — дружелюбный ассистент трекера привычек Grit. Ты в диалоге собираешь "
        "параметры новой привычки. Человек пишет свободно — понимай смысл слов, "
        "а не шаблоны: «1 лабу в день», «пару кружек», «по выходным», «давай по 2» — "
        "это ответы.\n"
        f"Привычка: «{title}».\n"
        f"Сейчас выясняется: {_STAGE_RU.get(stage, stage)}.\n"
        f"Уже собрано: {json.dumps(collected, ensure_ascii=False)}.\n"
        f"Твоё прошлое предложение: {json.dumps(suggest or {}, ensure_ascii=False)} — "
        "если человек его подтвердил («да»), верни его в understood.\n"
        f"Категории пользователя: {cat_list}.\n"
        f"Осталось выяснить: {miss}.\n\n"
        "Ответь строго JSON без markdown, поля:\n"
        '{"understood": {}, "proposal": {}, "reply": ""}\n'
        "- understood — что ты понял ИЗ ЭТОГО СООБЩЕНИЯ; ничего не выдумывай, пустой "
        "объект, если понять нечего. Поля: category (строка), days (массив токенов: "
        "«Пн»…«Вс»; интервал «каждыеN», N≥2: «через день», «каждый второй день», "
        "«каждые чётные дни» → «каждые2», «каждые 3 дня» → «каждые3»; дни месяца "
        "«1»…«31» — ТОЛЬКО когда человек назвал конкретные числа («1-го и 15-го»). "
        "НЕ разворачивай интервал в список дат: «каждые два дня» → «каждые2», "
        "а не «2, 4, 6, 8»; «каждый день» → все семь), target (число), unit "
        "(строка, именительный падеж ед. числа: «лаба», «стакан», «минута»), "
        "step (число — сколько счётчик прибавляет за одно нажатие «+»).\n"
        "- proposal — твоё разумное значение по умолчанию для первого недостающего "
        "пункта из «осталось выяснить», подобранное по смыслу привычки "
        "(«медитировать» → 10 минут; «звонить бабушке» → 1 звонок). График "
        "предлагай токеном: все семь дней или «каждыеN» — не списком дат. "
        "Пустой объект, если всё собрано.\n"
        "- reply — 1–2 живых предложения по-русски: коротко подтверди, что понял, и "
        "задай следующий вопрос как консультация — предложи значение из proposal и "
        "попроси подтвердить («в день по одной лабе — верно?»). Если ответ понять "
        "не удалось — мягко переспроси первый пункт из «осталось выяснить». "
        "Не анкета, а разговор. Не пиши, что привычка создана — это не так."
    )


async def llm_interview_step(
    message: str, title: str, stage: str, collected: dict, suggest: dict | None,
    categories: list[str], missing: list[str], history: list[dict] | None = None,
) -> dict | None:
    """Шаг интервью через LLM: понимание свободного ответа + реплика.
    None при любой неудаче — тогда работает детерминированный разбор."""
    if not LLM_API_KEY:
        return None
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        base_url=LLM_BASE_URL,
        api_key=LLM_API_KEY,
        timeout=LLM_TIMEOUT,
        max_retries=1,
    )
    messages = [
        {"role": "system", "content": _interview_prompt(
            title, stage, collected, suggest, categories, missing)},
        *[
            {"role": m["role"], "content": m["content"]}
            for m in (history or [])[-6:]
            if isinstance(m, dict) and m.get("role") in ("user", "assistant")
        ],
        {"role": "user", "content": message},
    ]
    try:
        completion = await client.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,  # type: ignore[arg-type]
            temperature=0.4,
        )
    except Exception as e:  # noqa: BLE001 — любая неудача → детерминированный путь
        log.warning("LLM-консультант интервью недоступен: %s", e)
        return None
    raw = completion.choices[0].message.content or ""
    data = _extract_json(raw)
    if not isinstance(data, dict) or not isinstance(data.get("reply"), str):
        log.warning("LLM-консультант вернул не JSON: %s", raw[:160])
        return None
    return data


# --- Локальный rule-based fallback (тесты / нет ключа) -----------------------------

_FATIGUE_RE = re.compile(
    r"устал\S*|выгор\S*|нет\s+сил|не\s+(?:успеваю|могу\s*больше|вывоз\w*)"
    r"|тяжело|истощ\S*|боле\w|температур\S*|мало\s+сплю|перегруж\S*|не\s+одихнул",
    re.IGNORECASE,
)
_ADD_RE = re.compile(
    r"добав\w+|завед\w+|созда\w+|постав\w+\s+(?:привычку|напомин\w*)|"
    r"хочу\s+(?:начать|добавить|следить)|"
    # «каждый пн хочу прыгать» — намерение сразу за «хочу» (кроме жалоб-желаний)
    r"хочу\s+(?!отдохн|отдых|спать|выспать|бросить|забить|умерет?|плакать|рыдать|забы)\S+|"
    r"буд\w+\s|начн\w+|надо\s+начать|"
    r"нач\w+\s+(?:с|бег|занима)|трек\w*|привычк\w+",
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
    r"|воскресенье\w*|воскрес\w*"
    r"|пнд|пн|вт|срд|ср|чтв|чт|птн|пт|сб|вск|вс)\b",
    re.IGNORECASE,
)
_TARGET_RE = re.compile(
    r"(\d{1,3})\s*(мин\w*|страниц\w*|раз\w*|стакан\w*|км|километр\w*|повторени\w*"
    r"|сеанс\w*|час\w*|штук\w*|подход\w*|отжимани\w*|упражнени\w*|звон\w*)?",
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
    "подход": "подход", "подхода": "подход", "подходов": "подход",
    "отжимание": "отжимание", "отжимания": "отжимание", "отжиманий": "отжимание",
    "упражнение": "упражнение", "упражнения": "упражнение", "упражнений": "упражнение",
    "звонк": "звонок",  # звонок/звонка/звонков/звонки
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

# «раз в пн», «по вт», «в среду», «каждую пятницу», «каждый пн» — фразы с днём
_DAYS_PHRASE_RE = re.compile(
    r"(?:\bраз\b\s*)?(?:\bв\b|\bво\b|\bпо\b|\bкажду?\w*)\s*"
    r"(?:понедельник\w*|вторник\w*|среду?|сред\w*|четверг\w*|пятниц\w*|суббот\w*"
    r"|воскресень\w*|пнд|пн|вт|срд|ср|чтв|чт|птн|пт|сб|вск|вс)\b",
    re.IGNORECASE,
)

# «3 раза», «10 минут», «5 страниц» — числовая цель (после очистки времени)
_QUANTITY_RE = re.compile(
    r"\b\d{1,3}\s*(?:/\s*(?:д|дн|день)\b"
    r"|\s*(?:раз\w*|мин\w*|страниц\w*|стакан\w*|километр\w*|км\b|повторени\w*"
    r"|сеанс\w*|штук\w*|час\w*|подход\w*|отжимани\w*|упражнени\w*|звон\w*))"
    r"(?:\s*(?:в|на)?\s*(?:день|недел\w*))?",
    re.IGNORECASE,
)

# явная числовая цель НЕ из времени — «3/д», «10 минут», «5 страниц»…
_QUANTITY_HINT_RE = re.compile(
    r"\b\d{1,3}\s*(?:/\s*(?:д|дн|день)\b"
    r"|\s*(?:раз\w*|мин\w*|страниц\w*|стакан\w*|километр\w*|км\b|повторени\w*"
    r"|сеанс\w*|штук\w*|час\w*|подход\w*|отжимани\w*|упражнени\w*|звон\w*))",
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
    токенов: если плохих токенов больше половины, название бесполезно.
    Время вида «13:00» в названии легально и мусором не считается."""
    toks = re.findall(r"[0-9а-яё:]+", (title or "").lower())
    if not toks:
        return True
    bad = sum(
        1 for t in toks
        if t in _SERVICE_TOKENS
        or (any(ch.isdigit() for ch in t) and ":" not in t)
        or len(t) < 2
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
    """В тексте есть числовая цель, не похожая на время/график
    («3/д», «10 минут», «1 лабу», «2 бутылки»)."""
    cleaned, _ = _split_time(text)
    cleaned = _normalize_shorthand(cleaned)
    if _QUANTITY_HINT_RE.search(cleaned):
        return True
    # число + незнакомое слово — тоже цель, если это не график и не время
    return any(
        not _NOT_UNIT_RE.match(w)
        for _, w in re.findall(r"\b(\d{1,3})\s+([а-яё]{2,24})\b", cleaned, re.IGNORECASE)
    )


# «по вт», «каждый день», «1 раз в день», «3/д» — явный график (не дефолт)
_SCHEDULE_HINT_RE = re.compile(
    r"кажд\w*|ежедн\w*|еже\w+|по\s+выходн\w*|по\s+будням|в\s+будни|"
    r"\b(?:пнд|пн|вт|срд|ср|чтв|чт|птн|пт|сб|вск|вс|понедельник\w*|вторник\w*|"
    r"среду?|сред\w*|четверг\w*|пятниц\w*|суббот\w*|воскресень\w*)\b|"
    r"(?:раз\w*\s+)?(?:в|на)\s+день\b|(?:в|на)\s+недел\w*|\d\s*/\s*(?:д|дн|день)\b",
    re.IGNORECASE,
)

# названия-заглушки, которые нельзя создавать
_PLACEHOLDER_TITLES = {
    "новая привычка", "привычка", "привычку", "название", "занятие", "add_habit",
}

# удаление: «удали привычку», «удали все», «избавь меня от…»
_DELETE_RE = re.compile(r"удал\w*|снес\w*|убер\w*|стёр|стере\w*|избав\w*", re.IGNORECASE)
_DELETE_ALL_RE = re.compile(r"\bвс[её]\b", re.IGNORECASE)


def _norm_days(raw) -> list[str]:
    """Дни от LLM/fallback → канонические коды недели (без мусора и дублей)."""
    if not isinstance(raw, list):
        return []
    canon = {d.lower(): d for d in DAY_CODES}
    out: list[str] = []
    for d in raw:
        code = canon.get(str(d).strip().lower()) if isinstance(d, str) else None
        if code and code not in out:
            out.append(code)
    return out


def _habit_exists(title_lower: str, habits: list[dict]) -> bool:
    """Есть ли такая привычка у пользователя (точное или частичное совпадение)."""
    return any(
        title_lower == h["title"].lower() or title_lower in h["title"].lower()
        for h in habits
    )


def _days_label(days: list[str]) -> str:
    if len(days) == 7:
        return "каждый день"
    if days == ["Сб", "Вс"]:
        return "по выходным"
    if days == list(DAY_CODES[:5]):
        return "по будням"
    return "по " + ", ".join(days).lower()


def _clarify_add(title: str, need_days: bool, need_qty: bool) -> str:
    """Один конкретный уточняющий вопрос вместо создания привычки-заглушки."""
    if not title:
        return (
            "Готов создать привычку. Что за занятие, по каким дням и сколько "
            "раз (или минут) в день? Например: «медитация 10 минут каждый день» "
            "или «бег по вт и пт 3 раза»."
        )
    missing = " и ".join(
        part for part, need in (
            ("по каким дням", need_days),
            ("сколько раз (или минут) в день", need_qty),
        ) if need
    )
    if not missing:
        return (
            f"«{title}» — готов добавить. Напиши, по каким дням и сколько "
            "раз (или минут) в день."
        )
    return f"«{title}» — уточни: {missing}? Например: «каждый день, 10 минут»."


def _not_found_reply(habits: list[dict]) -> str:
    """Честный ответ, когда привычка для действия не найдена (без выдумок)."""
    if not habits:
        return (
            "Не нашёл такой привычки — у тебя пока их нет. Могу помочь создать первую: "
            "напиши, что отслеживать, по каким дням и сколько раз в день."
        )
    names = ", ".join(f"«{h['title']}»" for h in habits[:8])
    return f"Не нашёл привычку с таким названием. Вот что у тебя есть: {names}."


_SUPPORT_REPLIES = {
    "none": (
        "Я на связи. Напиши, что сделать: создать привычку, снизить план, "
        "поставить на паузу или удалить — сделаю и подтвержу."
    ),
    "reduce": "Планка снижена, прогресс сохранён.",
    "both": "Привычку добавил и нагрузку снизил — прогресс сохранён.",
    "fatigue_care": (
        "Понял: сил мало. Скажи, что сделать — снизить план или поставить "
        "привычку на паузу, и я применю; прогресс при этом сохраняется."
    ),
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
    # (утро/вечер — только не в начале: «Вечерний созвон» — валидное название)
    text = re.sub(
        r"(?:^|\s+)(?:кажд\w*|ежедневн\w*|еже\w*|завтра\b|сегодня).*$"
        r"|\s+(?:утр\w*|вечер\w*).*$",
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


# слова, которые не единицы измерения: графики и время суток
# («2 в день» — это не «2 дня»; «1 вск» — не единица)
_NOT_UNIT_RE = re.compile(
    r"^(?:дн|день|дня|дни|недел|месяц|числ|час|год|утр|вечер|ноч|попол|"
    r"понедельни|вторник|сред|четверг|пятниц|суббот|воскрес|"
    r"пнд|пн|вт|срд|ср|чтв|чт|птн|пт|сб|вск|вс)",
    re.IGNORECASE,
)


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
    # число + незнакомое слово («1 звонок», «1 лабу», «2 бутылки») — берём,
    # если это точно не график/время; единицу приводим к именительному
    for m in re.finditer(r"\b(\d{1,3})\s+([а-яё]{2,24})\b", cleaned, re.IGNORECASE):
        word = m.group(2).lower()
        if _NOT_UNIT_RE.match(word):
            continue
        from db import canon_unit

        return max(1, int(m.group(1))), canon_unit(word)
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
    add_clarify = ""      # текст уточняющего вопроса для неполного add
    delete_clarify = ""   # текст уточняющего вопроса для неполного delete

    # --- удаление: «удали привычку X», «удали все привычки» --------------------
    # (проверяем ПЕРЕД добавлением: «удали привычку» не про создание)
    delete_intent = bool(_DELETE_RE.search(text))
    if delete_intent:
        wants_add = False
        if _DELETE_ALL_RE.search(text):
            if habits:
                for h in habits:
                    actions.append(
                        {"type": "delete_habit", "habit_title": h["title"]}
                    )
            # привычек нет → останется честная реплика «удалять нечего»
        else:
            q = _QUOTED_RE.search(message)
            needle = ""
            target_habit = None
            if q:
                needle = q.group(1).lower()
                target_habit = next(
                    (h for h in habits if h["title"].lower() == needle), None
                ) or next(
                    (h for h in habits if needle in h["title"].lower()), None
                )
            if not needle:
                m = re.search(
                    r"привычк\w*\s+(.+?)(?=$|[,.;:!?]|\s+(?:на|из|с)\b)",
                    text, re.IGNORECASE,
                )
                if m:
                    needle = m.group(1).strip().lower()
                    target_habit = next(
                        (h for h in habits
                         if needle in h["title"].lower()
                         or h["title"].lower() in needle),
                        None,
                    )
            if target_habit is None and not needle and len(habits) == 1:
                target_habit = habits[0]  # «удали привычку» с единственной — очевидно
            if target_habit:
                actions.append(
                    {"type": "delete_habit", "habit_title": target_habit["title"]}
                )
            elif needle:
                # названо то, чего нет — честный отказ, ничего не трогаем
                delete_clarify = _not_found_reply(habits)
            elif habits:
                names = ", ".join(f"«{h['title']}»" for h in habits[:8])
                delete_clarify = f"Какую привычку удалить? Вот что у тебя есть: {names}."

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
        else:
            # просили паузу, но привычку не нашли — без заглушек и без выдумок
            wants_add = False
            delete_clarify = _not_found_reply(habits)

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
        # Строгий поток: без заглушек. Создаём ТОЛЬКО если в сообщении есть
        # и название, и явный график, и количество; иначе — уточняющий вопрос.
        title = _extract_title(message)
        sched = bool(_SCHEDULE_HINT_RE.search(message))
        qty = _has_explicit_quantity(message)
        if not title:
            add_clarify = _clarify_add("", False, False)
            wants_add = False
        elif not (sched and qty):
            add_clarify = _clarify_add(title, not sched, not qty)
            wants_add = False
        else:
            days = _extract_days(message)
            target, unit = _extract_target_unit(message)
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

    # --- реплики: только факты о том, что сделали, без шаблонных фраз ---
    if add_clarify or delete_clarify:
        reply = delete_clarify or add_clarify
    elif not habits and delete_intent:
        reply = (
            "Удалять нечего — привычек пока нет. Могу помочь создать первую: "
            "напиши, что отслеживать, по каким дням и сколько раз в день."
        )
    elif actions:
        parts: list[str] = []
        for a in actions:
            if a["type"] == "add_habit":
                try:
                    from db import plural_count  # локальный импорт — без циклов
                    qty_text = f"{a['target']} {plural_count(int(a['target']), a['unit'])}"
                except Exception:  # noqa: BLE001 — реплика не должна ломать применение
                    qty_text = f"{a['target']} {a['unit']}"
                parts.append(
                    f"Добавил «{a['title']}» — {_days_label(a['days'])}, "
                    f"{qty_text} в день."
                )
            elif a["type"] == "reduce_habit":
                old = next(
                    (h["target"] for h in habits if h["title"] == a["habit_title"]),
                    "?",
                )
                parts.append(
                    f"Снизил «{a['habit_title']}»: {old} → {a['new_target']} в день. "
                    "Прогресс сохранён."
                )
            elif a["type"] == "delete_habit":
                parts.append(f"Удалил «{a['habit_title']}».")
            elif a["type"] == "freeze_habit":
                until = (
                    date.today() + timedelta(days=int(a["days"]) - 1)
                ).strftime("%d.%m")
                parts.append(
                    f"«{a['habit_title']}» на паузе до {until} — прогресс сохранён, "
                    "эти дни не считаются пропущенными."
                )
            elif a["type"] == "set_checkpoint":
                parts.append(
                    f"Контрольная точка через {a['days']} дн. — вернусь "
                    "со сравнением статистики."
                )
        reply = " ".join(parts) or _SUPPORT_REPLIES["none"]
    elif zone in ("yellow", "red"):
        # зона вычислена из реальной статистики недели — говорим честно и с цифрами
        from wellbeing import SUPPORT  # локальный импорт — без циклов
        stats = (wellbeing or {}).get("stats") or {}
        pct = stats.get("pct")
        skipped = stats.get("skippedDays")
        base = SUPPORT.get(zone) or ""
        if base:
            reply = (
                base.rstrip() + " "
                f"(по данным недели: выполнение {pct if pct is not None else '—'}%, "
                f"полных пропусков {skipped}.)"
            )
        else:
            reply = _SUPPORT_REPLIES["none"]
    elif fatigue or heavy:
        reply = _SUPPORT_REPLIES["fatigue_care"]
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


def finalize_plan(plan: dict, message: str, habits: list[dict]) -> dict:
    """Финальная фаза разбора (применяется к ЛЮБОМУ плану — LLM и fallback):
    1) перекрёстный контроль add_habit по исходному тексту (reconcile);
    2) строгая валидация: add_habit выживает только с названием, явным графиком
       и количеством из сообщения — иначе действие снимается и ассистент задаёт
       один уточняющий вопрос (никаких «Новая привычка» и дефолтных заглушек);
    3) reduce/delete/freeze срабатывают только по реально существующим привычкам
       — удаление несуществующих (галлюцинаций) блокируется."""
    plan = reconcile_add_actions(plan, message)
    actions = [a for a in (plan.get("actions") or []) if isinstance(a, dict)]

    title = _extract_title(message)
    sched = bool(_SCHEDULE_HINT_RE.search(message))
    qty = _has_explicit_quantity(message)

    valid: list[dict] = []
    dropped_add = False       # неполный add → нужен уточняющий вопрос
    dropped_missing = False   # действие по несуществующей привычке

    for act in actions:
        kind = (act.get("type") or "").lower().strip()
        if kind == "add_habit":
            act_title = str(act.get("title") or "").strip()
            bad_title = (
                not act_title
                or act_title.lower() in _PLACEHOLDER_TITLES
                or _title_is_service(act_title)
            )
            act["days"] = _norm_days(act.get("days"))
            if not act["days"]:
                # дни не названы ни моделью, ни текстом → берём из сообщения
                act["days"] = _norm_days(_extract_days(message))
            try:
                act["target"] = max(1, min(100000, int(act.get("target") or 1)))
            except (TypeError, ValueError):
                act["target"] = 1
            act["unit"] = str(act.get("unit") or "раз").strip()[:40] or "раз"
            if bad_title or not sched or not qty or not act["days"]:
                dropped_add = True
                log.warning(
                    "add_habit отклонён (неполные данные): title=%r sched=%s qty=%s",
                    act_title, sched, qty,
                )
                continue
            valid.append(act)
        elif kind in ("reduce_habit", "delete_habit", "freeze_habit"):
            t = str(act.get("habit_title") or "").strip().lower()
            if not t or not _habit_exists(t, habits):
                dropped_missing = True
                log.warning("действие %s отклонено: привычки нет в списке", kind)
                continue
            valid.append(act)
        else:
            valid.append(act)  # none / set_checkpoint / прочее

    if dropped_add and not any(
        a.get("type") in ("add_habit", "reduce_habit", "delete_habit",
                          "freeze_habit", "set_checkpoint")
        for a in valid
    ):
        # ничего полезного применить нельзя — задаём уточняющий вопрос
        plan["actions"] = [{"type": "none"}]
        plan["reply"] = _clarify_add(title if title else "", not sched, not qty)
        return plan
    if dropped_missing and not valid:
        plan["actions"] = [{"type": "none"}]
        plan["reply"] = _not_found_reply(habits)
        return plan

    plan["actions"] = valid or [{"type": "none"}]
    return plan


# === Интервью создания привычки: пошаговый сбор параметров =======================
#
# Порядок вопросов: категория → график → цель+единица → шаг.
# Важное (график, цель) — переспрашиваем; отказ/игнор категории и шага —
# генерируем сами. Никаких заглушек: привычка создаётся только после полного
# набора параметров. Черновик интервью хранится в БД (chat_drafts) по устройству.

_CANCEL_RE = re.compile(
    r"отмен\w*|забудь|отставить|передумал|стоп\b|хватит\s*спраш", re.IGNORECASE
)
# отказ от ответа: «сами подбери», «не важно» — параметр генерируем сами
_REFUSAL_RE = re.compile(
    r"\bсам(?:и|о|а|м)?\b|не\s*зна\w*|любой|все\s*равно|неважно|не\s*важно"
    r"|как\s*хочешь|без\s*разницы|дефолт|умолчан|пропуст\w*|не\s*буд\w*"
    r"|не\s*хочу\s*отве|не\s*нужно|давай\s*свою",
    re.IGNORECASE,
)
# ответ-согласие: «да», «давай» на вопрос-предложение = принять предложение
_AGREE_RE = re.compile(
    r"^(?:да\b|давай\b|ок\b|окей|хорошо|ладно|угу|ага|верно|точно|норм\b|соглас\w*)",
    re.IGNORECASE,
)
# «да» целиком — не название привычки и не новый параметр
_BARE_AGREE_RE = re.compile(
    r"^(?:да|давай|ок|окей|хорошо|ладно|угу|ага|верно|точно|норм|соглас[еён]\w*)"
    r"[.!\s]*$",
    re.IGNORECASE,
)
# другие команды важнее интервью: удаление/снижение/пауза/контрольная точка
_OTHER_CMD_RE = re.compile(
    r"удал\w*|снес\w*|избав\w*|стёр|замороз\w*|на\s+пау[зкс]|передышк\w*|"
    r"снизь\w*|уменьши\w*|сократи\w*|полегче|послабл\w*|контрольн\w*\s*точк",
    re.IGNORECASE,
)

# «каждые 3 дня», «через день» — интервальный график
_INTERVAL_WORDS_RE = re.compile(r"кажд\w*\s+(\d{1,2})\s+дн\w*", re.IGNORECASE)
# «через 2 дня» = с перерывом в 2 дня = каждые 3 дня
_INTERVAL_THROUGH_RE = re.compile(r"через\s+(\d{1,2})\s+дн\w*", re.IGNORECASE)
# «каждый третий день» — интервал словом (требуем слово «день/дня», чтобы не
# задеть «каждый вторник»)
_INTERVAL_ORDINAL_RE = re.compile(
    r"кажд\w*\s+(втор|трет|четв|пят)\w*\s+д(?:н\w*|ень)", re.IGNORECASE,
)
_ORDINAL_NUM = {"втор": 2, "трет": 3, "четв": 4, "пят": 5}
_EVERY_OTHER_RE = re.compile(
    r"через\s+(?:день|сутки|один\s+день)"
    r"|каждый\s+второй\s+день"
    r"|каждые\s+(?:чётные|четные|нечётные|нечетные)",
    re.IGNORECASE,
)
# «1-го и 15-го», «5 числа каждого месяца» — дни месяца
_MONTH_WORDS_RE = re.compile(r"числ\w*|месяц\w*", re.IGNORECASE)

# автокатегория по ключевым словам названия (когда пользователь сказал «сам»)
_AUTO_CATEGORY = (
    (r"бег|пробеж|ходь|скакалк|отжима|подтягив|пресс|планк|плаван|бассейн|"
     r"велосипед|йог|трениров|зарядк|растяж|спорт|гантел|турник|присед|снах?орт",
     "Спорт"),
    (r"вод\w*|пить|сон|спать|вес\w*|таблетк|витамин|лекарств|зуб|кож|душ|закалив",
     "Здоровье"),
    (r"чита|книг|медит|дневник|рефлекс|аффирмац|саморазв|блог|обзор",
     "Саморазвитие"),
    (r"уч\w*|курс|лекц|английск|немецк|испанск|язык|экзамен|зачет|зачёт|"
     r"лаб[оауыи]|лаборатор|семинар|практикум|реферат|сесси|домашк|диплом|конспект",
     "Учеба"),
    (r"работ|проект|дедлайн|созвон|встреч|почт|задач|отчёт|отчет|митинг",
     "Работа"),
    (r"убор|мыть|посуд|стирк|готов|покупк|цвет|растени|мусор|пылесос|постел",
     "Дом"),
    # «позвон|(?<!со)звон» — без «созвон» (это Работа)
    (r"позвон|(?<!со)звон|бабушк|дедушк|родител|мам|пап|сем[еья]|"
     r"друз|подруг|переписк|сообщен",
     "Общение"),
)


def _auto_category(title: str) -> str:
    """Подбор категории из названия: «бегать» → «Спорт», иначе «Другое»."""
    t = (title or "").lower()
    for pattern, name in _AUTO_CATEGORY:
        if re.search(pattern, t):
            return name
    return "Другое"


def _parse_schedule(message: str) -> list[str]:
    """График из текста → токены графика. [] — график не назван."""
    m = _INTERVAL_WORDS_RE.search(message)
    if m:
        return [f"каждые{max(2, min(30, int(m.group(1))))}"]
    m = _INTERVAL_THROUGH_RE.search(message)
    if m:
        return [f"каждые{max(2, min(31, int(m.group(1)) + 1))}"]
    m = _INTERVAL_ORDINAL_RE.search(message)
    if m:
        num = _ORDINAL_NUM.get(m.group(1).lower())
        if num:
            return [f"каждые{num}"]
    if _EVERY_OTHER_RE.search(message):
        return ["каждые2"]
    cleaned, _ = _split_time(message)
    cleaned = _normalize_shorthand(cleaned)
    # дни месяца: числа рядом со словами «числа»/«месяц» или суффикс «-го» («1-го и 15-го»)
    if _MONTH_WORDS_RE.search(cleaned) or re.search(r"\b\d{1,2}\s*-\s*г[оое]\b", cleaned):
        no_qty = _QUANTITY_RE.sub(" ", cleaned)
        nums = [
            int(n) for n in re.findall(r"\b(\d{1,2})\b", no_qty) if 1 <= int(n) <= 31
        ]
        if nums:
            return [str(n) for n in dict.fromkeys(nums)]
    days = _extract_days(message)
    if days != list(DAY_CODES):
        return days
    if _EVERYDAY_RE.search(message):
        return list(DAY_CODES)
    return []


def _parse_category_answer(message: str, categories: list[str]) -> str | None:
    """Категория из ответа: имя существующей / новая / 'AUTO' (отказ) / None."""
    if _REFUSAL_RE.search(message):
        return "AUTO"
    q = _QUOTED_RE.search(message)
    text = q.group(1) if q else message
    cand = _clean_title_candidate(text)
    if not cand:
        return None
    cand = re.sub(r"^(?:в|во|к|на|по|для|из)\s+", "", cand, flags=re.IGNORECASE)
    cand = cand.strip(" \t.,;:!?«»\"'-—")
    low = cand.lower()
    if not low or low in _PLACEHOLDER_TITLES or not re.search(r"[а-яёa-z]", low):
        return None
    if _AGREE_RE.match(low):
        return "AUTO"
    if _title_is_service(cand):
        return None
    for c in categories:
        cl = c.lower()
        if cl == low or cl in low or low in cl:
            return c
    return cand[:1].upper() + cand[1:40]


def _parse_step_answer(message: str) -> int | None:
    """Шаг увеличения из ответа: «5 страниц», «2 подхода», «3»."""
    cleaned, _ = _split_time(message)
    cleaned = _normalize_shorthand(cleaned)
    m = _TARGET_RE.search(cleaned)
    if m and m.group(2):
        return max(1, int(m.group(1)))
    n = re.search(r"\b(\d{1,4})\b", _QUANTITY_RE.sub(" ", cleaned))
    return max(1, int(n.group(1))) if n else None


def _default_step(ans: dict) -> int:
    """Авто-шаг, когда пользователь сказал «сам» или промолчал."""
    t = int(ans.get("target") or 1)
    if (ans.get("unit") or "").lower() == "минута" and t >= 10:
        return 5  # минуты: шаг в 5 минут удобнее единичной минуты
    return 1


_STAGES = ["category", "schedule", "quantity", "step"]


def _stage_filled(stage: str, ans: dict) -> bool:
    if stage == "category":
        return bool(ans.get("category"))
    if stage == "schedule":
        return bool(ans.get("days"))
    if stage == "quantity":
        return bool(ans.get("target")) and bool(ans.get("unit"))
    if stage == "step":
        return ans.get("step") is not None
    return True


def _next_stage(cur: str, ans: dict) -> str:
    try:
        idx = _STAGES.index(cur)
    except ValueError:
        idx = 0
    for st in _STAGES[idx:]:
        if not _stage_filled(st, ans):
            return st
    return "done"


def _ask(stage: str, title: str, categories: list[str], ans: dict) -> tuple[str, dict]:
    """Вопрос этапа + предложение по умолчанию (стратегия консультации:
    предлагаем разумное значение, человек подтверждает «да» или правит)."""
    if stage == "title":
        return (
            "Какую привычку добавить? Напиши название — "
            "например: «Бег», «Медитация», «Пить воду»."
        ), {}
    if stage == "category":
        auto = _auto_category(title)
        names = ", ".join(categories) if categories else ""
        if names:
            text = (
                f"В какую категорию отнести «{title}»? Есть: {names}. "
                "Назови одну из них, придумай новую или напиши «сам» — подберу."
            )
        else:
            text = (
                f"В какую категорию отнести «{title}»? Назови свою или "
                "напиши «сам» — подберу."
            )
        if auto != "Другое":
            text += f" Или согласись с моим вариантом «{auto}» — просто «да»."
            return text, {"category": auto}
        return text, {}
    if stage == "schedule":
        return (
            f"По каким дням выполнять «{title}»? Например: каждый день, "
            "по вт и чт, 1-го и 15-го числа, каждые 3 дня. "
            "Если каждый день — просто напиши «да»."
        ), {"days": list(DAY_CODES)}
    if stage == "quantity":
        unit = (ans.get("unit") or "раз").lower()
        return (
            f"Сколько в день «{title}» и в чём мерить? "
            "Например: 10 минут, 3 раза, 20 страниц. "
            f"Или согласись с «1 {unit} в день» — просто «да»."
        ), {"target": 1, "unit": ans.get("unit") or "раз"}
    if stage == "step":
        from db import plural_count

        step = _default_step(ans)
        unit = (ans.get("unit") or "раз").lower()
        return (
            f"С каким шагом отмечать прогресс по «{title}»? "
            f"Например: 1 отжимание, 5 страниц. Предлагаю {step} "
            f"{plural_count(step, unit)} за нажатие — согласен?"
        ), {"step": step}
    return "", {}


def _created_reply(act: dict, auto: list[str]) -> str:
    """Фактологичное подтверждение создания: что добавлено, все параметры."""
    from db import days_label, plural_count

    unit = act["unit"]
    step = int(act.get("step") or 1)
    parts = [
        f"Добавил «{act['title']}» — {act['category']}, "
        f"{days_label(act['days']).lower()}, "
        f"{act['target']} {plural_count(act['target'], unit)} в день, "
        f"шаг {step} {plural_count(step, unit)}."
    ]
    if "category" in auto:
        parts.append(f"Категорию «{act['category']}» подобрал сам.")
    if "schedule" in auto:
        parts.append("График «каждый день» поставил сам — скажи, если поменять.")
    if "quantity" in auto:
        parts.append("План поставил 1 раз — скорректируй, если нужно.")
    if "step" in auto:
        parts.append("Шаг выбрал сам.")
    return " ".join(parts)


def _start_interview(message: str, categories: list[str]) -> tuple[dict, str]:
    """Начало интервью: вытаскиваем всё названное сразу, задаём первый вопрос."""
    title = _extract_title(message)
    ans: dict = {}
    sched = _parse_schedule(message)
    if sched:
        ans["days"] = sched
    if _has_explicit_quantity(message):
        ans["target"], ans["unit"] = _extract_target_unit(message)
    if not title or _title_is_service(title) or title.lower() in _PLACEHOLDER_TITLES:
        question, suggest0 = _ask("title", "", categories, {})
        draft = {"title": "", "stage": "title", "ans": {}, "tries": 0,
                 "auto": [], "suggest": suggest0}
        return draft, question
    stage = _next_stage("category", ans)
    question, suggest0 = _ask(stage, title, categories, ans)
    draft = {"title": title, "stage": stage, "ans": ans, "tries": 0,
             "auto": [], "suggest": suggest0}
    return draft, question


def _stage_key(stage: str) -> str | None:
    """Какой ключ ans закрывает этап."""
    return {
        "category": "category", "schedule": "days",
        "quantity": "target", "step": "step",
    }.get(stage)


def _validate_params(raw: dict, categories: list[str] | None = None) -> dict:
    """Параметры от LLM/предложений → допустимые значения; мусор выкидываем."""
    out: dict = {}
    if not isinstance(raw, dict):
        return out
    cat = raw.get("category")
    if isinstance(cat, str):
        cat = cat.strip().strip("«»\"'")[:40]
        if cat and re.search(r"[а-яёa-z]", cat, re.I) and cat.lower() not in _PLACEHOLDER_TITLES:
            out["category"] = cat[:1].upper() + cat[1:]
    days = raw.get("days")
    if isinstance(days, str):
        days = _parse_schedule(days)
    if isinstance(days, list):
        toks: list[str] = []
        for d in days:
            s = str(d).strip()
            low = s.lower()
            if s in DAY_CODES:
                tok = s
            elif re.fullmatch(r"\d{1,2}", s) and 1 <= int(s) <= 31:
                tok = s
            elif re.fullmatch(r"каждые\d{1,2}", low):
                tok = low
            elif "выходн" in low:
                toks.extend(["Сб", "Вс"])
                continue
            elif "будн" in low:
                toks.extend(DAY_CODES[:5])
                continue
            elif low.startswith("кажд") or low in ("ежедневно", "весь день"):
                toks.extend(DAY_CODES)
                continue
            else:
                tok = next((c for stem, c in _DAY_STEMS if low.startswith(stem)), None)
            if tok and tok not in toks:
                toks.append(tok)
        if toks:
            # страховка: если вернулась арифметическая прогрессия дат месяца
            # («2, 4, 6, 8, 10») с шагом 2–6 — это на самом деле интервал
            # («каждые 2 дня»), а не даты месяца
            nums = [int(t) for t in toks if re.fullmatch(r"\d{1,2}", t)]
            if len(nums) == len(toks) >= 4:
                vals = sorted(nums)
                step = vals[1] - vals[0]
                if 2 <= step <= 6 and all(b - a == step for a, b in zip(vals, vals[1:])):
                    toks = [f"каждые{step}"]
            out["days"] = toks
    for key, hi in (("target", 100000), ("step", 10000)):
        v = raw.get(key)
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)) and v >= 1:
            out[key] = min(int(v), hi)
        elif isinstance(v, str) and v.strip().isdigit():
            out[key] = min(int(v.strip()), hi)
    unit = raw.get("unit")
    if isinstance(unit, str) and unit.strip():
        unit = re.sub(r"[^а-яёa-z -]", "", unit.lower()).strip()[:40]
        if unit:
            from db import canon_unit

            out["unit"] = canon_unit(unit)
    return out


async def _interview(
    message: str, draft: dict, categories: list[str],
    history: list[dict] | None = None,
) -> tuple[dict | None, str, list[dict]]:
    """Один шаг интервью. Понимание ответа: детерминированные правила + LLM-консультация
    (если есть ключ — она первична: свободный язык, живые вопросы, предложения).
    Возвращает (новый черновик | None, реплика, действия)."""
    title = (draft.get("title") or "").strip()
    ans = dict(draft.get("ans") or {})
    tries = int(draft.get("tries") or 0)
    auto = list(draft.get("auto") or [])
    stage = draft.get("stage") or "category"
    suggest = dict(draft.get("suggest") or {})
    history = history or []

    if stage == "title":
        if _BARE_AGREE_RE.match(message.strip()):
            tries += 1  # «да» — это не название
        else:
            t = _extract_title(message)
            if t and not _title_is_service(t) and t.lower() not in _PLACEHOLDER_TITLES:
                title = t
                stage = "category"
            else:
                tries += 1
        if stage == "title":
            if tries >= 3:
                return None, (
                    "Название так и не названо — интервью прервал. "
                    "Напиши «создай привычку <название>», когда будешь готов."
                ), []
            q, _s = _ask("title", "", categories, {})
            return {"title": "", "stage": "title", "ans": {}, "tries": tries,
                    "auto": auto, "suggest": {}}, q, []
        # название получено: график/количество могли прийти тем же сообщением,
        # но ЭТО сообщение — не ответ на вопрос о категории
        found0: dict = {}
        sched0 = _parse_schedule(message)
        if sched0:
            found0["days"] = sched0
        if _has_explicit_quantity(message):
            found0["target"], found0["unit"] = _extract_target_unit(message)
        merged0 = dict(found0)
        nxt0 = _next_stage("category", merged0)
        if nxt0 == "done":
            act0 = {
                "type": "add_habit",
                "title": title,
                "category": "Другое",
                "emoji": "",
                "days": merged0.get("days") or list(DAY_CODES),
                "target": int(merged0.get("target") or 1),
                "unit": merged0.get("unit") or "раз",
                "step": int(merged0.get("step") or 1),
            }
            return None, _created_reply(act0, []), [act0]
        question0, suggest0 = _ask(nxt0, title, categories, merged0)
        return {"title": title, "stage": nxt0, "ans": merged0, "tries": 0,
                "auto": [], "suggest": suggest0}, question0, []

    found: dict = {}
    autofilled = False

    # --- 1. Детерминированный разбор ответа (правила — страховка) --------------
    stage_param_found = False
    if stage == "category":
        cat = _parse_category_answer(message, categories)
        if cat == "AUTO":
            if (
                _AGREE_RE.match(message.strip())
                and not _REFUSAL_RE.search(message)
                and suggest.get("category")
            ):
                found["category"] = suggest["category"]  # человек подтвердил «да»
            else:
                found["category"] = suggest.get("category") or _auto_category(title)
                auto.append("category")
            stage_param_found = True
        elif cat:
            found["category"] = cat
            stage_param_found = True
    elif stage == "schedule":
        sched = _parse_schedule(message)
        if sched:
            found["days"] = sched
            stage_param_found = True
    elif stage == "quantity":
        if _has_explicit_quantity(message):
            found["target"], found["unit"] = _extract_target_unit(message)
            stage_param_found = True
        elif re.fullmatch(r"\d{1,3}", message.strip()):
            # голое число — тоже ответ на «сколько?» («20» → 20 раз)
            found["target"] = int(message.strip())
            found["unit"] = ans.get("unit") or "раз"
            stage_param_found = True
    elif stage == "step":
        if _REFUSAL_RE.search(message):
            found["step"] = suggest.get("step") or _default_step(ans)
            auto.append("step")
            stage_param_found = True
        else:
            s = _parse_step_answer(message)
            if s:
                found["step"] = s
                stage_param_found = True

    # попутные параметры тем же сообщением («спорт, по вск, 2 раза»)
    if stage != "schedule" and not ans.get("days") and not found.get("days"):
        sched = _parse_schedule(message)
        if sched:
            found["days"] = sched
    if stage != "quantity" and not ans.get("target") and not found.get("target"):
        if _has_explicit_quantity(message):
            found["target"], found["unit"] = _extract_target_unit(message)

    # --- 2. Соглашение с предложенным («да» на мой вопрос-предложение) ---------
    if not stage_param_found and suggest and _AGREE_RE.match(message.strip()):
        sugg = _validate_params(suggest, categories)
        if sugg:
            found.update(sugg)
            stage_param_found = True

    # --- 3. LLM-консультация: понимание свободного языка поверх правил ---------
    llm_reply = ""
    llm_proposal: dict = {}
    if LLM_API_KEY and stage != "title":
        tmp = {**ans, **found}
        later = [st for st in _STAGES[_STAGES.index(stage) + 1:]
                 if not _stage_filled(st, tmp)]
        missing = later if _stage_filled(stage, tmp) else [stage, *later]
        res = await llm_interview_step(
            message, title, stage, tmp, suggest, categories, missing, history
        )
        if res:
            understood = _validate_params(res.get("understood") or {}, categories)
            for k, v in understood.items():
                found[k] = v  # понимание LLM перекрывает шаблоны
                if k == _stage_key(stage):
                    stage_param_found = True
            llm_proposal = _validate_params(res.get("proposal") or {}, categories)
            llm_reply = (res.get("reply") or "").strip()[:600]

    merged = dict(ans)
    for k, v in found.items():
        if v:
            merged[k] = v

    # --- 4. Не поняли → счётчик переспрашиваний → авто-подстановка -------------
    stage_filled_now = _stage_filled(stage, merged)
    if stage_filled_now:
        tries = 0
    else:
        tries += 1
        threshold = 2 if stage in ("category", "step") else 4
        if tries >= threshold:
            # игнор: заполняем сами (честно пометим при создании)
            if stage == "category":
                merged["category"] = suggest.get("category") or _auto_category(title)
                auto.append("category")
            elif stage == "schedule":
                merged["days"] = suggest.get("days") or list(DAY_CODES)
                auto.append("schedule")
            elif stage == "quantity":
                merged["target"] = suggest.get("target") or 1
                merged["unit"] = suggest.get("unit") or "раз"
                auto.append("quantity")
            elif stage == "step":
                merged["step"] = suggest.get("step") or _default_step(merged)
                auto.append("step")
            autofilled = True
            tries = 0
            stage_filled_now = True

    nxt = _next_stage(stage, merged)
    if nxt == "done":
        act = {
            "type": "add_habit",
            "title": title,
            "category": merged.get("category") or "Другое",
            "emoji": "",
            "days": merged.get("days") or list(DAY_CODES),
            "target": int(merged.get("target") or 1),
            "unit": merged.get("unit") or "раз",
            "step": int(merged.get("step") or 1),
        }
        return None, _created_reply(act, auto), [act]

    if nxt != stage:
        tries = 0  # счётчик переспрашиваний — свой у каждого вопроса
    # вопрос следующего этапа + предложение по умолчанию
    question, next_suggest = _ask(nxt, title, categories, merged)
    reply = question
    final_suggest = next_suggest
    if llm_reply and not autofilled:
        # живая формулировка от LLM (кроме случая, когда сами заполнили параметр)
        reply = llm_reply
        if llm_proposal:
            final_suggest = llm_proposal
    new_draft = {
        "title": title, "stage": nxt, "ans": merged, "tries": tries,
        "auto": auto, "suggest": final_suggest,
    }
    return new_draft, reply, []


async def parse_intent(
    message: str, habits: list[dict], history: list[dict], wellbeing: dict | None = None,
    draft: dict | None = None, categories: list[str] | None = None,
) -> dict:
    """Точка входа NLP.

    1) Черновик интервью активен → обрабатываем ответ на текущий вопрос.
    2) Просьба создать привычку → начинаем интервью (детерминированно,
       одинаково с LLM-ключом и без).
    3) Остальные команды → LLM, при сбое/отсутствии ключа fallback, затем
       finalize_plan (валидация без заглушек и действий по чужим привычкам).
    План содержит «draft»: новый черновик интервью или None."""
    wellbeing = wellbeing or {}
    categories = categories or []
    text = message.lower()

    # другие команды (удаление/снижение/пауза) важнее интервью и создания
    other_cmd = bool(_OTHER_CMD_RE.search(message))
    if other_cmd:
        draft = None

    if draft:
        if _CANCEL_RE.search(message) and len(message.split()) <= 4:
            return {
                "reply": "Отменил создание — черновик стёр.",
                "actions": [{"type": "none"}],
                "draft": None,
            }
        # «создай привычку X» во время интервью → начинаем заново с новым названием
        t_new = (
            _extract_title(message)
            if (not other_cmd and (_ADD_RE.search(text) or "привычк" in text))
            else None
        )
        if (
            t_new and not _title_is_service(t_new)
            and (draft.get("stage") or "") != "title"
        ):
            draft, reply = _start_interview(message, categories)
            return {"reply": reply, "actions": [{"type": "none"}], "draft": draft}
        new_draft, reply, actions = await _interview(message, draft, categories, history)
        return {
            "reply": reply,
            "actions": actions or [{"type": "none"}],
            "draft": new_draft,
        }

    if not other_cmd and (_ADD_RE.search(text) or "привычк" in text):
        draft, reply = _start_interview(message, categories)
        return {"reply": reply, "actions": [{"type": "none"}], "draft": draft}

    if LLM_API_KEY:
        try:
            plan = await llm_parse(message, habits, history, wellbeing.get("prompt", ""))
        except Exception as e:  # noqa: BLE001 — любой сбой уводит в fallback
            log.warning("LLM недоступна, транзакция ушла в fallback: %s", e)
            plan = fallback_parse(message, habits, wellbeing)
    else:
        plan = fallback_parse(message, habits, wellbeing)
    plan = finalize_plan(plan, message, habits)

    # страховка: LLM вернул add_habit → переводим в интервью, ничего не создаём
    if any(
        isinstance(a, dict) and a.get("type") == "add_habit"
        for a in plan.get("actions") or []
    ):
        draft, reply = _start_interview(message, categories)
        return {"reply": reply, "actions": [{"type": "none"}], "draft": draft}

    plan["draft"] = None
    return plan
