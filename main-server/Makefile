.PHONY: migrate
migrate: ## Updates and cleans up dependencies.
	docker-compose exec web python manage.py migrate

.PHONY: up
up:
	docker-compose up -d --build 


.PHONY: down
down:
	docker-compose down