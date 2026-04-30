.PHONY: install run run-bot run-dashboard run-loop test lint fmt deploy

install:
	python -m pip install -e '.[dev]'

run:
	python -m mimmy.main run

run-bot:
	python -m mimmy.main bot

run-dashboard:
	python -m mimmy.main dashboard

run-loop:
	python -m mimmy.main loop

test:
	pytest -q

lint:
	ruff check src tests

fmt:
	ruff format src tests

deploy:
	bash deploy/push-and-restart.sh
