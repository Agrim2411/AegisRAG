.PHONY: install test smoke eval demo simulate lint

install:
	python3 -m pip install -e '.[dev]'

test:
	python3 -m pytest

lint:
	python3 -m ruff check src tests

eval:
	python3 -m aegis_rag eval --dataset data/eval/golden.jsonl

demo:
	python3 -m aegis_rag demo

simulate:
	python3 -m aegis_rag simulate --scenario payments-pool-exhaustion --tenant acme-payments

smoke:
	./scripts/smoke.sh
