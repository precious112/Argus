.PHONY: help dev dev-docker stop install lint type-check test test-agent test-web clean build

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# --- Development ---

install: ## Install all dependencies
	cd packages/agent && uv pip install -e ".[dev,all-providers]"
	cd packages/cli && uv pip install -e ".[dev]"
	cd packages/web && npm install
	cd packages/sdk-node && npm install

dev: ## Start agent server with hot-reload (local)
	cd packages/agent && uvicorn argus_agent.main:app --reload --reload-dir src --host 0.0.0.0 --port 7600

dev-web: ## Start Next.js dev server
	cd packages/web && npm run dev

dev-docker: ## Start everything with Docker (dev mode)
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build

stop: ## Stop Docker services
	docker compose down

# --- Quality ---

lint: ## Run linters
	cd packages/agent && ruff check src/ tests/
	cd packages/agent && ruff format --check src/ tests/

format: ## Auto-format code
	cd packages/agent && ruff check --fix src/ tests/
	cd packages/agent && ruff format src/ tests/

type-check: ## Run type checkers
	cd packages/agent && mypy src/argus_agent/
	cd packages/web && npm run type-check

# --- Testing ---

test: test-agent ## Run all tests

test-agent: ## Run agent tests
	cd packages/agent && python -m pytest tests/ -v

test-cov: ## Run tests with coverage
	cd packages/agent && python -m pytest tests/ -v --cov=argus_agent --cov-report=html

# --- Build ---

build: ## Build production Docker image
	docker compose build argus

build-web: ## Build web UI
	cd packages/web && npm run build

# --- Cleanup ---

clean: ## Clean build artifacts
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name node_modules -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .next -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name dist -exec rm -rf {} + 2>/dev/null || true
