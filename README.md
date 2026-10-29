# 🎯 Grit — дневник рефлексии и трекер привычек с ИИ-ассистентом

Кроссплатформенное PWA: личный дневник + трекер привычек. Главная фишка — «вылить душу»
в чат-бот: ассистент на базе LLM разбирает поток сознания, сам добавляет новые привычки
и аккуратно снижает планку нагрузки на день **без сброса прогресса**.

**Живое приложение:** [https://habit-tracker-artem.amvera.io](https://habit-tracker-artem.amvera.io) *(без VPN)*

## 🧠 Двухуровневый интеллект
1. **NLP-модуль на базе LLM** (по умолчанию Amvera LLM Inference, OpenAI-совместимый API) —
   разбирает неотструктурированный текст из чата: эмоциональный контекст + структурированные
   действия над привычками (`add_habit`, `reduce_habit`, `delete_habit`) в строгом JSON.
2. **Локальный rule-based fallback** (`llm.py`) — работает без API-ключа: те же сценарии
   по регулярным выражениям (используется в автотестах и при недоступности LLM).

## 🛠 Стек
* **Frontend:** React 19 + Vite + Tailwind CSS 4 (PWA: manifest, standalone, тема)
* **Backend:** Python 3.11, FastAPI, Uvicorn
* **ML/AI:** Amvera LLM Inference / любой OpenAI-совместимый API
* **Database:** SQLite (`habits`, `habit_logs`, `chat_messages`) в постоянном хранилище `/data`
* **DevOps:** Docker (2-stage: node для фронта + python для бэка), Amvera Cloud (CI/CD по push)

## 📌 Особенности
* Прогресс по дням хранится в БД → серия 🔥, отставание «−7», кольцо прогресса в ленте дат.
* Снижение планки меняет только `target` — счётчик дня и история не сбрасываются.
* Чат сохраняет историю диалога; в ответах приходят «чипы» применённых действий.
* Статика PWA раздаётся самим FastAPI (единый сервис).

## ⚙️ API
| Метод | Маршрут | Что делает |
|---|---|---|
| GET | `/api/habits` | привычки с прогрессом за сегодня |
| POST | `/api/habits` | создать привычку (форма «Новая привычка») |
| POST | `/api/habits/{id}/increment` | клик «+» |
| POST | `/api/habits/{id}/complete` | отметить день выполненным |
| POST | `/api/habits/{id}/set-target` | изменить план (прогресс сохраняется) |
| DELETE | `/api/habits/{id}` | удалить привычку (последняя в категории → категория исчезает) |
| DELETE | `/api/categories/{категория}` | удалить категорию со всеми её привычками |
| POST | `/api/chat` | «вылить душу»: текст → действия над привычками |
| GET | `/api/chat/history` | история диалога |

## 🔑 Переменные окружения LLM
| Переменная | По умолчанию | Описание |
|---|---|---|
| `LLM_API_KEY` | *(нет)* | токен из ЛК Amvera (раздел LLM). Если не задан — работает fallback |
| `LLM_BASE_URL` | `https://inference.waw0.amvera.ru/v1` | любой OpenAI-совместимый API |
| `LLM_MODEL` | `gpt-4.1` | например `gpt-4.1`, `gpt-5`, `llama70b`, `qwen3_235b` |
| `LLM_TIMEOUT` | `60` | таймаут запроса к LLM, сек |

Задать переменные на Amvera: **Конфигурация → Переменные окружения** приложения.

## 💻 Локальный запуск
```bash
# backend (из корня репозитория)
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m uvicorn main:app --port 8000        ; или с --reload

# frontend (отдельный терминал, dev-режим с прокси /api → :8000)
cd frontend
npm install
npm run dev
```

## ✅ Тест базового сценария
```bash
.venv\Scripts\python -X utf8 tests\test_chat_module.py
```
Проверяет: чат → «Медитация 10 минут каждый день» появляется в SQLite; «устал — снизь
нагрузку» → план 84→40, прогресс не сброшен; клики «+»/галочка; история чата в БД.

## 🚀 Деплой
Окружение Amvera — **python**, инструмент — **pip**. Фронтенд собирается локально и
коммитится в git (`frontend/dist`), Amvera его не пересобирает — uvicorn раздаёт статику
и API одним процессом. `amvera.yml` задаёт запуск
`uvicorn main:app --host 0.0.0.0 --port 80`, постоянное хранилище `/data` (там живёт
SQLite) и порт приложения 80.

Перед пушем:
```bash
cd frontend && npm run build && cd ..   # обновить frontend/dist
git add -A && git commit -m "..." 
```

Dockerfile оставлен как запасной вариант: при желании можно переключить проект
на docker-окружение (meta.environment в `amvera.yml`).
