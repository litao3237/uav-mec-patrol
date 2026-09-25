from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean, median, stdev
from typing import Any


METHODS = (
    "time_b_alns",
    "budget_v5",
    "energy_guided_no_dual",
    "energy_guided_v6",
)
EXPECTED_K = (50, 80)
EXPECTED_SCENARIOS = (85, 86, 87, 88)
EXPECTED_ALGORITHMS = (100, 101, 102)


def _stats(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {
            "mean": None,
            "median": None,
            "std": None,
            "min": None,
            "max": None,
        }
    return {
        "mean": mean(values),
        "median": median(values),
        "std": stdev(values) if len(values) > 1 else 0.0,
        "min": min(values),
        "max": max(values),
    }


def _load(input_dir: Path) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(input_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not payload.get("complete", False):
            raise ValueError(f"Incomplete result: {path}")
        rows.append(payload["row"])
    return rows


def _validate(rows: list[dict[str, Any]]) -> None:
    expected = {
        (k, scenario, algorithm)
        for k in EXPECTED_K
        for scenario in EXPECTED_SCENARIOS
        for algorithm in EXPECTED_ALGORITHMS
    }
    keys = [
        (
            int(row["K"]),
            int(row["scenario_seed"]),
            int(row["algorithm_seed"]),
        )
        for row in rows
    ]
    observed = set(keys)
    missing = sorted(expected - observed)
    duplicate = sorted(
        key for key in observed if keys.count(key) > 1
    )
    if missing or duplicate:
        raise ValueError(
            f"Matrix mismatch missing={missing} duplicate={duplicate}"
        )


def _summary(
    rows: list[dict[str, Any]],
    *,
    k: int,
    method: str,
) -> dict[str, Any]:
    records = [
        (row, row["methods"][method])
        for row in rows
        if int(row["K"]) == k
    ]
    strict = [
        (row, rec)
        for row, rec in records
        if rec.get("stage1_status") == "optimal"
        and rec.get("energy_j") is not None
    ]

    by_scenario: dict[int, list[float]] = defaultdict(list)
    strict_counts: dict[int, int] = defaultdict(int)
    for row, rec in strict:
        scenario = int(row["scenario_seed"])
        strict_counts[scenario] += 1
        by_scenario[scenario].append(float(rec["energy_j"]))

    cvs = []
    for values in by_scenario.values():
        if len(values) >= 2:
            center = mean(values)
            if abs(center) > 1e-12:
                cvs.append(
                    100.0 * stdev(values) / abs(center)
                )

    def diag_values(path: tuple[str, ...]) -> list[float]:
        values = []
        for _, rec in records:
            obj: Any = rec.get("diagnostics", {})
            for key in path:
                if not isinstance(obj, dict):
                    obj = None
                    break
                obj = obj.get(key)
            if obj is not None:
                values.append(float(obj))
        return values

    return {
        "K": k,
        "method": method,
        "runs": len(records),
        "strict": len(strict),
        "fully_strict_scenarios": sum(
            strict_counts.get(scenario, 0) == 3
            for scenario in EXPECTED_SCENARIOS
        ),
        "energy_j": _stats(
            [float(rec["energy_j"]) for _, rec in strict]
        ),
        "within_scenario_cv_pct": _stats(cvs),
        "runtime_s": _stats(
            [float(rec["method_runtime_s"]) for _, rec in records]
        ),
        "overrun_s": _stats(
            [float(rec["budget_overrun_s"]) for _, rec in records]
        ),
        "iterations": _stats(
            diag_values(("completed_iterations",))
        ),
        "elite_candidates": _stats(
            diag_values(
                (
                    "elite_efficiency",
                    "candidates_evaluated",
                )
            )
        ),
        "elite_exact_cvx_calls": _stats(
            diag_values(
                (
                    "elite_efficiency",
                    "exact_cvx_calls",
                )
            )
        ),
        "elite_accepted": _stats(
            diag_values(
                (
                    "elite_efficiency",
                    "accepted_improvements",
                )
            )
        ),
        "elite_gain_j": _stats(
            diag_values(
                (
                    "elite_efficiency",
                    "accepted_gain_j",
                )
            )
        ),
        "gain_per_cvx_j": _stats(
            diag_values(
                (
                    "elite_efficiency",
                    "gain_per_cvx_j",
                )
            )
        ),
        "gain_per_exact_second_jps": _stats(
            diag_values(
                (
                    "elite_efficiency",
                    "gain_per_exact_second_jps",
                )
            )
        ),
        "accepted_hit_rate": _stats(
            diag_values(
                (
                    "elite_efficiency",
                    "accepted_candidate_hit_rate",
                )
            )
        ),
    }


def _paired(
    rows: list[dict[str, Any]],
    *,
    k: int,
    method: str,
    baseline: str,
) -> dict[str, Any]:
    gains = []
    by_scenario: dict[int, list[float]] = defaultdict(list)

    for row in rows:
        if int(row["K"]) != k:
            continue
        a = row["methods"][baseline]
        b = row["methods"][method]
        if (
            a.get("stage1_status") != "optimal"
            or b.get("stage1_status") != "optimal"
            or a.get("energy_j") is None
            or b.get("energy_j") is None
        ):
            continue
        gain = (
            100.0
            * (
                float(a["energy_j"])
                - float(b["energy_j"])
            )
            / max(1.0, abs(float(a["energy_j"])))
        )
        gains.append(gain)
        by_scenario[int(row["scenario_seed"])].append(gain)

    scenario_means = {
        scenario: mean(values)
        for scenario, values in sorted(by_scenario.items())
    }
    sv = list(scenario_means.values())
    return {
        "K": k,
        "method": method,
        "baseline": baseline,
        "common_strict": len(gains),
        "better": sum(v > 1e-9 for v in gains),
        "equal": sum(abs(v) <= 1e-9 for v in gains),
        "worse": sum(v < -1e-9 for v in gains),
        "run_gain_pct": _stats(gains),
        "scenario_gain_pct": _stats(sv),
        "scenario_means_pct": scenario_means,
        "positive_scenarios": sum(v > 1e-9 for v in sv),
        "equal_scenarios": sum(abs(v) <= 1e-9 for v in sv),
        "negative_scenarios": sum(v < -1e-9 for v in sv),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    rows = _load(Path(args.input_dir))
    _validate(rows)

    summaries = [
        _summary(rows, k=k, method=method)
        for k in EXPECTED_K
        for method in METHODS
    ]
    paired = [
        _paired(
            rows,
            k=k,
            method=method,
            baseline=baseline,
        )
        for k in EXPECTED_K
        for method, baseline in (
            ("energy_guided_no_dual", "budget_v5"),
            ("energy_guided_v6", "budget_v5"),
            ("energy_guided_v6", "energy_guided_no_dual"),
            ("energy_guided_v6", "time_b_alns"),
        )
    ]

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "complete": True,
                "development": True,
                "summaries": summaries,
                "paired": paired,
                "rows": rows,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    for item in summaries:
        print(
            f"K={item['K']} {item['method']}: "
            f"strict={item['strict']}/{item['runs']} "
            f"E={item['energy_j']['mean']} "
            f"CV={item['within_scenario_cv_pct']['mean']} "
            f"runtime={item['runtime_s']['mean']} "
            f"cvx={item['elite_exact_cvx_calls']['mean']} "
            f"gain/cvx={item['gain_per_cvx_j']['mean']} "
            f"gain/s={item['gain_per_exact_second_jps']['mean']}"
        )

    for item in paired:
        print(
            f"PAIR K={item['K']} {item['method']} vs "
            f"{item['baseline']}: n={item['common_strict']} "
            f"B/E/W={item['better']}/{item['equal']}/{item['worse']} "
            f"scenario_mean={item['scenario_gain_pct']['mean']}"
        )


if __name__ == "__main__":
    main()
