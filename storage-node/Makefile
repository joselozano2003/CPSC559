# .PHONY: migrate
# migrate: ## Updates and cleans up dependencies.
# 	docker-compose exec web python manage.py migrate

.PHONY: up
up:
	docker compose -p node1 -f docker-compose.yml up --build -d                                                                                        
	docker compose -p node2 -f docker-compose.node2.yml up --build -d                                                                                  
	docker compose -p node3 -f docker-compose.node3.yml up --build -d                                                                                  
	docker compose -p node4 -f docker-compose.node4.yml up --build -d                                                                                  
	docker compose -p node5 -f docker-compose.node5.yml up --build -d 

.PHONY: down
down:
	docker compose -p node1 -f docker-compose.yml down
	docker compose -p node2 -f docker-compose.node2.yml down
	docker compose -p node3 -f docker-compose.node3.yml down
	docker compose -p node4 -f docker-compose.node4.yml down
	docker compose -p node5 -f docker-compose.node5.yml down

