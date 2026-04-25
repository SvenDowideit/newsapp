.PHONY: help backend-install models dev run test lint clean \
        android-deps android-run android-apk android-install \
        docker-build docker-run install-systemd

BACKEND_DIR   := backend
ANDROID_DIR   := android
VENV          := $(BACKEND_DIR)/venv
PYTHON        := $(VENV)/bin/python
PIP           := $(VENV)/bin/pip
UVICORN       := $(VENV)/bin/uvicorn
DATA_DIR      := data
APK_OUT       := newsapp.apk
DOCKER_IMAGE  := newsagg

# ── Help ─────────────────────────────────────────────────────────────────────

help:
	@echo ""
	@echo "newsagg — Personal News Aggregator"
	@echo ""
	@echo "Backend:"
	@echo "  make backend-install   Create venv and install Python deps"
	@echo "  make models            Pull required Ollama models"
	@echo "  make dev               Run backend with auto-reload on :8000"
	@echo "  make run               Run backend in production mode"
	@echo "  make test              Run Python test suite"
	@echo "  make lint              Run ruff linter"
	@echo ""
	@echo "Android:"
	@echo "  make android-deps      Download Go module dependencies"
	@echo "  make android-run       Run app on Linux desktop (preview)"
	@echo "  make android-apk       Build $(APK_OUT) via Drift CLI"
	@echo "  make android-install   adb install $(APK_OUT)"
	@echo ""
	@echo "Deployment:"
	@echo "  make docker-build      Build Docker image ($(DOCKER_IMAGE))"
	@echo "  make docker-run        Run backend in Docker on :8000"
	@echo "  make install-systemd   Copy newsagg.service to /etc/systemd/system/"
	@echo ""
	@echo "Maintenance:"
	@echo "  make clean             Remove venv, caches, *.duckdb"
	@echo ""

# ── Backend ──────────────────────────────────────────────────────────────────

$(VENV)/bin/activate: $(BACKEND_DIR)/pyproject.toml
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e "$(BACKEND_DIR)[dev]"
	@touch $(VENV)/bin/activate

backend-install: $(VENV)/bin/activate

models:
	ollama pull mistral
	ollama pull nomic-embed-text

dev: backend-install
	cd $(BACKEND_DIR) && ../$(UVICORN) newsagg.main:app \
		--reload --host 0.0.0.0 --port 8000

run: backend-install
	cd $(BACKEND_DIR) && ../$(UVICORN) newsagg.main:app \
		--host 0.0.0.0 --port 8000 --workers 1

test: backend-install
	cd $(BACKEND_DIR) && ../$(VENV)/bin/pytest tests/ -v

lint: backend-install
	$(VENV)/bin/ruff check $(BACKEND_DIR)/newsagg/ || true

# ── Android ──────────────────────────────────────────────────────────────────

android-deps:
	cd $(ANDROID_DIR) && go mod download

android-run: android-deps
	cd $(ANDROID_DIR) && go run ./cmd/newsapp

android-apk: android-deps
	cd $(ANDROID_DIR) && drift build android -o ../$(APK_OUT)

android-install: $(APK_OUT)
	adb install -r $(APK_OUT)

# ── Docker ───────────────────────────────────────────────────────────────────

docker-build:
	docker build -t $(DOCKER_IMAGE) $(BACKEND_DIR)

docker-run: docker-build
	mkdir -p $(DATA_DIR)
	docker run -d \
		--name newsagg \
		-p 8000:8000 \
		-v "$(CURDIR)/$(DATA_DIR):/data" \
		-v "$(CURDIR)/$(BACKEND_DIR)/config.toml:/app/config.toml:ro" \
		$(DOCKER_IMAGE)
	@echo "Backend running at http://localhost:8000"

# ── Deployment ───────────────────────────────────────────────────────────────

install-systemd:
	sudo cp $(BACKEND_DIR)/newsagg.service /etc/systemd/system/newsagg.service
	sudo systemctl daemon-reload
	@echo "Service installed. Enable with: sudo systemctl enable --now newsagg"
	@echo "View logs with:               sudo journalctl -u newsagg -f"

# ── Maintenance ──────────────────────────────────────────────────────────────

clean:
	rm -rf $(VENV)
	find $(BACKEND_DIR) -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find $(BACKEND_DIR) -name "*.pyc" -delete 2>/dev/null || true
	rm -f *.duckdb $(BACKEND_DIR)/*.duckdb
	rm -f $(APK_OUT)
