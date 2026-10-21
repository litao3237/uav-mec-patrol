"""M0.4 domain feedback: physical energy, MEC proxy benefit and deadline risk."""
from dataclasses import replace
import pytest

from uav_mec.algorithms.alns import (
    ScreenedProxyObjectiveEvaluator, UavMecALNSConfig, run_uav_mec_alns,
)
from uav_mec.algorithms.alns.domain_credit import domain_features
from uav_mec.instances import build_small_instance


def _snap(*, flight=10000., upload=1000., energy=12000.,
          offload=("S1",), ratio_s1=.95, ratio_s2=.91, visits=1):
    return {
        "flight_energy_j": flight,
        "flight_distance_m": flight / 18.,
        "upload_energy_j": upload,
        "energy_j": energy,
        "offloaded_tasks": offload,
        "normalized_completion": {"S1":ratio_s1,"S2":ratio_s2},
        "contact_visits": visits,
    }


def test_route_term_uses_flight_energy_not_contacts_or_distance_only():
    base=_snap(flight=10000.,visits=1)
    improvement=_snap(flight=9200.,visits=5)
    terms=domain_features(base, improvement)
    assert terms["flight"]==pytest.approx(1.)
    assert terms["delta_flight_j"]==pytest.approx(800.)
    assert terms["delta_flight_m"]>0.
    assert "contacts" not in terms
    # Adding contacts without reducing flight/latency cannot create a bonus.
    no_improvement=domain_features(base,_snap(visits=5))
    assert no_improvement["flight"]==0.
    assert no_improvement["mec"]==0.
    assert no_improvement["deadline"]==0.


def test_contact_benefit_requires_task_relief_net_of_upload_burden():
    base=_snap(ratio_s1=.98,upload=900.)
    improved=_snap(ratio_s1=.80,upload=950.,visits=3)
    worse=_snap(ratio_s1=.98,upload=1500.,visits=3)
    good=domain_features(base,improved)
    bad=domain_features(base,worse)
    assert good["mec"]>0
    assert good["delta_upload_energy_j"]<0
    assert bad["mec"]<0
    no_offload=domain_features(_snap(offload=()),_snap(offload=(),visits=7))
    assert no_offload["mec"]==0.
    with pytest.raises(ValueError):
        domain_features(base,{**base,"normalized_completion":{"S7":.5}})


def test_deadline_pressure_only_activates_near_task_deadline():
    easy_before=_snap(ratio_s1=.3,ratio_s2=.4)
    easy_after=_snap(ratio_s1=.2,ratio_s2=.3)
    assert domain_features(easy_before,easy_after)["deadline"]==0.
    near=_snap(ratio_s1=.99,ratio_s2=.92)
    better=_snap(ratio_s1=.86,ratio_s2=.80)
    assert domain_features(near,better)["deadline"]>0
    assert domain_features(better,near)["deadline"]<0


def test_cached_domain_features_never_add_solver_calls():
    inst,sol=build_small_instance()
    inst=replace(inst,qos_hard=False)
    evaluator=ScreenedProxyObjectiveEvaluator(capture_domain_snapshots=True)
    score=evaluator(inst,sol)
    calls=evaluator.stats.calls
    snapshot=evaluator.domain_snapshot(inst,sol)
    key=evaluator.quality_key(inst,sol)
    assert evaluator.stats.calls==calls
    assert isinstance(score,float) and len(key)==5
    assert snapshot["flight_energy_j"]>=0
    assert set(snapshot["normalized_completion"])==set(inst.tasks)
    assert snapshot["contact_visits"]==len(sol.contact_visits)


@pytest.mark.parametrize("component",[
    ("flight",),("mec",),("deadline",),("flight","mec","deadline"),
])
def test_domain_bandit_full_alns_smoke_and_bounded_credit(component):
    inst,sol=build_small_instance()
    inst=replace(inst,qos_hard=False)
    config=UavMecALNSConfig(
        iterations=8,seed=100,selection_mode="domain_credit_ucb",
        domain_credit_components=component,diagnostic_trace=True,
    )
    evaluator=ScreenedProxyObjectiveEvaluator()
    result=run_uav_mec_alns(
        inst,initial_solution=sol,config=config,evaluator=evaluator,
    )
    assert result.best_solution
    assert len(result.search_trace)==8
    assert len(result.domain_history)==8
    assert len(result.credit_history)==8
    assert evaluator.capture_domain_snapshots is True
    assert len(evaluator._domain_cache)>0
    assert sum(sum(vals) for vals in result.operator_pair_counts.values())==8
    assert all(0<=ev["adjusted_credit"]<=1 for ev in result.domain_history)
    assert all(ev["active_components"]==list(component) for ev in result.domain_history)
    assert all(ev["credit"]==pytest.approx(domain["adjusted_credit"])
               for ev,domain in zip(result.credit_history,result.domain_history))


def test_legacy_selector_is_not_changed_by_opt_in_feature():
    inst,sol=build_small_instance()
    inst=replace(inst,qos_hard=False)
    c=UavMecALNSConfig(iterations=9,seed=100,selection_mode="unit_credit_ucb")
    old=run_uav_mec_alns(
        inst,initial_solution=sol,config=c,
        evaluator=ScreenedProxyObjectiveEvaluator(),
    )
    observed=run_uav_mec_alns(
        inst,initial_solution=sol,config=replace(c,diagnostic_trace=True),
        evaluator=ScreenedProxyObjectiveEvaluator(),
    )
    assert old.best_solution==observed.best_solution
    assert old.operator_pair_counts==observed.operator_pair_counts
    assert old.best_objective==pytest.approx(observed.best_objective)
    assert not old.domain_history
    assert not observed.domain_history


def test_invalid_components_and_hard_mode_fail_closed():
    inst,sol=build_small_instance()
    with pytest.raises(ValueError):
        run_uav_mec_alns(
            inst,initial_solution=sol,
            config=UavMecALNSConfig(
                iterations=2,selection_mode="domain_credit_ucb",
            ),
        )
    inst=replace(inst,qos_hard=False)
    with pytest.raises(ValueError):
        run_uav_mec_alns(
            inst,initial_solution=sol,
            config=UavMecALNSConfig(
                iterations=2,selection_mode="domain_credit_ucb",
                domain_credit_components=("flight","unrecognized"),
            ),
        )
