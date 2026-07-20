.PHONY: install backend frontend start stop restart status logs

RUN_DIR := .run
HOST ?= 0.0.0.0
BACKEND_PORT ?= 8000
FRONTEND_PORT ?= 5173

install:
	python3 -m venv .venv
	.venv/bin/pip install -r backend/requirements.txt
	cd frontend && npm install

# --- Foreground (development, auto-reload; tied to the terminal) --------------
backend:
	cd backend && ../.venv/bin/uvicorn app.main:app --reload --port 8000

frontend:
	cd frontend && npm run dev

# --- Background (detached; survives closing the terminal / SSH session) -------
# Both servers are launched with nohup and detached, so they keep running after
# you log out. PIDs and logs live in $(RUN_DIR)/. No --reload (meant for an
# always-on box like a Raspberry Pi) and a single uvicorn worker so exactly one
# monitor scheduler runs. Servers bind to 0.0.0.0 so you can reach them from
# other machines on your LAN (use the box's IP, e.g. http://192.168.x.y:$(FRONTEND_PORT)).
# To restrict to this machine only, run: make start HOST=127.0.0.1
start: start-backend start-frontend
	@echo "Backend  -> http://$(HOST):$(BACKEND_PORT)   (log: $(RUN_DIR)/backend.log)"
	@echo "Frontend -> http://$(HOST):$(FRONTEND_PORT)   (log: $(RUN_DIR)/frontend.log)"
	@echo "On your LAN, browse to http://<this-machine-ip>:$(FRONTEND_PORT)"
	@echo "Manage with: make status | make logs | make stop"

start-backend:
	@mkdir -p $(RUN_DIR)
	@if [ -f $(RUN_DIR)/backend.pid ] && kill -0 `cat $(RUN_DIR)/backend.pid` 2>/dev/null; then \
		echo "backend already running (PID `cat $(RUN_DIR)/backend.pid`)"; \
	else \
		( cd backend && exec nohup ../.venv/bin/uvicorn app.main:app --host $(HOST) --port $(BACKEND_PORT) ) > $(RUN_DIR)/backend.log 2>&1 & \
		echo $$! > $(RUN_DIR)/backend.pid; \
		echo "backend started (PID `cat $(RUN_DIR)/backend.pid`)"; \
	fi

start-frontend:
	@mkdir -p $(RUN_DIR)
	@if [ -f $(RUN_DIR)/frontend.pid ] && kill -0 `cat $(RUN_DIR)/frontend.pid` 2>/dev/null; then \
		echo "frontend already running (PID `cat $(RUN_DIR)/frontend.pid`)"; \
	else \
		( cd frontend && exec nohup node_modules/.bin/vite --host $(HOST) --port $(FRONTEND_PORT) ) > $(RUN_DIR)/frontend.log 2>&1 & \
		echo $$! > $(RUN_DIR)/frontend.pid; \
		echo "frontend started (PID `cat $(RUN_DIR)/frontend.pid`)"; \
	fi

stop:
	@for name in backend frontend; do \
		pidfile=$(RUN_DIR)/$$name.pid; \
		if [ -f $$pidfile ] && kill -0 `cat $$pidfile` 2>/dev/null; then \
			kill `cat $$pidfile` && echo "stopped $$name (PID `cat $$pidfile`)"; \
		else \
			echo "$$name not running"; \
		fi; \
		rm -f $$pidfile; \
	done

restart:
	@$(MAKE) stop
	@$(MAKE) start

status:
	@for name in backend frontend; do \
		pidfile=$(RUN_DIR)/$$name.pid; \
		if [ -f $$pidfile ] && kill -0 `cat $$pidfile` 2>/dev/null; then \
			echo "$$name: running (PID `cat $$pidfile`)"; \
		else \
			echo "$$name: stopped"; \
		fi; \
	done

logs:
	@tail -n 50 -F $(RUN_DIR)/backend.log $(RUN_DIR)/frontend.log
