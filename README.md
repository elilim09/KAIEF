# Software FUTURE & DREAM Challenge 2025

## Docker

```bash
cp .env.example .env
docker compose up -d --build
```

Open `http://localhost:8000`.

Useful `.env` options:

- `HOST_PORT=8000`: host port to expose.
- `STARTUP_CRAWL=false`: start quickly from bundled `events.json`.
- `BUILD_VECTOR_ON_REFRESH=false`: skip OpenAI embedding build on startup/refresh.
- `DAILY_REFRESH_ENABLED=true`: run the daily refresh scheduler.
- `SCHEDULED_CRAWL=true`: crawl fresh data during scheduled refreshes.
