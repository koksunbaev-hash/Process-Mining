# Запуск без путаницы со старыми сборками

1. Удали старую папку проекта полностью.
2. Распакуй этот архив в новую папку.
3. Открой PowerShell именно в папке, где лежат `docker-compose.yml` и `Dockerfile`.
4. Выполни:

```powershell
Copy-Item .env.example .env
notepad .env
# для локального запуска можно оставить PM_API_KEYS пустым

docker compose down --remove-orphans
docker compose up -d --build
```

5. Проверь:

```powershell
Invoke-WebRequest http://localhost:8000/health/live
Start-Process http://localhost:8000/
```

Если видишь старый экран, значит запущена старая папка или старый контейнер. Выполни
`docker compose down --remove-orphans`, удали старую папку, затем повтори сборку.
