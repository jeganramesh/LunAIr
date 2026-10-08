.PHONY: help up down logs build test lint fmt clean

help:
	@echo "make up      - start all services"
	@echo "make down    - stop all services"
	@echo "make logs    - tail logs"
	@echo "make build   - rebuild images"
	@echo "make test    - run all tests"
	@echo "make lint    - lint all services"
	@echo "make fmt     - format all services"
	@echo "make clean   - remove volumes"

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

build:
	docker compose build

test:
	cd app && pytest
	cd gateway && go test ./...

lint:
	cd app && ruff check .
	cd gateway && golangci-lint run

fmt:
	cd app && ruff format .
	cd gateway && gofmt -w .

clean:
	docker compose down -v
