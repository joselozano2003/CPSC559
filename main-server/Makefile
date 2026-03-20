.PHONY: migrations
migrations: ## Updates and cleans up dependencies.
	docker-compose exec main-server python manage.py makemigrations

.PHONY: migrate
migrate: ## Updates and cleans up dependencies.
	docker-compose exec main-server python manage.py migrate

.PHONY: up
up:
	docker-compose up -d --build 


.PHONY: down
down:
	docker-compose down

.PHONY: downv
downv:
	docker-compose down -v