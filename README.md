# 🎯 FastAPI Habit Tracker

Простой и быстрый трекер привычек, разработанный на Python с использованием FastAPI. Приложение оптимизировано для использования на мобильных устройствах (iOS/Safari) в качестве PWA и развёрнуто в облачной инфраструктуре.

## 🚀 Демо
* **Живое приложение:** [https://habit-tracker-artem.amvera.io](https://habit-tracker-artem.amvera.io) *(без необходимости использовать VPN)*

## 🛠 Технологический стек
* **Backend:** Python 3.11, FastAPI, Uvicorn
* **Database:** SQLite (с хранением данных в `/data` для сохранения между перезапусками контейнера)
* **DevOps & Deploy:** Docker, Amvera Cloud Platform
* **VCS:** Git, GitHub

## 📌 Ключевые особенности
* **Асинхронный бэкенд:** Высокая скорость обработки запросов благодаря FastAPI.
* **Сохранение состояния:** Использование Docker volume (`/data`) гарантирует целостность базы данных при пересборке и перезапуске контейнеров.
* **Контейнеризация:** Изолированная сборка через `Dockerfile` на базе `python:3.11-slim`.
* **Mobile-First UX:** Удобный доступ с мобильных устройств через Safari.

## ⚙️ Локальный запуск

1. **Клонируйте репозиторий:**
   ```bash
   git clone [https://github.com/artemhashig/habit-tracker.git](https://github.com/artemhashig/habit-tracker.git)
   cd habit-tracker