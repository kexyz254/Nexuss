.PHONY: validate test lint security run run-p4 stop-p4 run-p5 stop-p5

validate:
	python scripts/validate_repository.py

test:
	python -m pytest tests

lint:
	ruff check .
	mypy src services libs scripts

security:
	bandit -q -r src services libs scripts

run:
	uvicorn nexuss.api.app:app --host 127.0.0.1 --port 8100 --reload

run-p4:
	powershell.exe -ExecutionPolicy Bypass -File .\scripts\start_p4.ps1

stop-p4:
	powershell.exe -ExecutionPolicy Bypass -File .\scripts\stop_p4.ps1

run-p5:
	powershell.exe -ExecutionPolicy Bypass -File .\scripts\start_p5.ps1

stop-p5:
	powershell.exe -ExecutionPolicy Bypass -File .\scripts\stop_p5.ps1
