DEFAULT_GOAL := help


.PHONY: install
install: ## Install dependencies
	poetry install

.PHONY: run
run: ## Run the AWS cost notifier script
	poetry run python main.py

help: ## Show help message
	@grep -h -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'

guard-%:
	@ if [ "${${*}}" = "" ]; then \
		echo "Environment variable $* not set"; \
		exit 1; \
	fi
