.PHONY: install backend frontend build install-service uninstall-service start stop restart status logs

SERVICE := yt-summarizer
UNIT_DIR := $(if $(XDG_CONFIG_HOME),$(XDG_CONFIG_HOME),$(HOME)/.config)/systemd/user
# 0.0.0.0 makes the app reachable from the LAN; HOST=127.0.0.1 keeps it on this machine.
HOST ?= 0.0.0.0
PORT ?= 8642
PYTHON ?= $(shell pyenv which python3 2>/dev/null)

install:
	$(if $(PYTHON),,$(error pyenv not found: run from a login shell, or pass PYTHON=/path/to/python3))
	$(PYTHON) -m venv --clear .venv
	.venv/bin/pip install -r backend/requirements.txt
	cd frontend && pnpm install

# --- Development (auto-reload, tied to the terminal) --------------------------
backend:
	cd backend && ../.venv/bin/uvicorn app.main:app --reload --port $(PORT)

frontend:
	cd frontend && BACKEND_PORT=$(PORT) pnpm run dev

# --- Always-on (systemd user service, Linux) -----------------------------------
build:
	cd frontend && pnpm run build

install-service: build
	mkdir -p $(UNIT_DIR)
	sed -e 's|@CHECKOUT@|$(CURDIR)|g' -e 's|@HOST@|$(HOST)|g' -e 's|@PORT@|$(PORT)|g' \
		deploy/$(SERVICE).service > $(UNIT_DIR)/$(SERVICE).service
	systemctl --user daemon-reload
	systemctl --user enable $(SERVICE)
	systemctl --user restart $(SERVICE)
	loginctl enable-linger

uninstall-service:
	systemctl --user disable --now $(SERVICE)
	rm -f $(UNIT_DIR)/$(SERVICE).service
	systemctl --user daemon-reload

start stop restart:
	systemctl --user $@ $(SERVICE)

status:
	-systemctl --user status $(SERVICE)

logs:
	journalctl --user -u $(SERVICE) -f
