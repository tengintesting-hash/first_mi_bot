# Telegram Casino Offers System

Цей репозиторій містить мінімальний каркас Telegram-бота, WebApp, API та інфраструктури для системи оферів.

## Запуск

1. Створіть `.env` на основі `.env.example`.
2. Запустіть:

```bash
docker compose up -d --build
```

## Сервіси

- `backend`: FastAPI API для авторизації, оферів, рефералів та постбеків.
- `bot`: Telegram-бот для /start, /ref та перевірки підписок.
- `frontend`: статичний WebApp інтерфейс.
- `nginx`: проксі для API та фронтенду.
