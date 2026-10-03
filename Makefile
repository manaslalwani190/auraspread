.PHONY: setup data test serve all clean

PYTHON ?= python

setup:
	$(PYTHON) -m pip install -r requirements.txt

data:
	$(PYTHON) -m pipeline.run_pipeline

test:
	$(PYTHON) -m pytest pipeline/tests -v

serve:
	$(PYTHON) -m http.server 8000 --directory web

all: setup data test serve

clean:
	rm -rf data/processed/* web/data/* .pytest_cache
