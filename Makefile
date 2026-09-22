.PHONY: install test run worker doctor migrate

install:
	python -m pip install -r requirements.txt

test:
	python -m pytest -q --basetemp=.pytest-run

run:
	python run.py

worker:
	python -m scheduler.cli worker

doctor:
	python -m scheduler.cli doctor

migrate:
	python -m scheduler.cli migrate
