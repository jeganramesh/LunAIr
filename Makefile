.PHONY: help up up-go up-all down logs build test test-app test-gateway lint fmt fmt-app fmt-gateway clean

PY      := app/.venv/bin/python
GO_DOCKER  := docker run --rm -v $(PWD)/gateway:/src -v lunair-gomodcache:/go/pkg/mod -w /src golang:1.22-alpine
GO_IMAGE  := golang:1.22-alpine
GOLANGCI  := golangci/golangci-lint:v1.61-alpine

help:
	@echo "make up             - start services without the Go gateway (fastapi_only)"
	@echo "make up-go          - start gateway + fastapi"
	@echo "make up-all         - start everything including the dashboard"
	@echo "make down           - stop all services"
	@echo "make logs           - tail logs"
	@echo "make build          - rebuild images"
	@echo "make test           - run all tests"
	@echo "make test-app       - run python tests (needs app/.venv)"
	@echo "make test-gateway   - run go tests in Docker"
	@echo "make lint           - lint all services"
	@echo "make fmt            - format all services"
	@echo "make clean          - remove volumes"

up:
	docker compose up -d

up-go:
	docker compose --profile gateway up -d

# The dashboard is gated on the gateway, so both profiles are required.
up-all:
	docker compose --profile gateway --profile dashboard up -d

down:
	docker compose down

logs:
	docker compose logs -f

build:
	docker compose build

test: test-app test-gateway

test-app:
	$(PY) -m pytest tests/unit

# Host Go is often older than the gateway's go.mod requirement, so Go tooling
# runs in a pinned container instead.
test-gateway:
	$(GO_DOCKER) go test ./...

lint:
	$(PY) -m ruff check app
	$(GO_DOCKER) sh -c "gofmt -l . | grep . && exit 1 || echo 'gofmt: clean'"

fmt: fmt-app fmt-gateway

fmt-app:
	$(PY) -m ruff format app tests

fmt-gateway:
	$(GO_DOCKER) gofmt -w .

clean:
	docker compose down -v