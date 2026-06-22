.PHONY: dev test clean-db clean

dev:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

test:
	pytest -v

clean-db:
	rm -f data/gateway.db

clean:
	rm -rf data/gateway.db __pycache__ .pytest_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
