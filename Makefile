PYTHONNOUSERSITE ?= 1
CONDA_ENV ?= poly_agent
PYTEST_ARGS ?= backend/tests
PYTHONPATH ?= backend
NPM_PREFIX ?= frontend

.PHONY: test-backend test-frontend-build test-lui-eval init-mongo-indexes test-e2e check-all
test-backend:
	AUTH_ENABLED=false PYTHONNOUSERSITE=$(PYTHONNOUSERSITE) PYTHONPATH=$(PYTHONPATH) conda run -n $(CONDA_ENV) python -m pytest $(PYTEST_ARGS)

test-frontend-build:
	npm --prefix $(NPM_PREFIX) run build

test-lui-eval:
	PYTHONNOUSERSITE=$(PYTHONNOUSERSITE) PYTHONPATH=$(PYTHONPATH) conda run -n $(CONDA_ENV) python scripts/run_lui_eval.py \
		--dataset backend/evaluation/lui/dataset --mode smoke \
		--report-dir backend/evaluation/lui/reports \
		--manual-review backend/evaluation/lui/baselines/manual-review-2026.08.28.json \
		--check-baseline backend/evaluation/lui/baselines/smoke-2026.08.28.json

init-mongo-indexes:
	PYTHONNOUSERSITE=$(PYTHONNOUSERSITE) PYTHONPATH=$(PYTHONPATH) conda run -n $(CONDA_ENV) python scripts/init_mongo_indexes.py

test-e2e:
	PYTHONNOUSERSITE=$(PYTHONNOUSERSITE) conda run -n $(CONDA_ENV) python e2e/dialogue_e2e.py
	PYTHONNOUSERSITE=$(PYTHONNOUSERSITE) conda run -n $(CONDA_ENV) python e2e/capability_admin_e2e.py

check-all: test-backend test-frontend-build test-lui-eval test-e2e
