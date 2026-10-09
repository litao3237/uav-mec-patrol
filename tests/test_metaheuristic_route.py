"""新基线的覆盖、可复现性和预算停止回归检查。"""
import pytest
from uav_mec.algorithms.initial.metaheuristic_route import RouteMetaheuristicConfig, run_route_metaheuristic
from uav_mec.analysis.experiment_snapshot import content_hash
from uav_mec.evaluation import validate_solution
from uav_mec.instances import build_paper_scale_instance,load_paper_scale_config


@pytest.fixture(scope='module')
def instance():
    return build_paper_scale_instance(load_paper_scale_config(),num_tasks=8,num_uavs=2,num_mecs=2,scenario_seed=17)


@pytest.mark.parametrize('method',['SA-MR','DPSO-MR'])
def test_complete_reproducible_and_monotone(instance,method):
    cfg=RouteMetaheuristicConfig(iterations=6,population_size=3,generations=2)
    a=run_route_metaheuristic(instance,method=method,seed=11,config=cfg)
    b=run_route_metaheuristic(instance,method=method,seed=11,config=cfg)
    validate_solution(instance,a.best_solution)
    assert content_hash(a.best_solution)==content_hash(b.best_solution)
    assigned=[t for r in a.best_solution.routes.values() for t in r.task_ids()]
    assert len(assigned)==len(set(assigned))==len(instance.tasks)
    values=[h['best_proxy_objective'] for h in a.history]
    assert all(y<=x for x,y in zip(values,values[1:]))
    assert a.evaluations==(7 if method=='SA-MR' else 9)


@pytest.mark.parametrize('method',['SA-MR','DPSO-MR'])
def test_zero_budget_returns_valid_initial_solution(instance,method):
    result=run_route_metaheuristic(instance,method=method,seed=0,config=RouteMetaheuristicConfig(max_runtime_s=0))
    validate_solution(instance,result.best_solution)
    assert result.evaluations==1


def test_rejects_invalid_numeric_configuration(instance):
    with pytest.raises(ValueError,match='时间上限'):
        run_route_metaheuristic(instance,method='SA-MR',seed=0,config=RouteMetaheuristicConfig(max_runtime_s=float('nan')))
