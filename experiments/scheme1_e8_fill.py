"""方案一 E8 补跑：把实例内的任务拆到不同作业运行，结果与实例内并行逐位相同

E8（run 40466638442）的分片 13 超时，6 个实例没有结果：分片里第一个实例（火线 N = 120、ε = 0.25、种子 113）
即使实例内 4 个进程并行，330 分钟也没有算完。这里把一个实例的任务拆开，每个任务占一个作业：

  plan1  用 scheme1_e8.run_instance 本身列出第一阶段的任务（P2、P2 的逐步复现、冷启动链的初始求解）
  stage  在单独的进程里运行一个任务，结果用 pickle 保存（与进程池在进程间传结果的方式相同）
  plan2  读入第一阶段的结果，再用 run_instance 列出 4 条链的任务
  merge  读入全部结果，由 run_instance 组装记录（写法与 run_jobs 相同），复现实例另与 E8 原记录逐位比对

列任务与组装都调用 run_instance 本身：ReplayPool 代替进程池，已有结果的任务直接交回结果，没有结果的只记下来，
在第一次取结果时中止（run_instance 每个阶段都先提交全部任务、再逐个取结果）。每个任务都是用相同的参数调用
scheme1_e8 里的同一个函数，所以除耗时外与实例内并行逐位相同。另取 3 个 E8 已完成的轻实例（REPRO）走同样的
拆分流程，与 E8 原记录比对，作为在 Actions 上的直接核对

用法：
  python experiments/scheme1_e8_fill.py plan1 --set all --out 目录
  python experiments/scheme1_e8_fill.py stage --plan 目录/plan1.pkl --task 任务名 --out 结果目录
  python experiments/scheme1_e8_fill.py plan2 --plan 目录/plan1.pkl --results 结果目录 --out 目录
  python experiments/scheme1_e8_fill.py merge --plan 目录/plan1.pkl --results 结果目录 --out 目录 [--ref E8 记录目录]
  python experiments/scheme1_e8_fill.py local --set smoke --out 目录 [--workers 4] [--ref E8 记录目录]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pickle
import platform
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments"))

import scheme1_e8 as e8  # noqa: E402

# E8 分片 13 的 6 个实例（run 40466638442 中超时、没有结果），与 e8.shard_jobs(13, 40) 相同
MISSING = [("fireline", 120, 113, 0.25), ("fireline", 80, 106, 0.25), ("fireline", 120, 113, 0.1),
           ("fireline", 80, 106, 0.1), ("sector", 50, 113, 0.25), ("fireline", 50, 106, 0.1)]
# E8 已完成的轻实例，走同样的拆分流程后与原记录逐位比对，覆盖三种起点组合：
# 3 条冷启动链（最好解来自冷启动链）、可行的冷启动只有 2 条（增开 1 条热启动链）、没有可行的冷启动（4 条全是热启动链）
REPRO = [("fireline", 50, 114, 0.1), ("sector", 50, 112, 0.1), ("sector", 80, 100, 0.1)]
SETS = {"fill": MISSING, "repro": REPRO, "all": MISSING + REPRO,
        "smoke": e8.jobs(sizes=e8.SMOKE["sizes"], seeds=e8.SMOKE["seeds"], eps_list=e8.SMOKE["eps"])}
STAGE1_FNS = ("task_p2", "task_replica", "task_cold_init")
LABELS = {"task_p2": "p2", "task_replica": "replica", "task_cold_init": "cold", "task_chain": "chain"}


def task_key(fn_name: str, args: tuple) -> str:
    """任务的身份：函数名与参数的 repr 取 SHA-256

    repr 只看取值、不看对象身份，浮点按最短往返表示，所以从 pickle 读回的同值参数得到同一身份
    :param fn_name: scheme1_e8 中的任务函数名
    :param args: 提交任务时的参数
    :return: 十六进制摘要
    """
    return hashlib.sha256(repr((fn_name, args)).encode("utf-8")).hexdigest()


class _NeedResults(Exception):
    """列任务时的中止信号：当前阶段的任务已全部提交，第一次取到还没有结果的任务"""


class _Pending:
    """还没有结果的任务，接口同 Future.result()；取结果即中止 run_instance"""

    def result(self):
        raise _NeedResults


class ReplayPool:
    """代替进程池交给 run_instance：已有结果的任务直接交回结果，没有结果的只记下来

    run_instance 每个阶段都先提交全部任务、再逐个取结果，所以中止时这一阶段的任务已全部记下
    """

    def __init__(self, results: dict):
        """:param results: {任务身份: 任务结果}"""
        self.results = results
        self.pending = []

    def submit(self, fn, *args):
        """与 ProcessPoolExecutor.submit 同名同参

        :return: 有结果时为已完成的任务，否则为取结果即中止的占位
        """
        key = task_key(fn.__name__, args)
        if key in self.results:
            return e8._Done(self.results[key])
        self.pending.append({"key": key, "fn": fn.__name__, "args": args})
        return _Pending()


def replay(job: tuple, results: dict):
    """用已有结果运行 run_instance

    :param job: (布点, N, 种子, ε)
    :param results: {任务身份: 任务结果}
    :return: (记录, 还缺的任务)；还缺任务时记录为 None，列出的是当前阶段已提交而没有结果的任务
    """
    pool = ReplayPool(results)
    try:
        rec = e8.run_instance(job, pool)
    except _NeedResults:
        return None, pool.pending
    if pool.pending:
        raise RuntimeError(f"{job}：记录已组装完成，却仍有未运行的任务")
    return rec, []


def inst_name(job: tuple) -> str:
    """实例名，与 E8 记录文件名相同"""
    layout, n, seed, eps = job
    return e8.record_name({"layout": layout, "n": n, "seed": seed, "eps": eps})


def make_plan1(jobs: list[tuple]) -> dict:
    """列出各实例第一阶段的任务

    :param jobs: 运行单元列表
    :return: {"stage": 1, "jobs": jobs, "tasks": {任务名: {"job", "key", "fn", "args"}}}；
             任务名为 "实例名.s1.序号.类别"，序号是 run_instance 中的提交顺序
    """
    tasks = {}
    for job in jobs:
        rec, pending = replay(job, {})
        if rec is not None or [t["fn"] for t in pending][:2] != ["task_p2", "task_replica"] \
                or any(t["fn"] not in STAGE1_FNS for t in pending):
            raise RuntimeError(f"{job}：第一阶段的任务与预期不符")
        for i, t in enumerate(pending):
            tasks[f"{inst_name(job)}.s1.{i}.{LABELS[t['fn']]}"] = {"job": job, **t}
    return {"stage": 1, "jobs": list(jobs), "tasks": tasks}


def make_plan2(plan1: dict, results: dict) -> tuple[dict, list[str]]:
    """读入第一阶段的结果，列出各实例的 4 条链

    第一阶段还有任务没有结果的实例跳过（例如某个任务超过作业时限），不影响其余实例；
    两个阶段的结果都已齐全的实例（本地重跑时）不再安排任务
    :param plan1: make_plan1 的结果
    :param results: {任务身份: 任务结果}
    :return: ({"stage": 2, "jobs": 可进入第二阶段的实例, "tasks": {...}}, 跳过的说明)
    """
    tasks, jobs, skipped = {}, [], []
    for job in plan1["jobs"]:
        rec, pending = replay(job, results)
        if rec is not None:
            jobs.append(job)
            continue
        if any(t["fn"] != "task_chain" for t in pending):
            missing = [n for n, t in plan1["tasks"].items() if t["job"] == job and t["key"] not in results]
            skipped.append(f"{inst_name(job)}：第一阶段缺 {len(missing)} 个任务的结果 {missing}")
            continue
        jobs.append(job)
        for i, t in enumerate(pending):
            tasks[f"{inst_name(job)}.s2.{i}.{LABELS[t['fn']]}"] = {"job": job, **t}
    return {"stage": 2, "jobs": jobs, "tasks": tasks}, skipped


def save_pickle(obj, path: Path) -> None:
    """保存 pickle（与进程池传结果相同，类型与浮点逐位保留）"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump(obj, f, protocol=pickle.HIGHEST_PROTOCOL)


def load_pickle(path: Path):
    """读入本流程自己写出的 pickle"""
    with open(path, "rb") as f:
        return pickle.load(f)


def run_task(task: dict) -> dict:
    """在当前进程里运行一个任务

    :param task: 计划中的任务 {"job", "key", "fn", "args"}
    :return: {"key", "fn", "result", "wall"}；wall 为调用耗时（秒，含重建实例）
    """
    fn = getattr(e8, task["fn"])
    t0 = time.perf_counter()
    res = fn(*task["args"])
    return {"key": task["key"], "fn": task["fn"], "result": res, "wall": time.perf_counter() - t0}


def run_stage(plan_path: Path, name: str, out: Path) -> Path:
    """stage 子命令：运行计划中的一个任务，结果存为 任务名.pkl

    :param plan_path: plan1.pkl 或 plan2.pkl
    :param name: 任务名
    :param out: 结果目录
    :return: 结果文件路径
    """
    task = load_pickle(plan_path)["tasks"][name]
    res = run_task(task)
    res.update({"name": name, "job": task["job"], "host": platform.platform(), "python": platform.python_version()})
    path = out / f"{name}.pkl"
    save_pickle(res, path)
    return path


def load_results(d: Path) -> tuple[dict, dict]:
    """读入结果目录（含子目录）中的全部任务结果

    :return: ({任务身份: 结果}, {任务身份: {"name", "wall"}})
    """
    results, info = {}, {}
    for p in sorted(Path(d).rglob("*.pkl")):
        r = load_pickle(p)
        results[r["key"]] = r["result"]
        info[r["key"]] = {"name": r["name"], "wall": r["wall"]}
    return results, info


def strip_timing(rec: dict) -> dict:
    """去掉墙钟耗时与补跑说明（每次运行都不同），其余字段用于逐位比对

    :param rec: 记录（run_instance 的结果或读回的 JSON）
    :return: 经 JSON 往返、去掉耗时字段后的副本
    """
    r = json.loads(json.dumps(rec, ensure_ascii=False))
    for k in ("job_secs", "split"):
        r.pop(k, None)
    for k in ("secs", "replica_secs"):
        r["p2"].pop(k, None)
    r["ils"].pop("secs", None)
    for c in r["chains"]:
        c.pop("secs", None)
    return r


def diff_paths(a, b, path: str = "", out: list | None = None, limit: int = 8) -> list[str]:
    """列出两份记录取值不同的位置（最多 limit 处），供报告用"""
    out = [] if out is None else out
    if len(out) >= limit:
        return out
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b), key=str):
            if k not in a or k not in b:
                out.append(f"{path}/{k}（只在一边）")
            else:
                diff_paths(a[k], b[k], f"{path}/{k}", out, limit)
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            diff_paths(x, y, f"{path}[{i}]", out, limit)
    elif a != b:
        out.append(f"{path}：{a!r} ≠ {b!r}"[:200])
    return out


def compare(a: dict, b: dict) -> list[str]:
    """逐位比对两份记录（不含耗时字段；浮点按 repr 的文本比较）

    :return: 不同之处的说明；空列表表示逐位相同
    """
    sa, sb = strip_timing(a), strip_timing(b)
    if json.dumps(sa, sort_keys=True, ensure_ascii=False) == json.dumps(sb, sort_keys=True, ensure_ascii=False):
        return []
    return diff_paths(sa, sb) or ["JSON 文本不同"]


SPLIT_NOTE = ("补跑：任务拆到不同作业，每个任务单独一个进程；job_secs 为关键路径（第一阶段最长的任务 + 最长的一条链），"
              "与 E8 实例内并行的整例墙钟不能直接比较")


def merge(plan1: dict, results: dict, info: dict, out: Path, ref: Path | None) -> tuple[list[str], bool]:
    """组装各实例的记录：补跑与冒烟实例写到 out/records/，复现实例写到 out/repro/ 并与 E8 原记录比对

    复现实例不放进 records/：汇总时按 records/*.json 收集，放进去会与 E8 原记录重复
    :param plan1: 第一阶段计划（提供实例清单）
    :param results: {任务身份: 结果}（两个阶段合并）
    :param info: {任务身份: {"name", "wall"}}
    :param out: 输出目录
    :param ref: E8 原记录所在目录（实例名.json）；有复现实例时必须提供
    :return: (报告行, 是否全部完成且复现实例逐位相同)
    """
    lines, ok = [], True
    (out / "records").mkdir(parents=True, exist_ok=True)
    for job in plan1["jobs"]:
        name = inst_name(job)
        rec, pending = replay(job, results)
        if rec is None:
            ok = False
            lines.append(f"{name}：未完成，还缺 {len(pending)} 个任务（{', '.join(sorted({t['fn'] for t in pending}))}）")
            continue
        walls = {i["name"]: i["wall"] for i in info.values() if i["name"].startswith(name + ".s")}
        s1 = {n: w for n, w in walls.items() if ".s1." in n}
        s2 = {n: w for n, w in walls.items() if ".s2." in n}
        rec["job_secs"] = max(s1.values()) + max(s2.values())
        rec["split"] = {"note": SPLIT_NOTE, "stage1_secs": s1, "stage2_secs": s2}
        text = json.dumps(rec, ensure_ascii=False)
        msg = (f"{name}：第一阶段 {len(s1)} 个任务，最长 {max(s1.values()):.0f} s；4 条链最长 {max(s2.values()):.0f} s；"
               f"相对 P2 的改善 {rec['gain']['final']:.3f}%")
        if job in REPRO:
            (out / "repro").mkdir(parents=True, exist_ok=True)
            (out / "repro" / f"{name}.json").write_text(text, encoding="utf-8")
            ref_path = ref / f"{name}.json" if ref is not None else None
            if ref_path is None or not ref_path.is_file():
                ok = False
                msg += "；复现实例缺少 E8 原记录，无法比对"
            else:
                d = compare(json.loads(text), json.loads(ref_path.read_text(encoding="utf-8")))
                ok = ok and not d
                msg += "；与 E8 原记录逐位相同" if not d else f"；与 E8 原记录不同：{d}"
        else:
            (out / "records" / f"{name}.json").write_text(text, encoding="utf-8")
        lines.append(msg)
    return lines, ok


def run_tasks_subprocess(plan_path: Path, names: list[str], out: Path, workers: int) -> None:
    """本地模拟分作业：每个任务一个子进程（与作业一样从头导入、单独计算），同时最多 workers 个"""
    env = {**os.environ, "PYTHONHASHSEED": "0"}

    def one(name: str) -> str:
        """运行一个任务的 stage 子命令；失败时带上标准错误的末尾抛出"""
        r = subprocess.run([sys.executable, str(Path(__file__).resolve()), "stage", "--plan", str(plan_path),
                            "--task", name, "--out", str(out)], env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        if r.returncode != 0:
            raise RuntimeError(f"{name} 失败：{r.stderr[-2000:]}")
        return name

    with ThreadPoolExecutor(max(1, workers)) as ex:
        for name in ex.map(one, names):
            print(f"  完成 {name}", flush=True)


def local(jobs: list[tuple], out: Path, workers: int, ref: Path | None) -> bool:
    """local 子命令：本地走完全部步骤（每个任务一个子进程），再与实例内并行（进程池）的结果逐位比对

    :param jobs: 运行单元
    :param out: 输出目录（plan/、results/、merged/ 与报告）
    :param workers: 同时运行的子进程数，也是参照用进程池的进程数
    :param ref: E8 原记录目录（复现实例与之比对）
    :return: 是否全部逐位相同
    """
    if os.environ.get("PYTHONHASHSEED") != "0":
        raise SystemExit("请在 PYTHONHASHSEED=0 下运行（与 Actions 相同），否则参照进程池与子进程的条件不一致")
    plan_dir, res_dir = out / "plan", out / "results"
    plan1 = make_plan1(jobs)
    save_pickle(plan1, plan_dir / "plan1.pkl")
    print(f"第一阶段 {len(plan1['tasks'])} 个任务", flush=True)
    run_tasks_subprocess(plan_dir / "plan1.pkl", list(plan1["tasks"]), res_dir, workers)
    plan2, skipped = make_plan2(plan1, load_results(res_dir)[0])
    save_pickle(plan2, plan_dir / "plan2.pkl")
    print(f"第二阶段 {len(plan2['tasks'])} 个任务；跳过 {skipped or '无'}", flush=True)
    run_tasks_subprocess(plan_dir / "plan2.pkl", list(plan2["tasks"]), res_dir, workers)
    results, info = load_results(res_dir)
    lines, ok = merge(plan1, results, info, out / "merged", ref)
    with ProcessPoolExecutor(workers) as pool:
        for job in jobs:
            name = inst_name(job)
            mine = out / "merged" / ("repro" if job in REPRO else "records") / f"{name}.json"
            if not mine.is_file():
                continue
            d = compare(json.loads(mine.read_text(encoding="utf-8")), e8.run_instance(job, pool))
            ok = ok and not d
            lines.append(f"{name}：与本地实例内并行（{workers} 个进程）" + ("逐位相同" if not d else f"不同：{d}"))
    text = "\n".join(lines) + "\n"
    (out / "local_report.txt").write_text(text, encoding="utf-8", newline="\n")
    print(text)
    return ok


def write_matrix(plan: dict, path: Path) -> int:
    """作业矩阵：任务名列表写成一行 JSON，供工作流的 fromJSON 使用

    :return: 任务数
    """
    names = sorted(plan["tasks"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(names, ensure_ascii=False), encoding="utf-8", newline="\n")
    return len(names)


def main(argv=None) -> int:
    """命令行入口：plan1、stage、plan2、merge 对应工作流的各个作业，local 在本地一次走完

    :param argv: 参数列表，缺省取命令行
    :return: 进程退出码；merge 与 local 在有实例未完成或比对不一致时返回 1
    """
    ap = argparse.ArgumentParser(description="方案一 E8 补跑：按任务拆作业，结果与实例内并行逐位相同")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan1")
    p.add_argument("--set", choices=sorted(SETS), default="all")
    p.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("stage")
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--task", required=True)
    p.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("plan2")
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--results", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("merge")
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--results", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--ref", type=Path)
    p = sub.add_parser("local")
    p.add_argument("--set", choices=sorted(SETS), default="smoke")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--ref", type=Path)
    a = ap.parse_args(argv)
    if a.cmd == "plan1":
        plan = make_plan1(SETS[a.set])
        save_pickle(plan, a.out / "plan1.pkl")
        print(f"第一阶段：{len(plan['jobs'])} 个实例，{write_matrix(plan, a.out / 'matrix1.json')} 个任务")
        return 0
    if a.cmd == "stage":
        print(f"完成 {run_stage(a.plan, a.task, a.out).name}")
        return 0
    if a.cmd == "plan2":
        plan2, skipped = make_plan2(load_pickle(a.plan), load_results(a.results)[0])
        save_pickle(plan2, a.out / "plan2.pkl")
        n = write_matrix(plan2, a.out / "matrix2.json")
        (a.out / "plan2_skipped.txt").write_text("".join(s + "\n" for s in skipped), encoding="utf-8", newline="\n")
        print(f"第二阶段：{len(plan2['jobs'])} 个实例，{n} 个任务；跳过 {len(skipped)} 个实例")
        return 0
    if a.cmd == "merge":
        results, info = load_results(a.results)
        lines, ok = merge(load_pickle(a.plan), results, info, a.out, a.ref)
        text = "\n".join(lines) + "\n"
        (a.out / "fill_report.txt").write_text(text, encoding="utf-8", newline="\n")
        print(text)
        return 0 if ok else 1
    return 0 if local(SETS[a.set], a.out, a.workers, a.ref) else 1


if __name__ == "__main__":
    sys.exit(main())
