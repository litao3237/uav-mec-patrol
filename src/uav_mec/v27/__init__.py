"""v27 timeliness model for multi-UAV forest patrol with intermittent edge contact.

Self-contained: it does not import or modify the archived v25 model
(``uav_mec.domain``/``uav_mec.optimization``), whose recorded results stay
reproducible.

Model summary
-------------
* Freshness (age of information) of task i is ``AoI_i = c_i - t_i^col``:
  from collection completion to result completion, not from mission start.
* UAV propulsion follows the Zeng et al. (TWC 2019) rotary-wing model.
* Each edge station serves one upload at a time with its full bandwidth
  (TDMA, FCFS by arrival) and processes uploaded tasks on one server at full
  speed (FIFO by upload completion, EDF inside a batch).
* The only continuous decision for a fixed discrete structure is the onboard
  DVFS frequency of locally processed tasks (convex per-UAV subproblem).
"""

from .params import ModelParams, load_params
from .instance import Instance, generate_instance
from .solution import Structure
from .evaluate import evaluate, Evaluation

__all__ = [
    "ModelParams",
    "load_params",
    "Instance",
    "generate_instance",
    "Structure",
    "evaluate",
    "Evaluation",
]
