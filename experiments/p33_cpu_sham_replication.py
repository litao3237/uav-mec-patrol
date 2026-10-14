"""P33 exact P32 CPU guard diagnostic-only sham, without P32 tuning.

The CPU-enabled arm is IMPORTED UNCHANGED from P32. For each original
legacy cheapest/regret2 repair the control invokes the SAME P32 CPU
refine_one() on the repaired D with the same limits/same candidate
generation, screening, scoring, and work. A hypothetical modified D is
DISCARDED and the original legacy repaired state is returned.

This is a real diagnostic-work sham at the *per-repair* level, not a
guarantee of the same number of stochastic ALNS iterations under a fixed
wall clock. The unchanged original Stage1+Stage2 are the sole final
feasibility decisions, and original CPU/BW remain unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import wraps
from unittest.mock import patch

import p32_staged_queue_repair as p32
import run_p32_staged_firstuse as p32_run
from uav_mec.algorithms.alns import operators as ops


@dataclass
class CpuShamCounters(p32.P32Counters):
    hypothetical_selected_D:int=0

    def snapshot(self):
        return {
            **super().snapshot(),
            "hypothetical_selected_D":self.hypothetical_selected_D,
            "return_unmodified_original_repair_D":True,
            "uses_unchanged_P32_cpu_guard_candidate_generator_and_ranking":True,
        }


def make_cpu_sham_list(counters:CpuShamCounters,limits=None):
    limits=limits or p32.LIMITS
    existing=ops.make_repair_operators()
    wrapped=[]
    for name,old in existing:
        @wraps(old)
        def applied(destroyed,rng,old=old):
            original_full=old(destroyed,rng)
            counters.legacy_full_builder_calls+=1
            earlier_actual=counters.chosen_other_D
            hypothetical=p32.refine_one(
                original_full,"cpu_guard",counters,limits
            )
            if hypothetical is not original_full:
                if counters.chosen_other_D!=earlier_actual+1:
                    raise RuntimeError("P33 sham disagreed with actual CPU guard")
                counters.hypothetical_selected_D+=1
            counters.chosen_other_D=earlier_actual
            return original_full
        wrapped.append((name,applied))
    if [n for n,_ in wrapped]!=[n for n,_ in existing]:
        raise RuntimeError("P33 modified original ALNS repair registrations")
    return wrapped


def run_cpu_sham(inst,initial,seed):
    """Reuse SAME P32 original hybrid runner and strict audit, only SHAM hook."""
    with (
        patch.object(
            p32_run,"POLICIES",tuple(p32.POLICIES)+("cpu_sham",)
        ),
        patch.object(p32_run,"P32Counters",CpuShamCounters),
        patch.object(p32_run,"make_repair_list",
                     lambda policy,counters,limits:
                         make_cpu_sham_list(counters,limits)),
    ):
        result=p32_run.run_one(inst,initial,seed,"cpu_sham")
    result["uses_exact_P32_cpu_guard_repair_diagnostics_without_action"]=True
    if result["postrepair"]["chosen_other_D"]!=0:
        raise RuntimeError("P33 sham actively changed a repaired D")
    return result
