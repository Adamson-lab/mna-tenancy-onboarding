.PHONY: install test demo serve docker diagrams clean
install:   ; pip install -e ".[dev]"
test:      ; pytest -q
demo:      ; PYTHONPATH=src python -m mnatenancy demo
serve:     ; PYTHONPATH=src python -m mnatenancy demo --serve --port 8080
docker:    ; docker compose up --build
diagrams:  ; for f in docs/diagrams/*.mmd; do mmdc -i $$f -o $${f%.mmd}.svg -b white; done; python scripts/build_readme.py
clean:     ; rm -rf out demo.db mnat.db .pytest_cache
