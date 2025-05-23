DEFAULT_GOAL := help


.PHONY: install
install: ## Install dependencies
	poetry install

.PHONY: run
run: ## Run the AWS cost notifier script
	poetry run python main.py

.PHONY: lint
lint: ## Run linter
	poetry run flake8 .

.PHONY: format
format: ## Run formatter
	poetry run black .

.PHONY: update-template
update-template: ## Update the lambda function code in template.yaml with main.py content
	@echo "template.yaml 内の Lambda 関数コードを更新中..."
	@# main.py の中から `if __name__ == "__main__":` とその下の行を除く
	@sed '/^if __name__ == "__main__":/,$$d' main.py > code_without_main.txt
	@awk 'BEGIN {in_code_section=0;} /^ *Code:$$/ {print; getline; print "        ZipFile: |"; getline; while ((getline line < "code_without_main.txt") > 0) print "          " line; in_code_section=1; next} in_code_section && /^[ ]{2}[a-zA-Z]/ {in_code_section=0} {if (!in_code_section) print}' template.yaml > temp.yaml
	@mv temp.yaml template.yaml
	@rm code_without_main.txt
	@echo "Lambda 関数コードが更新されました。"


help: ## Show help message
	@grep -h -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'
