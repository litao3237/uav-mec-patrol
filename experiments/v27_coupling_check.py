"""v27 coupling check: do the non-route decisions matter once routes are frozen?

For each instance the routes come from a distance-only sweep + 2-opt
constructor and are held fixed. Three offloading policies are compared:

  L  onboard-first: every onboard-capable task runs onboard; edge-only tasks
     are uploaded at the depot station on return (no search).
  E  edge-only (searched): every task is offloaded; contact visits and
     upload assignment are searched.
  O  joint (searched): per-task choice between onboard and edge, contacts and
     upload assignment searched, starting from L.

Gate (registered before running): the joint decision matters if O beats the
better single-mode policy by >= 10% in the controllable objective. Since
flight energy is fixed by the frozen routes, both the full objective J and the
AoI term are reported; late tasks and normalized tardiness come first.

Variants are a PRE-DECLARED sensitivity grid, not a tuning loop:
  base            configs/v27_timeliness.yaml as written
  weak_onboard    0.5 Gcycles/s, 5 W onboard computer (no GPU payload)
  heavy_edge_only heavy analytics cannot run onboard

Usage:
  python experiments/v27_coupling_check.py --tasks 30 50 80 --seeds 45 46 47 48 \
      --variants base weak_onboard heavy_edge_only --workers 2 --output outputs/v27/coupling
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from uav_mec.v27 import Structure, evaluate, generate_instance, load_params  # noqa: E402
from uav_mec.v27.audit import audit  # noqa: E402
from uav_mec.v27.offload_search import _terminal, optimize_offloading  # noqa: E402
from uav_mec.v27.routing import sweep_routes  # noqa: E402

VARIANTS = {
    "base": {},
    "weak_onboard": {"cpu_max_gcps": 0.5, "cpu_min_gcps": 0.1, "cpu_power_at_max_w": 5.0},
    "heavy_edge_only": {"heavy_onboard_allowed": False},
}


def onboard_first(inst, routes) -> Structure:
    d = Structure(routes={u: list(s) for u, s in routes.items()})
    for t, task in inst.tasks.items():
        if not task.onboard_allowed:
            u = next(u for u, s in d.routes.items() if t in s)
            d = _terminal(d, inst, t, u)
    return d


def run_case(args: tuple) -> dict:
    config, variant, k, seed = args
    params = load_params(config).with_overrides(**VARIANTS[variant])
    inst = generate_instance(params, num_tasks=k, seed=seed)
    routes = sweep_routes(inst)
    t0 = time.perf_counter()
    d_l = onboard_first(inst, routes)
    ev_l = evaluate(inst, d_l)
    res_e = optimize_offloading(inst, d_l, allow_local=False)
    res_o = optimize_offloading(inst, d_l, allow_local=True)
    rows = []
    for name, d, ev in (("L", d_l, ev_l), ("E", res_e.structure, res_e.evaluation),
                        ("O", res_o.structure, res_o.evaluation)):
        errs = audit(inst, d, ev)
        s = ev.summary()
        s.update(policy=name, variant=variant, tasks=k, seed=seed, audit_errors=len(errs),
                 audit_first=errs[0] if errs else "",
                 contacts=sum(d.en_route_visit_count(inst, u) for u in d.routes))
        rows.append(s)
    return {"variant": variant, "tasks": k, "seed": seed, "rows": rows,
            "runtime_s": time.perf_counter() - t0,
            "heavy": sum(t.kind == "heavy" for t in inst.tasks.values())}


def gap(best_single: dict, joint: dict, field: str) -> float:
    b = best_single[field]
    return 0.0 if b == 0 else 100.0 * (b - joint[field]) / b


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(ROOT / "configs/v27_timeliness.yaml"))
    ap.add_argument("--tasks", type=int, nargs="+", default=[30, 50, 80])
    ap.add_argument("--seeds", type=int, nargs="+", default=[45, 46, 47, 48])
    ap.add_argument("--variants", nargs="+", default=list(VARIANTS))
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--output", default="outputs/v27/coupling")
    a = ap.parse_args()
    out = Path(a.output)
    out.mkdir(parents=True, exist_ok=True)
    jobs = [(a.config, v, k, s) for v in a.variants for k in a.tasks for s in a.seeds]
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        results = list(ex.map(run_case, jobs))
    (out / "coupling_raw.json").write_text(json.dumps(results, indent=1), encoding="utf-8")

    flat = [r for res in results for r in res["rows"]]
    with (out / "coupling_rows.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(flat[0]))
        w.writeheader()
        w.writerows(flat)

    summary = []
    for res in results:
        by = {r["policy"]: r for r in res["rows"]}
        key = lambda r: (r["late_tasks"], r["norm_tardiness"], r["objective"])
        single = min((by["L"], by["E"]), key=key)
        summary.append({
            "variant": res["variant"], "tasks": res["tasks"], "seed": res["seed"],
            "best_single": single["policy"],
            "late_L": by["L"]["late_tasks"], "late_E": by["E"]["late_tasks"], "late_O": by["O"]["late_tasks"],
            "J_gap_pct": round(gap(single, by["O"], "objective"), 2),
            "AoI_gap_pct": round(gap(single, by["O"], "aoi_term"), 2),
            "offloaded_O": by["O"]["offloaded"], "contacts_O": by["O"]["contacts"],
            "audit_errors": sum(r["audit_errors"] for r in res["rows"]),
            "runtime_s": round(res["runtime_s"], 1),
        })
    with (out / "coupling_summary.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(summary[0]))
        w.writeheader()
        w.writerows(summary)
    for s in summary:
        print(json.dumps(s, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
