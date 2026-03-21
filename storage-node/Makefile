# .PHONY: migrate
# migrate: ## Updates and cleans up dependencies.
# 	docker-compose exec web python manage.py migrate

.PHONY: up
up:
	docker compose -f docker-compose.yml -f docker-compose.node2.yml up -d --build

.PHONY: down
down:
	docker compose -f docker-compose.yml -f docker-compose.node2.yml down

.PHONY: downv
downv:
	docker compose -f docker-compose.yml -f docker-compose.node2.yml down -v
