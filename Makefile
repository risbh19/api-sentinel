API := apps/api
.PHONY: setup check serve smoke

setup:
	cd $(API) && uv sync --locked

check:
	cd $(API) && uv run --locked ruff format --check src tests
	cd $(API) && uv run --locked ruff check src tests
	cd $(API) && uv run --locked mypy
	cd $(API) && PYTHONPATH=src uv run --locked python -m unittest discover -s tests -v

serve:
	cd $(API) && uv run --locked uvicorn api_sentinel.main:app --app-dir src --host 127.0.0.1 --port 8000 --no-access-log --no-server-header --no-proxy-headers

smoke:
	bash scripts/compose-smoke.sh
