import json
import pathlib

import pytest

from mnatenancy.service import Platform

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEALS = ROOT / "deals"


def deal(name: str, **overrides) -> dict:
    d = json.loads((DEALS / f"{name}.json").read_text())
    d.update(overrides)
    return d


@pytest.fixture
def platform(tmp_path):
    p = Platform(str(tmp_path / "t.db"), str(tmp_path / "out"))
    p.bootstrap_parent(str(DEALS / "parent-northwind.json"))
    return p


@pytest.fixture
def onboarded(platform):
    for n in ("globex-bank", "initech-cloud", "umbrella-federal", "sahel-pay"):
        platform.onboard(deal(n))
    return platform
