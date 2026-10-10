"""修正版B/ESI相同名义端到端预算对照，串行执行并报告资源求解超时。

预算在离散迭代或凸求解边界检查，不能中断单次求解。最终资源验收必做，
总耗时、预算超出量与最终合格状态均保存，不把软预算包装成硬实时限制。
"""
from __future__ import annotations
import argparse
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import logging
from pathlib import Path
from time import perf_counter
import numpy as np

from run_seven_methods import finalize
from experiment_common import provenance, current_source_hashes
from uav_mec.algorithms import (build_greedy_initial_solution,build_mec_assisted_initial_solution,
    UavMecALNSConfig,ScreenedProxyObjectiveEvaluator,run_uav_mec_alns,run_uav_mec_hybrid_alns)
from uav_mec.analysis.experiment_snapshot import write_json,content_hash
from uav_mec.instances import load_paper_scale_config,build_paper_scale_instance

PROTOCOL={'id':'v25_equal_nominal_end_to_end_v1','tasks':[50,80],'scenarios':list(range(45,53)),
    'algorithm_seeds':[100,101,102],'methods':['B-ALNS','ESI-ALNS'],
    'budget_s':{'50':15.0,'80':45.0},'search_fraction':.8,'esi_exploration_fraction':.6,
    'reserved_finalization_fraction':.2,'time_scaled_rrt':True,'rrt_reference_iterations':100,
    'elite_rounds':2,'order_seed':20261009,'sequential':True,
    'boundary':'软预算；初始构造计时，最终两阶段求解及验收全计时；不可抢占求解的超时量单列',
    'claim':'固定预算分配策略下比较修正版；并不保证两方法实际耗时严格相同或策略最优'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--pilot',action='store_true')
    args=parser.parse_args()
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    args.output_dir.mkdir(parents=True,exist_ok=True)
    # 正式计时使用串行进程；调用方必须先结束占用CPU的正式七方法作业。
    hashes=current_source_hashes(Path(__file__))
    for tasks in PROTOCOL['tasks']:
        for scenario in ([45] if args.pilot else PROTOCOL['scenarios']):
            out=args.output_dir/f'K{tasks}_S{scenario}.json'
            if out.exists():
                prior=json.loads(out.read_text(encoding='utf-8'))
                if prior['complete'] and prior['source_hashes']==hashes:continue
                raise RuntimeError(f'已有中断或不同源码结果，保留原文件：{out}')
            instance=build_paper_scale_instance(load_paper_scale_config(),num_tasks=tasks,
                num_uavs=5,num_mecs=2,scenario_seed=scenario)
            payload={'protocol':PROTOCOL,'source_hashes':hashes,'provenance':provenance(),
                     'instance':instance,'instance_sha256':content_hash(instance),'tasks':tasks,
                     'scenario_seed':scenario,'complete':False,'pilot':args.pilot,'rows':[]}
            write_json(out,payload)
            try:
                for seed in ([100] if args.pilot else PROTOCOL['algorithm_seeds']):
                    order=np.random.default_rng([PROTOCOL['order_seed'],tasks,scenario,seed]).permutation(PROTOCOL['methods']).tolist()
                    for method in order:
                        total_start=perf_counter()
                        initial=build_mec_assisted_initial_solution(instance,base_solution=build_greedy_initial_solution(instance))
                        initialization_s=perf_counter()-total_start
                        budget=PROTOCOL['budget_s'][str(tasks)]
                        search_cap=max(0.,.8*budget-initialization_s)
                        evaluator=ScreenedProxyObjectiveEvaluator()
                        search_started=perf_counter()
                        if method=='B-ALNS':
                            result=run_uav_mec_alns(instance,initial_solution=deepcopy(initial),
                                config=UavMecALNSConfig(seed=seed,iterations=100,max_runtime_s=search_cap,
                                    time_scaled_rrt=search_cap>0,enable_problem_operators=False),evaluator=evaluator)
                            solution=result.best_solution
                            diagnostics={'screening_stats':asdict(evaluator.stats)}
                        else:
                            exploration_cap=max(0.,.6*budget-initialization_s)
                            result=run_uav_mec_hybrid_alns(instance,initial_solution=deepcopy(initial),
                                config=UavMecALNSConfig(seed=seed,iterations=100,max_runtime_s=exploration_cap,
                                    time_scaled_rrt=exploration_cap>0,enable_problem_operators=False),
                                evaluator=evaluator,elite_rounds=2,
                                exploration_max_runtime_s=exploration_cap,elite_max_runtime_s=.2*budget)
                            solution=result.best_solution
                            diagnostics={'screening_stats':asdict(evaluator.stats),'elite_stats':result.elite_stats,
                                'exploration_s':result.exploration_runtime_s,'elite_phase_s':result.elite_phase_runtime_s}
                        search_s=perf_counter()-search_started
                        row=finalize(instance,solution,method=method,seed=seed,
                            initialization_s=initialization_s,search_s=search_s,diagnostics=diagnostics)
                        elapsed=perf_counter()-total_start
                        row.update(tasks=tasks,scenario_seed=scenario,method_order=order,
                            nominal_end_to_end_budget_s=budget,measured_end_to_end_s=elapsed,
                            overrun_s=max(0.,elapsed-budget),within_nominal_budget=elapsed<=budget)
                        payload['rows'].append(row);write_json(out,payload)
                        logging.info('K%s S%s A%s %s：两阶段%s，总耗时%.2fs/预算%.0fs',tasks,scenario,seed,
                                     method,row['stage1']['qualified'] and row['stage2']['qualified'],elapsed,budget)
            except Exception as exc:
                payload['execution_error']={'type':type(exc).__name__,'message':str(exc)};write_json(out,payload)
                logging.exception('等预算实验失败，保留完整诊断');raise
            payload['complete']=True;write_json(out,payload)


if __name__=='__main__':main()
