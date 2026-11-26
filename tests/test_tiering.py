from mnatenancy.models import DealManifest, Tier
from mnatenancy.tiering import decide

from .conftest import deal


def m(name, **kw):
    return DealManifest.from_dict(deal(name, **kw))


def test_sovereign_is_silo_forever():
    d = decide(m("umbrella-federal"))
    assert d.day1_tier is Tier.SILO and d.target_tier is Tier.SILO
    assert any("sovereign" in h for h in d.hard_constraints)


def test_low_risk_absorb_converges_to_pool_via_bridge():
    d = decide(m("initech-cloud"))
    assert (d.day1_tier, d.target_tier) == (Tier.BRIDGE, Tier.POOL)
    assert d.convergence_path["day_365"] == "pool"


def test_high_risk_absorb_isolated_first_then_bridge():
    d = decide(m("globex-bank"))
    assert d.day1_tier is Tier.SILO
    assert d.target_tier is Tier.BRIDGE  # risk too high for pooling
    assert d.convergence_path["day_100"] == "bridge"


def test_unserved_residency_forces_silo():
    d = decide(m("initech-cloud", data_residency=["me-central-1"]))
    assert d.target_tier is Tier.SILO
    assert any("residency" in h for h in d.hard_constraints)


def test_divest_likely_keeps_silo():
    d = decide(m("initech-cloud", intent="divest_likely"))
    assert d.target_tier is Tier.SILO


def test_preserve_targets_bridge():
    d = decide(m("initech-cloud", intent="preserve"))
    assert d.target_tier is Tier.BRIDGE


def test_day1_never_less_isolated_than_target():
    for name in ("globex-bank", "initech-cloud", "umbrella-federal", "sahel-pay"):
        d = decide(m(name))
        assert d.day1_tier.isolation_rank >= d.target_tier.isolation_rank


def test_rationale_is_explainable():
    d = decide(m("globex-bank"))
    assert any("MFA" in r for r in d.rationale)
    assert any("critical security" in r for r in d.rationale)
