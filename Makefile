PYTHON_EXECUTABLE ?= python3.15
.PHONY: install test run worker doctor migrate

install:
	@test ! -d .venv || .venv/bin/python -I -c "import sys; assert sys.version_info[:3]==(3,15,1), 'Preserve the existing environment before upgrading'"
	$(PYTHON_EXECUTABLE) tools/prepare_sqlite_runtime.py
	@test -d .venv || $(PYTHON_EXECUTABLE) -m venv .venv
	.venv/bin/python -m pip install --require-hashes -r requirements.lock

test run worker doctor migrate:
	$(PYTHON_EXECUTABLE) tools/run_local.py $@
