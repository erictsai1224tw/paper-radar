.PHONY: build up down terminal logs format lint lock clean \
        worktree worktree-rm worktree-list help

# ── Docker container targets ─────────────────────────────────
build: ## Build the image (deps 有變更時重建)
	@echo "Building image..."
	docker compose build app

up: ## Start the app container
	docker compose up -d app

down: ## Stop the app container
	docker compose stop app

terminal: ## Enter the app container terminal
	docker compose exec -it app /bin/bash

logs: ## View the app container logs
	docker compose logs -f app

format: ## Format code inside the app container
	docker compose exec -it app ruff format .

lint: ## Lint code inside the app container
	docker compose exec -it app ruff check . --fix

lock: ## Update uv.lock
	@echo "Updating uv.lock..."
	docker compose run --rm app uv lock

clean: ## Clean up all Docker resources
	@echo "Cleaning up..."
	docker compose down -v --remove-orphans

# ── Project-specific targets go here ─────────────────────────
# Example: forward to a sub-Makefile for your app's commands
# demo-%: ## Run a demo inside container
#	@$(MAKE) --no-print-directory -C src/<your_pkg> $* $(if $(provider),provider=$(provider))

# ── Worktree helpers ─────────────────────────────────────────
worktree: ## Create a parallel worktree: make worktree name=feat-xxx
	@if [ -z "$(name)" ]; then echo "Usage: make worktree name=<branch-name>"; exit 1; fi
	git worktree add ../$(name) -b feat/$(name)
	@if [ -f .env ]; then ln -sf "$$(pwd)/.env" "../$(name)/.env" && echo "Linked .env"; fi
	@echo "✅ Worktree created at ../$(name)"

worktree-rm: ## Remove a worktree: make worktree-rm name=feat-xxx
	@if [ -z "$(name)" ]; then echo "Usage: make worktree-rm name=<branch-name>"; exit 1; fi
	git worktree remove ../$(name)
	-git branch -D feat/$(name)
	@echo "✅ Worktree removed: ../$(name)"

worktree-list: ## List all worktrees
	git worktree list

# - Database Related
database-clean: ## Clean database
	python -c "import sqlite3; sqlite3.connect('db.sqlite').execute('DELETE FROM seen').connection.commit()"

database-test: ## test send out a message
	python radar.py 

# ── Help ─────────────────────────────────────────────────────
help: ## Display this help message
	@echo "Usage: make [target]"
	@echo ""
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z0-9_-]+:.*?## / {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo ""
	@echo "💡 提示："
	@echo "  • 首次使用請先跑 ./bootstrap.sh"
	@echo "  • Worktree: make worktree name=<feature-name>"
