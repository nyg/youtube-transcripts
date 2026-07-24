.PHONY: install backend frontend start stop restart status logs

# Logs and PID files are XDG state: $XDG_STATE_HOME/yt-summarizer, i.e.
# ~/.local/state/yt-summarizer by default — never inside the checkout.
# $XDG_RUNTIME_DIR is where the spec puts PID files, but it is wiped when your
# last session ends, and `make start` exists precisely to survive logging out of
# an SSH session, so the PID files stay next to the logs.
STATE_DIR := $(if $(XDG_STATE_HOME),$(XDG_STATE_HOME),$(HOME)/.local/state)/yt-summarizer
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
# you log out. PIDs and logs live in the XDG state dir (see STATE_DIR above,
# `make logs` tails them). No --reload (meant for an
# always-on box like a Raspberry Pi) and a single uvicorn worker so exactly one
# monitor scheduler runs. Servers bind to 0.0.0.0 so you can reach them from
# other machines on your LAN (use the box's IP, e.g. http://192.168.x.y:$(FRONTEND_PORT)).
# To restrict to this machine only, run: make start HOST=127.0.0.1
start: start-backend start-frontend
	@echo "Backend  -> http://$(HOST):$(BACKEND_PORT)   (log: $(STATE_DIR)/backend.log)"
	@echo "Frontend -> http://$(HOST):$(FRONTEND_PORT)   (log: $(STATE_DIR)/frontend.log)"
	@echo "On your LAN, browse to http://<this-machine-ip>:$(FRONTEND_PORT)"
	@echo "Manage with: make status | make logs | make stop"

start-backend:
	@mkdir -p $(STATE_DIR)
	@if [ -f $(STATE_DIR)/backend.pid ] && kill -0 `cat $(STATE_DIR)/backend.pid` 2>/dev/null; then \
		echo "backend already running (PID `cat $(STATE_DIR)/backend.pid`)"; \
	else \
		( cd backend && exec nohup ../.venv/bin/uvicorn app.main:app --host $(HOST) --port $(BACKEND_PORT) ) > $(STATE_DIR)/backend.log 2>&1 & \
		echo $$! > $(STATE_DIR)/backend.pid; \
		echo "backend started (PID `cat $(STATE_DIR)/backend.pid`)"; \
	fi

start-frontend:
	@mkdir -p $(STATE_DIR)
	@if [ -f $(STATE_DIR)/frontend.pid ] && kill -0 `cat $(STATE_DIR)/frontend.pid` 2>/dev/null; then \
		echo "frontend already running (PID `cat $(STATE_DIR)/frontend.pid`)"; \
	else \
		( cd frontend && exec nohup node_modules/.bin/vite --host $(HOST) --port $(FRONTEND_PORT) ) > $(STATE_DIR)/frontend.log 2>&1 & \
		echo $$! > $(STATE_DIR)/frontend.pid; \
		echo "frontend started (PID `cat $(STATE_DIR)/frontend.pid`)"; \
	fi

stop:
	@for name in backend frontend; do \
		pidfile=$(STATE_DIR)/$$name.pid; \
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
		pidfile=$(STATE_DIR)/$$name.pid; \
		if [ -f $$pidfile ] && kill -0 `cat $$pidfile` 2>/dev/null; then \
			echo "$$name: running (PID `cat $$pidfile`)"; \
		else \
			echo "$$name: stopped"; \
		fi; \
	done

logs:
	@tail -n 50 -F $(STATE_DIR)/backend.log $(STATE_DIR)/frontend.log
