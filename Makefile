# polycr Makefile
# Why: Provides short, memorable aliases for the most common Docker Compose
#      and testing workflows so contributors don't need to memorise long commands.

.PHONY: up up-gpu up-full up-minimal down test logs build push-ghcr

COMPOSE      := docker compose
COMPOSE_FILE := -f docker-compose.yml

## up — Start the default stack (router + tesseract + easyocr + doctr)
up:
	$(COMPOSE) $(COMPOSE_FILE) up -d

## up-gpu — Start the default stack with GPU acceleration
up-gpu:
	$(COMPOSE) $(COMPOSE_FILE) -f docker-compose.gpu.yml up -d

## up-full — Start all engines including paddleocr and surya (profile=full)
up-full:
	$(COMPOSE) $(COMPOSE_FILE) --profile full up -d

## up-minimal — Start minimal stack (router + tesseract only)
up-minimal:
	$(COMPOSE) -f docker-compose.minimal.yml up -d

## down — Stop and remove all containers and networks
down:
	$(COMPOSE) $(COMPOSE_FILE) --profile full down

## build — Build all images without starting containers
build:
	$(COMPOSE) $(COMPOSE_FILE) --profile full build

## logs — Tail logs from all running services
logs:
	$(COMPOSE) $(COMPOSE_FILE) logs -f

## test — Run the integration test suite against a running minimal stack
test:
	@echo "Starting minimal stack for tests..."
	$(COMPOSE) -f docker-compose.minimal.yml up -d
	@echo "Waiting for services to be healthy..."
	sleep 20
	python3 tests/test_pipeline.py
	$(COMPOSE) -f docker-compose.minimal.yml down

## push-ghcr — Build and push all images to GitHub Container Registry
## Requires: GHCR_USERNAME env var and prior `docker login ghcr.io`
push-ghcr:
	@if [ -z "$(GHCR_USERNAME)" ]; then \
		echo "Error: GHCR_USERNAME is not set"; exit 1; \
	fi
	$(COMPOSE) $(COMPOSE_FILE) --profile full build
	for svc in router tesseract easyocr doctr paddleocr surya; do \
		docker tag polycr-$$svc ghcr.io/$(GHCR_USERNAME)/polycr-$$svc:latest && \
		docker push ghcr.io/$(GHCR_USERNAME)/polycr-$$svc:latest; \
	done
