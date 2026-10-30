# -*- coding: utf-8 -*-
"""Интеграционный тест чат-модуля: текст из чата → привычка в базе данных.

Сценарий:
1. Чистая БД (временная папка, без LLM-ключа → rule-based fallback), без демо-данных.
2. POST /api/chat: поток сознания + просьба добавить привычку.
3. Привычка появляется в GET /api/habits (т.е. записана в sqlite).
4. POST /api/chat: жалоба на усталость → планка снижается, прогресс НЕ сбрасывается.
5. Клик «+» и «отметить день» работают как раньше.
6. Форма «Новая привычка», удаление привычек/категорий.
7. Изоляция устройств: X-Device-ID — у каждого свои привычки и история чата.
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
DEV = {"X-Device-ID": "device-1"}  # все запросы «первого устройства»


def check(name: str, cond: bool, extra: str = ""):
    mark = "PASS" if cond else "FAIL"
    print(f"[{mark}] {name} {extra}")
    if not cond:
        failures.append(name)


print("=== 0. Стартовое состояние: главный экран чистый ===")
habits = client.get("/api/habits", headers=DEV).json()
check("главный экран пуст — люди создают сами", habits == [], str(habits))

print("\n=== 1. Чат: добавление привычки из потока сознания ===")
r = client.post(
    "/api/chat",
    json={"message": "Привет. Вчера не выспался, голова тяжёлая, но решил: добавь привычку «Медитация» 10 минут по утрам каждый день."},
    headers=DEV,
)
check("POST /api/chat → 200", r.status_code == 200, str(r.status_code))
data = r.json()
print("Ответ ассистента:", data["reply"])
print("Применённые действия:", data["applied"])
check("есть действие add_habit", any(a["type"] == "add_habit" for a in data["applied"]))

habits = client.get("/api/habits", headers=DEV).json()
names = [h["title"] for h in habits]
check("Медитация появилась в БД", "Медитация" in names, str(names))
med = next(h for h in habits if h["title"] == "Медитация")
check("цель = 10 минут", med["target"] == 10 and med["unit"] == "минута",
      f"{med['target']} {med['unit']}")
check("график = каждый день", len(med["days"]) == 7, str(med["days"]))
check("прогресс с нуля", med["current"] == 0, str(med["current"]))

print("\n=== 2. Чат: усталость → снижение планки без сброса прогресса ===")
r = client.post(
    "/api/habits",
    json={"title": "Отжимания", "category": "Спорт", "target": 84, "unit": "повторение"},
    headers=DEV,
)
check("POST /api/habits → 201", r.status_code == 201, str(r.status_code))
pushups = r.json()
client.post(f"/api/habits/{pushups['id']}/increment", headers=DEV)
before = next(h for h in client.get("/api/habits", headers=DEV).json()
              if h["title"] == "Отжимания")
check("прогресс отжиманий = 1/84", before["current"] == 1 and before["target"] == 84,
      f"{before['current']}/{before['target']}")

r = client.post(
    "/api/chat",
    json={"message": "Я сегодня просто выжат, устал как собака и нет сил. Снизь нагрузку по отжиманиям до 40, пожалуйста."},
    headers=DEV,
)
data = r.json()
print("Ответ ассистента:", data["reply"])
print("Применённые действия:", data["applied"])
check("есть действие reduce_habit", any(a["type"] == "reduce_habit" for a in data["applied"]))

after = next(h for h in client.get("/api/habits", headers=DEV).json()
             if h["title"] == "Отжимания")
check("план отжиманий стал 40", after["target"] == 40, str(after["target"]))
check("прогресс не сброшен (1/40)", after["current"] == 1, str(after["current"]))

print("\n=== 3. Клик «+» и «отметить день» ===")
r = client.post(f"/api/habits/{med['id']}/increment", headers=DEV).json()
check("медитация 1/10 после клика", r["current"] == 1, str(r["current"]))
r = client.post(f"/api/habits/{med['id']}/complete", headers=DEV).json()
check("медитация закрыта 10/10, статус done", r["current"] == 10 and r["status"] == "done",
      f"{r['current']} {r['status']}")

print("\n=== 4. История чата сохранена в БД ===")
hist = client.get("/api/chat/history", headers=DEV).json()
roles = [m["role"] for m in hist]
check("4 сообщения (2 пользователя, 2 ассистента)",
      roles.count("user") == 2 and roles.count("assistant") == 2, str(roles))

print("\n=== 5. Форма «Новая привычка»: ручное создание ===")
r = client.post(
    "/api/habits",
    json={"title": "Зарядка", "category": "Спорт", "target": 15, "unit": "минут"},
    headers=DEV,
)
check("POST /api/habits → 201", r.status_code == 201, str(r.status_code))
created = r.json()
check("привычка создана «Зарядка»", created["title"] == "Зарядка", str(created["title"]))
check("цель 15 минут", created["target"] == 15 and created["unit"] == "минута",
      f"{created['target']} {created['unit']}")
habits = client.get("/api/habits", headers=DEV).json()
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
    "/api/habits", json={"title": "Чтение 1", "category": "Хобби", "target": 5, "unit": "страниц"},
    headers=DEV,
).json()
h2 = client.post(
    "/api/habits", json={"title": "Рисование", "category": "Хобби", "target": 10, "unit": "минут"},
    headers=DEV,
).json()
r = client.delete(f"/api/habits/{h1['id']}", headers=DEV)
check("DELETE привычки → ok", r.json().get("deleted") is True, str(r.json()))
habits = client.get("/api/habits", headers=DEV).json()
check("вторая привычка осталась в «Хобби»",
      any(h["title"] == "Рисование" and h["category"] == "Хобби" for h in habits))
client.delete(f"/api/habits/{h2['id']}", headers=DEV)
habits = client.get("/api/habits", headers=DEV).json()
check("последняя привычка удалена → категория «Хобби» исчезла сама",
      not any(h["category"] == "Хобби" for h in habits))

tmp = client.post(
    "/api/habits", json={"title": "Полив цветов", "category": "Проверка", "target": 1, "unit": "раз"},
    headers=DEV,
).json()
r = client.delete(f"/api/categories/{quote('Проверка')}", headers=DEV)
check("DELETE категории → удалена 1 привычка", r.json().get("deleted") == 1, str(r.json()))
habits = client.get("/api/habits", headers=DEV).json()
check("все привычки категории ушли", not any(h["id"] == tmp["id"] for h in habits))
r = client.delete(f"/api/categories/{quote('Проверка')}", headers=DEV)
check("несуществующая категория → deleted 0", r.json().get("deleted") == 0)

print("\n=== 8. Изоляция устройств: X-Device-ID ===")
DEV2 = {"X-Device-ID": "device-2"}
habits2 = client.get("/api/habits", headers=DEV2).json()
check("у второго устройства своего ничего нет", habits2 == [], str(habits2))

r = client.post("/api/habits", json={"title": "Йога", "category": "Спорт"}, headers=DEV2)
yoga_dev2 = r.json()

# привычка device-1 не видна и не редактируема с device-2
check("чужая привычка не видна в списке",
      not any(h["title"] == "Отжимания" for h in habits2))
r = client.post(f"/api/habits/{pushups['id']}/increment", headers=DEV2).json()
check("чужой «+» не срабатывает", r.get("error") == "Not found", str(r))
r = client.delete(f"/api/habits/{pushups['id']}", headers=DEV2)
check("чужую привычку нельзя удалить", r.json().get("deleted") is False, str(r.json()))
still = next(h for h in client.get("/api/habits", headers=DEV).json()
             if h["id"] == pushups["id"])
check("у владельца привычка цела (1/40)", still["current"] == 1 and still["target"] == 40,
      f"{still['current']}/{still['target']}")

# чат тоже изолирован
r = client.post("/api/chat", json={"message": "добавь привычку «Прогулка» 1 раз в день"},
                headers=DEV2)
check("чат device-2 → 200", r.status_code == 200)
hist2 = client.get("/api/chat/history", headers=DEV2).json()
check("у device-2 своя история (2 сообщения)",
      len(hist2) == 2 and all(m["role"] for m in hist2),
      str([m["role"] for m in hist2]))
hist1 = client.get("/api/chat/history", headers=DEV).json()
check("история device-1 не содержит чужих сообщений",
      not any("Прогулка" in m["content"] for m in hist1))
habits1 = client.get("/api/habits", headers=DEV).json()
check("«Прогулка» device-2 не появилась у device-1",
      not any(h["title"] == "Прогулка" for h in habits1))
check("у device-2 «Прогулка» есть",
      any(h["title"] == "Прогулка" for h in client.get("/api/habits", headers=DEV2).json()))

# старые записи (без device) невидимы никому — веб-локация demo gone
con2 = sqlite3.connect(os.path.join(_TMP, "app.db"))
no_device = con2.execute("SELECT COUNT(*) FROM habits WHERE device=''").fetchone()[0]
check("старых записей без device в базе нет", no_device == 0, str(no_device))

print()
if failures:
    print("ИТОГ: НЕ ПРОЙДЕНО ->", failures)
    sys.exit(1)
print("ИТОГ: все проверки пройдены ✔")
