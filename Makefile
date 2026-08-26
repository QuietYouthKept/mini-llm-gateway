.PHONY: dev test eval demo replay demo-report security-eval lint verify clean-db clean

PYTHON ?= python

dev:
	$(PYTHON) -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

test:
	$(PYTHON) -m pytest -v

eval:
	$(PYTHON) eval/run_eval.py

security-eval:
	$(PYTHON) eval/run_eval.py --cases eval/security_cases.yaml

demo:
	$(PYTHON) scripts/demo.py

demo-report:
	$(PYTHON) scripts/demo_report.py

replay:
	$(PYTHON) scripts/replay_request.py --request-id $(REQUEST_ID) --mode offline

lint:
	$(PYTHON) -m ruff check .

verify:
	$(PYTHON) scripts/verify.py

clean-db:
	rm -f data/gateway.db

clean:
	rm -rf data/gateway.db __pycache__ .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
