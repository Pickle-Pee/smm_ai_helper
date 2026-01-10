# SMM AI Helper

## Запуск

```bash
docker-compose up --build
```

## Чат-ассистент

### Пример запроса

```bash
curl -X POST http://localhost:8000/chat/message \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "tg:123",
    "text": "Нужен контент-план для телеграм-канала про финансы для подростков",
    "attachments": []
  }'
```

### Пример запроса со ссылкой

```bash
curl -X POST http://localhost:8000/chat/message \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "tg:123",
    "text": "Посмотри сайт https://example.com и предложи, как улучшить первый экран",
    "attachments": []
  }'
```
