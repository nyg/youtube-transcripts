.PHONY: install backend frontend

install:
	python3 -m venv .venv
	.venv/bin/pip install -r backend/requirements.txt
	cd frontend && npm install

backend:
	cd backend && ../.venv/bin/uvicorn app.main:app --reload --port 8000

frontend:
	cd frontend && npm run dev
