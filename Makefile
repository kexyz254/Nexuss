.PHONY: validate test lint

validate:
	python scripts/validate_repository.py

test:
	python -m pytest tests

lint:
	ruff check .
	mypy services libs scripts
