# -*- coding: utf-8 -*-
"""Интеграционный тест чат-модуля: текст из чата → привычка в базе данных.

Сценарий:
1. Чистая БД (временная папка, без LLM-ключа → rule-based fallback).
2. POST /api/chat: поток сознания + просьба добавить привычку.
3. Привычка появляется в GET /api/habits (т.е. записана в sqlite).
4. POST /api/chat: жалоба на усталость → планка снижается, прогресс НЕ сбрасывается.
5. Клик «+» и «отметить день» работают как раньше.
"""
import os
import sys
import tempfile

# ВАЖНО: до импорта main очищаем окружение и выбираем временную БД
os.environ.pop("LLM_API_KEY", None)  # форсируем локальный fallback-парсер
_TMP = tempfile.mkdtemp(prefix="grit-test-")
os.environ["DATA_DIR"] = _TMP

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402
import main  # noqa: E402
import db  # noqa: E402

client = TestClient(main.app)
failures = []


def check(name: str, cond: bool, extra: str = ""):
    mark = "PASS" if cond else "FAIL"
    print(f"[{mark}] {name} {extra}")
    if not cond:
        failures.append(name)


print("=== 0. Стартовое состояние ===")
habits = client.get("/api/habits").json()
names = [h["title"] for h in habits]
check("демо-данные засеяны", "Отжимания" in names and "Английский язык" in names, str(names))

print("\n=== 1. Чат: добавление привычки из потока сознания ===")
r = client.post(
    "/api/chat",
    json={"message": "Привет. Вчера не выспался, голова тяжёлая, но решил: добавь привычку «Медитация» 10 минут по утрам каждый день."}
)
check("POST /api/chat → 200", r.status_code == 200, str(r.status_code))
data = r.json()
print("Ответ ассистента:", data["reply"])
print("Применённые действия:", data["applied"])
check("есть действие add_habit", any(a["type"] == "add_habit" for a in data["applied"]))

habits = client.get("/api/habits").json()
names = [h["title"] for h in habits]
check("Медитация появилась в БД", "Медитация" in names, str(names))
med = next(h for h in habits if h["title"] == "Медитация")
check("цель = 10 минут", med["target"] == 10 and med["unit"] == "минута",
      f"{med['target']} {med['unit']}")
check("график = каждый день", len(med["days"]) == 7, str(med["days"]))
check("прогресс с нуля", med["current"] == 0, str(med["current"]))

print("\n=== 2. Чат: усталость → снижение планки без сброса прогресса ===")
# сначала набираем прогресс отжиманиям вручную
client.post("/api/habits/1/increment")
before = next(h for h in client.get("/api/habits").json() if h["id"] == 1)
check("прогресс отжиманий = 1/84", before["current"] == 1 and before["target"] == 84,
      f"{before['current']}/{before['target']}")

r = client.post(
    "/api/chat",
    json={"message": "Я сегодня просто выжат, устал как собака и нет сил. Снизь нагрузку по отжиманиям до 40, пожалуйста."}
)
data = r.json()
print("Ответ ассистента:", data["reply"])
print("Применённые действия:", data["applied"])
check("есть действие reduce_habit", any(a["type"] == "reduce_habit" for a in data["applied"]))

after = next(h for h in client.get("/api/habits").json() if h["id"] == 1)
check("план отжиманий стал 40", after["target"] == 40, str(after["target"]))
check("прогресс не сброшен (1/40)", after["current"] == 1, str(after["current"]))

print("\n=== 3. Клик «+» и «отметить день» ===")
r = client.post("/api/habits/3/increment").json()
check("медитация 1/10 после клика", r["current"] == 1, str(r["current"]))
r = client.post("/api/habits/3/complete").json()
check("медитация закрыта 10/10, статус done", r["current"] == 10 and r["status"] == "done",
      f"{r['current']} {r['status']}")

print("\n=== 4. История чата сохранена в БД ===")
hist = client.get("/api/chat/history").json()
roles = [m["role"] for m in hist]
check("4 сообщения (2 пользователя, 2 ассистента)", roles.count("user") == 2 and roles.count("assistant") == 2, str(roles))

print("\n=== 5. Форма «Новая привычка»: ручное создание ===")
r = client.post(
    "/api/habits",
    json={"title": "Зарядка", "category": "Спорт", "target": 15, "unit": "минут"},
)
check("POST /api/habits → 201", r.status_code == 201, str(r.status_code))
created = r.json()
check("привычка создана «Зарядка»", created["title"] == "Зарядка", str(created["title"]))
check("цель 15 минут", created["target"] == 15 and created["unit"] == "минута",
      f"{created['target']} {created['unit']}")
habits = client.get("/api/habits").json()
check("Зарядка в списке привычек", any(h["title"] == "Зарядка" for h in habits))
check("новая категория «Спорт» сгруппирована", any(h["category"] == "Спорт" for h in habits))

print("\n=== 6. Прямая запись привычек в sqlite ===")
import sqlite3  # noqa: E402
con = sqlite3.connect(os.path.join(_TMP, "app.db"))
rows = con.execute("SELECT title, target, unit FROM habits ORDER BY id").fetchall()
print("sqlite contents:", rows)
check("Медитация физически в таблице habits", any(r[0] == "Медитация" for r in rows))

print("\n=== 7. Удаление по удержанию: привычки и категории ===")
from urllib.parse import quote  # noqa: E402

h1 = client.post(
    "/api/habits", json={"title": "Чтение 1", "category": "Хобби", "target": 5, "unit": "страниц"}
).json()
h2 = client.post(
    "/api/habits", json={"title": "Рисование", "category": "Хобби", "target": 10, "unit": "минут"}
).json()
r = client.delete(f"/api/habits/{h1['id']}")
check("DELETE привычки → ok", r.json().get("deleted") is True, str(r.json()))
habits = client.get("/api/habits").json()
check("вторая привычка осталась в «Хобби»",
      any(h["title"] == "Рисование" and h["category"] == "Хобби" for h in habits))
client.delete(f"/api/habits/{h2['id']}")
habits = client.get("/api/habits").json()
check("последняя привычка удалена → категория «Хобби» исчезла сама",
      not any(h["category"] == "Хобби" for h in habits))

tmp = client.post(
    "/api/habits", json={"title": "Полив цветов", "category": "Проверка", "target": 1, "unit": "раз"}
).json()
r = client.delete(f"/api/categories/{quote('Проверка')}")
check("DELETE категории → удалена 1 привычка", r.json().get("deleted") == 1, str(r.json()))
habits = client.get("/api/habits").json()
check("все привычки категории ушли", not any(h["id"] == tmp["id"] for h in habits))
r = client.delete(f"/api/categories/{quote('Проверка')}")
check("несуществующая категория → deleted 0", r.json().get("deleted") == 0)

print()
if failures:
    print("ИТОГ: НЕ ПРОЙДЕНО ->", failures)
    sys.exit(1)
print("ИТОГ: все проверки пройдены ✔")
