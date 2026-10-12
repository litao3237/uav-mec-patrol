"""Guard that diagnostic tie interventions change ONLY score-equivalent choices."""
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"experiments"))

from run_p1_tie_break_audit import POLICIES,rearrange,primary


def _make(label,family,sig,distance=10.0):
    return {
        "label":label,"family":family,"sig":sig,
        "metric":{"passed":True,"n_reasons":0,"total_excess_s":0.,
                  "route_distance_m":distance},
    }


def test_reuse_is_only_preferred_when_numeric_keys_are_exactly_equal():
    originals=[
        _make("bundle_new_contact::a","bundle_new_contact","n"),
        _make("bundle_new_contact::b","bundle_new_contact","n2"),
        _make("bundle_reuse_contact::a","bundle_reuse_contact","r"),
        _make("other::a","other","o",distance=10.01),
    ]
    observed=rearrange(originals,"reuse_on_exact_ties")
    assert observed[0]["sig"]=="r"
    assert observed[-1]["sig"]=="o"
    assert [primary(x) for x in observed]==[primary(x) for x in originals]
    assert [x["sig"] for x in observed]!=[x["sig"] for x in originals]


def test_diversity_preserves_same_numeric_ranking_and_total_candidate_set():
    originals=[
        _make("bundle_new_contact::a","bundle_new_contact","n"),
        _make("bundle_new_contact::b","bundle_new_contact","n2"),
        _make("bundle_reuse_contact::a","bundle_reuse_contact","r"),
        _make("task_mode::a","task_mode","l"),
    ]
    diverse=rearrange(originals,"diverse_on_exact_ties")
    assert [x["sig"] for x in diverse][:3]==["n","r","l"]
    for policy in POLICIES:
        result=rearrange(originals,policy)
        assert {x["sig"] for x in result}=={x["sig"] for x in originals}
        assert [primary(x) for x in result]==[primary(x) for x in originals]
