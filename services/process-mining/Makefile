.PHONY: install run dev test lint fmt docker up down smoke

install:
	pip install -r requirements-dev.txt

run:
	uvicorn app.main:app --host 0.0.0.0 --port 8000

dev:
	uvicorn app.main:app --reload --port 8000

test:
	pytest -q

lint:
	ruff check app tests

fmt:
	ruff format app tests

docker:
	docker build -t process-mining-service:1.0.0 .

up:
	docker compose up -d --build

down:
	docker compose down

smoke:
	python clients/python/pm_client.py --base-url http://localhost:8000 --api-key dev-key-change-me --file examples/sample_log.csv
