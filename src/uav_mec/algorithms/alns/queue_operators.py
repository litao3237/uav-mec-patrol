"""P9: opt-in FIFO/EDF-predecessor task destroy for the ORIGINAL ALNS.

P7 showed that on high-load stress scenarios, original ALNS almost
never visits a state satisfying the necessary FIFO/EDF completion-time
constraints. P8's direct queue-violation scalar grading failed to
create more queue-feasible states in six stressed development cases.

P9 addresses the SOURCE of generated structures, not the score:
replace just the original 'critical_task_removal' destroy choice with
a queue-task, queue-predecessor or workload-matched comparator.
ALL original repair operators, ALNS roulette/reward, RRT acceptance,
screened-proxy evaluation, P1-R and Stage2 stay exactly unchanged.

For each target task that VIOLATES its optimistic deadline:
- A LOCAL task depends on earlier FIFO local tasks and earlier UAV
  uploads that delay its collection;
- An OFFLOADED task depends on EDF predecessors in its MEC batch,
  prior FIFO batches of the same UAV/MEC pair, and earlier UAV contacts
  that delay its uploading.
Sampling uses same q and critical_pool_factor as old critical destroy,
with same numpy rng.choice contract. Priorities are HEURISTIC; queue
necessary lower bounds are never treated as proof of full feasibility.
"""
from __future__ import annotations

from collections import defaultdict
from functools import partial, update_wrapper

import numpy as np

from uav_mec.domain import ExecutionMode
from uav_mec.evaluation import build_event_info
from uav_mec.optimization.resource.queue_aware_precheck import (
    queue_aware_feasibility_precheck,
)

from .operators import DestroyConfig,_destroy_tasks

QUEUE_DESTROY_POLICIES=("queue_task","queue_chain","workload_control")


def _critical_queue_chains(instance,solution,info,queue):
    """Map each optimistic deadline-violating task to compulsory predecessors."""
    tasks_for_visit=info.batch_tasks
    result={}
    for tid,task in instance.tasks.items():
        gap=(
            queue.task_completion_lb_s[tid]
            -(task.release_s+task.deadline_s))
        if gap<=1e-4:continue
        uid=info.task_owner[tid]
        dependents={tid}
        decision=solution.task_decisions[tid]
        if decision.mode is ExecutionMode.LOCAL:
            local=info.local_order[uid]
            if tid not in local:raise ValueError("Invalid local FIFO task in event info")
            dependents.update(local[:local.index(tid)])
            for v in info.prior_contacts_before_task[uid,tid]:
                dependents.update(tasks_for_visit[v])
        else:
            current=decision.contact_visit_id
            edf=info.batch_edf_order[current]
            if tid not in edf:raise ValueError("Invalid offloaded task EDF order")
            dependents.update(edf[:edf.index(tid)])
            prev=info.contact_predecessor_same_mec[current]
            while prev is not None:
                dependents.update(tasks_for_visit[prev])
                prev=info.contact_predecessor_same_mec[prev]
            for v in info.prior_contacts_before_contact[uid,current]:
                dependents.update(tasks_for_visit[v])
        result[tid]=dependents
    return result


def queue_guided_task_rank(instance,solution,*,policy):
    if policy not in QUEUE_DESTROY_POLICIES:
        raise ValueError("Unknown queue destroy policy")
    info=build_event_info(instance,solution)
    queue=queue_aware_feasibility_precheck(instance,solution,info)
    # Avoid mapping partial destroyed states; ALNS calls destroys only on
    # complete valid states so this should always hold.
    pressure={}
    direct={}
    for tid,task in instance.tasks.items():
        gap=max(0.0,queue.task_completion_lb_s[tid]-(
            task.release_s+task.deadline_s))
        ratio=gap/max(1.0,task.deadline_s)
        direct[tid]=ratio
        pressure[tid]=ratio
    if policy=="queue_chain":
        for late_task,predecessors in _critical_queue_chains(
            instance,solution,info,queue).items():
            related=direct[late_task]
            for pred in predecessors:
                if pred==late_task:continue
                # Prioritize real binding-chain tasks without assuming
                # they are all equally causally important.
                own=instance.tasks[pred]
                w=own.workload_gcycles/max(1.0,own.deadline_s)
                pressure[pred]=max(
                    pressure[pred],
                    related*(.55+.15*min(1.0,w)),
                )
    elif policy=="workload_control":
        pressure={
            tid:task.workload_gcycles/max(1.0,task.deadline_s)
            for tid,task in instance.tasks.items()
        }
    # Equal score secondary key keeps deterministic pairing and the
    # largest physically time-consuming blockers favored.
    ranked=sorted(instance.tasks,key=lambda tid:(
        -pressure[tid],
        -direct[tid],
        -instance.tasks[tid].workload_gcycles,
        tid))
    return ranked,{
        "policy":policy,
        "queue_pass":bool(queue.feasible),
        "deadline_violators":sum(x>1e-4 for x in direct.values()),
        "highest_normalized_deadline_excess":max(direct.values(),default=0.),
        "task_count":len(ranked),
    }


def queue_critical_task_removal(
    current,rng:np.random.Generator,*,
    config:DestroyConfig,policy:str="queue_chain"):
    rank,why=queue_guided_task_rank(
        current.instance,current.solution,policy=policy)
    del why
    q=config.count(len(rank))
    pool_size=min(len(rank),max(q,config.critical_pool_factor*q))
    pool=rank[:pool_size]
    if len(pool)<q:raise RuntimeError("Insufficient complete ALNS target tasks")
    chosen=rng.choice(pool,size=q,replace=False).tolist()
    return _destroy_tasks(current,chosen)


def create_queue_destroy_operator(config:DestroyConfig,policy:str):
    if policy not in QUEUE_DESTROY_POLICIES:
        raise ValueError(policy)
    fn=partial(queue_critical_task_removal,config=config,policy=policy)
    update_wrapper(fn,queue_critical_task_removal)
    return fn
