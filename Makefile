.PHONY: up down build demo test test-unit logs health clean train help

up:             ## Start all services
	docker compose up -d

down:           ## Stop all services
	docker compose down

build:          ## Rebuild and start all services
	docker compose up --build -d

demo:           ## Run the end-to-end demo script
	python3 scripts/demo.py

test:           ## Run all tests (services must be running)
	pytest tests/ -v

test-unit:      ## Run unit tests only (no Docker needed)
	pytest tests/test_denial_model.py tests/test_unit_services.py -v

logs:           ## Tail logs from all services
	docker compose logs -f --tail=50

health:         ## Check system health
	@curl -s http://localhost:8000/health | python3 -m json.tool

clean:          ## Stop services and delete all data
	docker compose down -v

train:          ## Train the ML denial prediction model
	python3 ml/train_model.py

help:           ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
