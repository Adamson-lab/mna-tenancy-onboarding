"""Inject docs/diagrams/*.mmd into README.md so diagrams and docs never drift.
Usage: python scripts/build_readme.py
"""
import pathlib
import re

root = pathlib.Path(__file__).resolve().parents[1]
tpl = (root / "docs/README.tpl.md").read_text()


def inject(m):
    name = m.group(1)
    src = (root / f"docs/diagrams/{name}.mmd").read_text().strip()
    return f"```mermaid\n{src}\n```\n<sub>Source: [`docs/diagrams/{name}.mmd`](docs/diagrams/{name}.mmd) · [SVG](docs/diagrams/{name}.svg)</sub>"


(root / "README.md").write_text(re.sub(r"\{\{diagram:([\w-]+)\}\}", inject, tpl))
print("README.md built")
