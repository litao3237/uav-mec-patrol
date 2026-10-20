"""当前实验共用的运行身份与两阶段残差快照。"""
from importlib.metadata import version
import hashlib
import os
from pathlib import Path
import platform
import subprocess
from uav_mec.analysis.constraint_audit import audit_both_timelines

ROOT = Path(__file__).resolve().parents[1]


def current_source_hashes(*extra: Path) -> dict[str, str]:
    """统一登记相对路径；重启和复用必须比较同一完整数值代码集合。"""
    paths = set((ROOT / "src/uav_mec").rglob("*.py"))
    paths.update([Path(__file__), ROOT / "experiments/run_seven_methods.py",
                  ROOT / "configs/baseline.yaml", *extra])
    return {p.resolve().relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(paths)}

def provenance() -> dict:
    """记录代码、依赖、硬件和线程配置，避免跨runner耗时被误认为算法收益。"""
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, cwd=ROOT).strip()
    return {"git_commit": sha, "python": platform.python_version(),
            "platform": platform.platform(), "processor": platform.processor(),
            "cpu_count": os.cpu_count(), "machine": platform.machine(),
            "dependencies": {p: version(p) for p in ("numpy", "cvxpy", "clarabel", "alns", "scs")},
            "threads": {k: os.environ.get(k) for k in
                        ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")},
            "github_run_id": os.environ.get("GITHUB_RUN_ID"),
            "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT")}


def stage_snapshot(instance, solution, result, *, stage: int) -> dict:
    """阶段失败保留原因；不把求解器回退的Stage-1变量当成Stage-2输出。"""
    status = result.diagnostics.get(f"stage{stage}_status", result.status if stage == 1 else "not_run")
    values = result.stage1_values if stage == 1 else result.diagnostics.get("stage2_raw_values")
    limit = None if stage == 1 else result.energy_stage1_j + result.diagnostics.get("energy_tolerance_j", 0.0)
    if not values:
        return {"status": status, "available": False, "qualified": False,
                "reason": "此阶段没有完整原始变量快照", "values": None, "audit": None}
    audit = audit_both_timelines(instance, solution, values, energy_limit_j=limit)
    return {"status": status, "available": True, "values": values, "audit": audit,
            "qualified": status == "optimal" and all(v["passed"] for v in audit.values())}
