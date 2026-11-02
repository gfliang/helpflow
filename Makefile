.PHONY: infra-up infra-down infra-obs api web migrate seed reindex eval test

infra-up:
	docker compose up -d postgres redis

infra-down:
	docker compose down

infra-obs:
	docker compose --profile observability up -d

api:
	cd backend && uv run uvicorn app.main:app --reload --port 8000

web:
	cd frontend && npm run dev

migrate:
	cd backend && uv run alembic upgrade head

seed:
	cd backend && uv run python -m app.seed

reindex:
	cd backend && uv run python -m app.tasks.reindex

eval:
	cd backend && uv run python -m evals.run_eval --workspace helpflow

test:
	cd backend && uv run pytest
