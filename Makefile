PYTHONNOUSERSITE ?= 1
CONDA_ENV ?= poly_agent
PYTEST_ARGS ?= backend/tests
PYTHONPATH ?= backend

.PHONY: test-backend
test-backend:
	PYTHONNOUSERSITE=$(PYTHONNOUSERSITE) PYTHONPATH=$(PYTHONPATH) conda run -n $(CONDA_ENV) python -m pytest $(PYTEST_ARGS)
