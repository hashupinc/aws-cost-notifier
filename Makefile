DEFAULT_GOAL := help

USE_DEFAULT_AWS_PROFILE := 0

TARGET_ENV := dev

AWS_PROFILE := rakutan-$(TARGET_ENV)

ifeq ($(USE_DEFAULT_AWS_PROFILE), 1)
	AWS_CMD_VARS := $(shell  echo "AWS_REGION=ap-northeast-1")
else
	AWS_CMD_VARS := $(shell  echo "AWS_PROFILE=$(AWS_PROFILE) AWS_REGION=ap-northeast-1")
endif

AWS := aws


.PHONY: install
install: ## Install dependencies
	poetry install


.PHONY: get-aws-cost
get-aws-cost: ## Run the AWS cost notifier script
	$(AWS_CMD_VARS) poetry run python main.py



help: ## Show help message
	@grep -h -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'

guard-%:
	@ if [ "${${*}}" = "" ]; then \
		echo "Environment variable $* not set"; \
		exit 1; \
	fi
