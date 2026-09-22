from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median, stdev
from typing import Any


METHODS = (
    "time_b_alns",
    "budget_v5",
    "energy_guided_v6",
)
EXPECTED_K = (50, 80)
EXPECTED_SCENARIOS = tuple(range(93, 101))
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
    rows: list[dict[str, Any]] = []
    for path in sorted(input_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not payload.get("complete", False):
            raise ValueError(f"Incomplete result: {path}")
        row = payload.get("row")
        if row is None:
            raise ValueError(f"Missing row: {path}")
        rows.append(row)
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
    unexpected = sorted(observed - expected)
    if missing or duplicate or unexpected:
        raise ValueError(
            "Energy-guided v6 holdout matrix mismatch: "
            f"rows={len(rows)}, unique={len(observed)}, "
            f"missing={missing}, duplicate={duplicate}, "
            f"unexpected={unexpected}"
        )


def _method_summary(
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
        (row, record)
        for row, record in records
        if (
            record.get("stage1_status") == "optimal"
            and record.get("energy_j") is not None
        )
    ]

    strict_by_scenario: dict[int, int] = defaultdict(int)
    energy_by_scenario: dict[int, list[float]] = defaultdict(list)
    for row, record in strict:
        scenario = int(row["scenario_seed"])
        strict_by_scenario[scenario] += 1
        energy_by_scenario[scenario].append(
            float(record["energy_j"])
        )

    cvs: list[float] = []
    spreads: list[float] = []
    for values in energy_by_scenario.values():
        if len(values) >= 2:
            center = mean(values)
            if abs(center) > 1e-12:
                cvs.append(
                    100.0 * stdev(values) / abs(center)
                )
                spreads.append(
                    100.0
                    * (max(values) - min(values))
                    / abs(center)
                )

    statuses = Counter(
        str(record.get("stage1_status"))
        for _, record in records
    )

    def values(key: str) -> list[float]:
        return [
            float(record[key])
            for _, record in records
            if record.get(key) is not None
        ]

    def dvalues(path: tuple[str, ...]) -> list[float]:
        result: list[float] = []
        for _, record in records:
            obj: Any = record.get("diagnostics", {})
            for key in path:
                if not isinstance(obj, dict):
                    obj = None
                    break
                obj = obj.get(key)
            if obj is not None:
                result.append(float(obj))
        return result

    return {
        "K": k,
        "method": method,
        "runs": len(records),
        "strict": len(strict),
        "strict_rate": len(strict) / len(records),
        "stage1_status_counts": dict(sorted(statuses.items())),
        "fully_strict_scenarios": sum(
            strict_by_scenario.get(scenario, 0) == 3
            for scenario in EXPECTED_SCENARIOS
        ),
        "energy_j": _stats(
            [float(record["energy_j"]) for _, record in strict]
        ),
        "within_scenario_cv_pct": _stats(cvs),
        "within_scenario_spread_pct": _stats(spreads),
        "method_runtime_s": _stats(values("method_runtime_s")),
        "budget_overrun_s": _stats(values("budget_overrun_s")),
        "budget_utilization_pct": _stats(
            values("budget_utilization_pct")
        ),
        "verification_runtime_s": _stats(
            values("verification_runtime_s")
        ),
        "completed_iterations": _stats(
            dvalues(("completed_iterations",))
        ),
        "elite_exact_cvx_calls": _stats(
            dvalues(
                (
                    "elite_efficiency",
                    "exact_cvx_calls",
                )
            )
        ),
        "elite_candidates_evaluated": _stats(
            dvalues(
                (
                    "elite_efficiency",
                    "candidates_evaluated",
                )
            )
        ),
        "elite_accepted_improvements": _stats(
            dvalues(
                (
                    "elite_efficiency",
                    "accepted_improvements",
                )
            )
        ),
        "elite_direct_gain_j": _stats(
            dvalues(
                (
                    "elite_efficiency",
                    "accepted_gain_j",
                )
            )
        ),
        "elite_gain_per_cvx_j": _stats(
            dvalues(
                (
                    "elite_efficiency",
                    "gain_per_cvx_j",
                )
            )
        ),
        "elite_gain_per_exact_second_jps": _stats(
            dvalues(
                (
                    "elite_efficiency",
                    "gain_per_exact_second_jps",
                )
            )
        ),
        "elite_strict_candidate_hit_rate": _stats(
            dvalues(
                (
                    "elite_efficiency",
                    "strict_candidate_hit_rate",
                )
            )
        ),
        "elite_accepted_candidate_hit_rate": _stats(
            dvalues(
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
    gains: list[float] = []
    by_scenario: dict[int, list[float]] = defaultdict(list)

    for row in rows:
        if int(row["K"]) != k:
            continue
        base = row["methods"][baseline]
        tested = row["methods"][method]
        if (
            base.get("stage1_status") != "optimal"
            or tested.get("stage1_status") != "optimal"
            or base.get("energy_j") is None
            or tested.get("energy_j") is None
        ):
            continue

        gain = (
            100.0
            * (
                float(base["energy_j"])
                - float(tested["energy_j"])
            )
            / max(1.0, abs(float(base["energy_j"])))
        )
        gains.append(gain)
        by_scenario[int(row["scenario_seed"])].append(gain)

    scenario_means = {
        scenario: mean(values)
        for scenario, values in sorted(by_scenario.items())
    }
    scenario_values = list(scenario_means.values())

    return {
        "K": k,
        "method": method,
        "baseline": baseline,
        "common_strict": len(gains),
        "better": sum(value > 1e-9 for value in gains),
        "equal": sum(abs(value) <= 1e-9 for value in gains),
        "worse": sum(value < -1e-9 for value in gains),
        "run_gain_pct": _stats(gains),
        "scenario_gain_pct": _stats(scenario_values),
        "scenario_means_pct": scenario_means,
        "positive_scenarios": sum(
            value > 1e-9 for value in scenario_values
        ),
        "equal_scenarios": sum(
            abs(value) <= 1e-9 for value in scenario_values
        ),
        "negative_scenarios": sum(
            value < -1e-9 for value in scenario_values
        ),
    }


def _pooled_elite(
    rows: list[dict[str, Any]],
    *,
    k: int,
    method: str,
) -> dict[str, Any]:
    exact_calls = 0
    candidates = 0
    strict_candidates = 0
    accepted = 0
    gain_j = 0.0
    exact_runtime_s = 0.0
    families: Counter[str] = Counter()
    labels: list[str] = []

    for row in rows:
        if int(row["K"]) != k:
            continue
        efficiency = (
            row["methods"][method]
            .get("diagnostics", {})
            .get("elite_efficiency", {})
        )
        exact_calls += int(efficiency.get("exact_cvx_calls", 0))
        candidates += int(
            efficiency.get("candidates_evaluated", 0)
        )
        strict_candidates += int(
            efficiency.get("strict_candidates", 0)
        )
        accepted += int(
            efficiency.get("accepted_improvements", 0)
        )
        gain_j += float(
            efficiency.get("accepted_gain_j", 0.0)
        )
        exact_runtime_s += float(
            efficiency.get("elite_exact_runtime_s", 0.0)
        )

        for move in efficiency.get("accepted_moves", []):
            label = str(move.get("move", ""))
            if not label:
                continue
            labels.append(label)
            families[label.split("::", 1)[0]] += 1

    return {
        "K": k,
        "method": method,
        "exact_cvx_calls": exact_calls,
        "candidates_evaluated": candidates,
        "strict_candidates": strict_candidates,
        "accepted_improvements": accepted,
        "accepted_direct_gain_j": gain_j,
        "exact_runtime_s": exact_runtime_s,
        "gain_per_exact_cvx_j": (
            gain_j / exact_calls
            if exact_calls > 0
            else 0.0
        ),
        "gain_per_exact_second_jps": (
            gain_j / exact_runtime_s
            if exact_runtime_s > 1e-12
            else 0.0
        ),
        "strict_candidate_hit_rate": (
            strict_candidates / candidates
            if candidates > 0
            else 0.0
        ),
        "accepted_candidate_hit_rate": (
            accepted / candidates
            if candidates > 0
            else 0.0
        ),
        "accepted_move_families": dict(
            sorted(families.items())
        ),
        "accepted_move_labels": labels,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    rows = _load(Path(args.input_dir))
    _validate(rows)

    summaries = [
        _method_summary(rows, k=k, method=method)
        for k in EXPECTED_K
        for method in METHODS
    ]

    paired = [
        _paired(
            rows,
            k=k,
            method="energy_guided_v6",
            baseline=baseline,
        )
        for k in EXPECTED_K
        for baseline in (
            "budget_v5",
            "time_b_alns",
        )
    ]

    pooled_elite = [
        _pooled_elite(rows, k=k, method=method)
        for k in EXPECTED_K
        for method in (
            "budget_v5",
            "energy_guided_v6",
        )
    ]

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "complete": True,
                "holdout": True,
                "summaries": summaries,
                "paired": paired,
                "pooled_elite": pooled_elite,
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
            f"fullS={item['fully_strict_scenarios']}/8 "
            f"E={item['energy_j']['mean']} "
            f"CV={item['within_scenario_cv_pct']['mean']} "
            f"runtime={item['method_runtime_s']['mean']} "
            f"overrun={item['budget_overrun_s']['mean']} "
            f"elite-cvx={item['elite_exact_cvx_calls']['mean']}"
        )

    for item in paired:
        print(
            f"PAIR K={item['K']} v6 vs {item['baseline']}: "
            f"n={item['common_strict']} "
            f"B/E/W={item['better']}/{item['equal']}/{item['worse']} "
            f"scenario_mean={item['scenario_gain_pct']['mean']} "
            f"positive/equal/negative="
            f"{item['positive_scenarios']}/"
            f"{item['equal_scenarios']}/"
            f"{item['negative_scenarios']}"
        )

    for item in pooled_elite:
        print(
            f"ELITE K={item['K']} {item['method']}: "
            f"cvx={item['exact_cvx_calls']} "
            f"accepted={item['accepted_improvements']} "
            f"gain={item['accepted_direct_gain_j']} "
            f"J/CVX={item['gain_per_exact_cvx_j']} "
            f"J/s={item['gain_per_exact_second_jps']} "
            f"families={item['accepted_move_families']}"
        )

    print(f"Saved: {output}")


if __name__ == "__main__":
    main()
