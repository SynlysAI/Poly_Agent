PYTHONNOUSERSITE ?= 1
CONDA_ENV ?= poly_agent
PYTEST_ARGS ?= backend/tests
PYTHONPATH ?= backend
NPM_PREFIX ?= frontend

.PHONY: test-backend test-frontend-build init-mongo-indexes test-e2e check-all
test-backend:
	PYTHONNOUSERSITE=$(PYTHONNOUSERSITE) PYTHONPATH=$(PYTHONPATH) conda run -n $(CONDA_ENV) python -m pytest $(PYTEST_ARGS)

test-frontend-build:
	npm --prefix $(NPM_PREFIX) run build

init-mongo-indexes:
	PYTHONNOUSERSITE=$(PYTHONNOUSERSITE) PYTHONPATH=$(PYTHONPATH) conda run -n $(CONDA_ENV) python scripts/init_mongo_indexes.py

test-e2e:
	PYTHONNOUSERSITE=$(PYTHONNOUSERSITE) conda run -n $(CONDA_ENV) python e2e/dialogue_e2e.py

check-all: test-backend test-frontend-build test-e2e
