# ЭТАП 1: Сборка React-фронтенда
FROM node:20-alpine AS build-frontend
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# ЭТАП 2: Запуск FastAPI + раздача собранной статики
FROM python:3.11-slim
WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
COPY --from=build-frontend /app/frontend/dist /app/frontend/dist

EXPOSE 8000
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]