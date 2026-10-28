"""方案一 E2、E6 补跑三个基线（就近贪心 B1、静态分簇 B3、截止驱动 B4），使这两组图与主对比用同一组 7 种方法

参考论文的对比图都用同一组方法（见 38_ 的分析），而 E2、E6 当初只跑了 B0、B2、P1、P2。补跑沿用原实验的实例生成与
求解代码（求解器同 scheme1-exp-v1），每个实例另跑一次两阶段 B2，要求与原记录逐位相同，确认实例与原实验一致

- shard：运行一个分片（E2 中 ε 的另外 7 档 280 个实例，E6 的 1120 个实例；ε = 0.1、0.25 的 E2 实例与 E1 相同，E1 已有这三个基线）
- summary：检查（实例齐全、方案可行、分配无误、B2 与参考值逐位相同、同一航线上 B2 不劣于 B1 与 B4）与各档均值
- ref：在本地从 E1–E3、E6 的产物写出 B2 的参考值 scheme1_supp_b2_ref.csv（随代码提交，Actions 上据此核对）
- figures：在本地把补跑记录并入原实验的结果，用原作图函数画 7 种方法的 F12、任务时长增幅、F16、F17、X11–X14

用法：
  python experiments/scheme1_supp.py shard --shard 0 --shards 4 --workers 4 --out 目录
  python experiments/scheme1_supp.py summary --inputs 分片目录 --out 目录
  python experiments/scheme1_supp.py ref --e1e3 E1–E3产物目录 --e6 E6产物目录
  python experiments/scheme1_supp.py figures --supp 补跑产物目录 --e1e3 E1–E3产物目录 --e6 E6产物目录 --out 目录
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "experiments"))

import scheme1_e6 as e6  # noqa: E402
import scheme1_experiments as e123  # noqa: E402

from uav_mec.scheme1 import load_scheme1_params, make_instance, run_methods, summary_rows  # noqa: E402

CONFIG = ROOT / "configs" / "v27_timeliness.yaml"
REF = ROOT / "experiments" / "scheme1_supp_b2_ref.csv"
SUPP_METHODS = ("B2", "B1", "B3", "B4")      # B2 只用来核对实例与原实验相同，图中用原实验的 B2
NEW_METHODS = ("B1", "B3", "B4")
E2_EXTRA = tuple(e for e in e123.E2_EPS if e not in e123.E1_EPS)
KEY_FIELDS = ("exp", "factor", "level", "layout", "seed", "eps")


def jobs() -> list[tuple]:
    """运行单元 (实验, 因素, 档位, 布点, 种子, ε)：E2 的因素与档位记为 "-"，E6 沿用其运行单元"""
    out = [("E2", "-", "-", lay, s, e) for lay in e123.LAYOUTS for s in e123.SEEDS for e in E2_EXTRA]
    out += [("E6", f, lv, lay, s, e) for f, lv, lay, s, e in e6.jobs()]
    return out


def key_of(meta: dict) -> tuple:
    """实例的键：(实验, 因素, 档位, 布点, 种子, ε)"""
    return tuple(meta[k] for k in KEY_FIELDS)


def shard_jobs(shard: int, shards: int) -> list[tuple]:
    """轮流分片：三个基线都很快，各实例耗时相近"""
    return [j for i, j in enumerate(jobs()) if i % shards == shard]


def run_job(job: tuple) -> dict:
    """生成与原实验相同的实例并运行 SUPP_METHODS

    实例参数、机数与随机种子标签都与原实验相同（E2 见 scheme1_experiments.run_job，E6 见 scheme1_e6.run_job）；
    这几个基线本身不用随机数。记录不保存几何信息，作图只用汇总指标
    :param job: (实验, 因素, 档位, 布点, 种子, ε)
    :return: 记录
    """
    exp, factor, level, layout, seed, eps = job
    if exp == "E2":
        params, m, n = load_scheme1_params(str(CONFIG)), e123.M_UAV, e123.E2_N
    else:
        (params, m), n = e6.variant(factor, level), e6.N
    inst, groups = make_instance(layout, n, m, seed, params)
    t0 = time.perf_counter()
    rec = run_methods(inst, groups, eps, methods=SUPP_METHODS, tag=(layout, n, m, seed, eps))
    rec.pop("geometry", None)
    rec["meta"] = {"exp": exp, "factor": factor, "level": level, "layout": layout, "n": n, "m": m, "seed": seed,
                   "eps": eps}
    rec["job_secs"] = time.perf_counter() - t0
    return rec


def record_name(meta: dict) -> str:
    return "S{exp}_{factor}_{level}_{layout}_s{seed}_e{eps}".format(**meta)


def run_jobs(job_list: list[tuple], out: Path, workers: int, log_name: str) -> None:
    """运行一组单元，逐个写记录 JSON、汇总行 CSV 与耗时日志；单进程时不开进程池（测试中进程池无法按名导入）"""
    from scheme1_plots import write_rows

    (out / "records").mkdir(parents=True, exist_ok=True)
    rows, log, t0 = [], [], time.perf_counter()

    def write(rec):
        name = record_name(rec["meta"])
        (out / "records" / f"{name}.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
        rows.extend(summary_rows(rec, rec["meta"]))
        log.append(f"{name}\t{rec['job_secs']:.1f}")

    if workers <= 1:
        for j in job_list:
            write(run_job(j))
    else:
        with ProcessPoolExecutor(workers) as ex:
            for rec in ex.map(run_job, job_list):
                write(rec)
    log.append(f"total\t{time.perf_counter() - t0:.1f}")
    write_rows(out / f"rows_{log_name}.csv", rows)
    (out / f"log_{log_name}.txt").write_text("\n".join(log) + "\n", encoding="utf-8", newline="\n")


def load_records(inputs) -> list[dict]:
    recs = []
    for d in inputs:
        for p in sorted(Path(d).rglob("records/*.json")):
            recs.append(json.loads(p.read_text(encoding="utf-8")))
    return recs


# ---------------------------------------------------------------------------
# 参考值与汇总
# ---------------------------------------------------------------------------

def _norm_key(exp: str, factor: str, level: str, layout: str, seed, eps) -> tuple:
    """CSV 读入的字段统一成与记录 meta 相同的类型（种子为整数、ε 为浮点数，因素与档位保持字符串）"""
    return exp, factor, level, layout, int(seed), float(eps)


def write_ref(e1e3: Path, e6_dir: Path, out: Path = REF) -> int:
    """从原实验的汇总行写出 B2 的目标（浮点数按 repr 写出，读回逐位不变），供补跑核对

    :param e1e3: E1–E3 汇总产物目录（含 E2_rows.csv）
    :param e6_dir: E6 汇总产物目录（含 E6_rows.csv）
    :return: 写出的行数
    """
    rows = []
    with open(e1e3 / "E2_rows.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["method"] == "B2" and float(r["eps"]) in E2_EXTRA:
                rows.append(("E2", "-", "-", r["layout"], int(r["seed"]), float(r["eps"]), r["obj"]))
    with open(e6_dir / "E6_rows.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["method"] == "B2":
                rows.append(("E6", r["factor"], r["level"], r["layout"], int(r["seed"]), float(r["eps"]), r["obj"]))
    rows.sort()
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow([*KEY_FIELDS, "b2_obj"])
        w.writerows(rows)
    return len(rows)


def load_ref(path: Path = REF) -> dict:
    """B2 的参考目标：{实例键: 目标}"""
    if not path.is_file():
        return {}
    with open(path, newline="", encoding="utf-8") as f:
        return {_norm_key(*(r[k] for k in KEY_FIELDS)): float(r["b2_obj"]) for r in csv.DictReader(f)}


def checks(recs: list[dict], expected: int, ref: dict) -> list[str]:
    """写定的检查：实例齐全；方案可行、分配无误；B2 与原实验逐位相同；同一航线上精确停靠的 B2 不劣于 B1、B4"""
    problems = []
    if len(recs) != expected or len({key_of(r["meta"]) for r in recs}) != len(recs):
        problems.append(f"实例数 {len(recs)}/{expected}（或有重复）")
    bad = [record_name(r["meta"]) for r in recs for m in SUPP_METHODS
           if not (r["methods"][m]["summary"]["feasible"] and r["methods"][m]["summary"]["assigned_once"])]
    if bad:
        problems.append(f"不可行或分配有误 {bad[:5]}")
    miss = [record_name(r["meta"]) for r in recs if key_of(r["meta"]) not in ref]
    diff = [record_name(r["meta"]) for r in recs if key_of(r["meta"]) in ref
            and r["methods"]["B2"]["summary"]["obj"] != ref[key_of(r["meta"])]]
    if miss:
        problems.append(f"没有 B2 参考值 {len(miss)} 个 {miss[:3]}")
    if diff:
        problems.append(f"B2 与原实验不同 {len(diff)} 个 {diff[:3]}")
    order = [record_name(r["meta"]) for r in recs for m in ("B1", "B4")
             if r["methods"]["B2"]["summary"]["obj"] > r["methods"][m]["summary"]["obj"] + 1e-9]
    if order:
        problems.append(f"B2 劣于同航线的 B1 或 B4 {order[:5]}")
    return problems


def table_lines(recs: list[dict]) -> list[str]:
    """各档（实验 × 因素 × 档位 × 布点 × ε）四个方法平均归一化 AoI 的均值"""
    cells: dict = {}
    for r in recs:
        m = r["meta"]
        cells.setdefault((m["exp"], m["factor"], m["level"], m["layout"], m["eps"]), []).append(r)
    lines = ["  实验  因素       档位      布点      ε      实例   " + "   ".join(f"{x:>6}" for x in SUPP_METHODS)]
    for (exp, f, lv, lay, eps), rs in sorted(cells.items(), key=lambda kv: (kv[0][:4], kv[0][4])):
        means = [statistics.fmean(r["methods"][x]["summary"]["norm_aoi"] for r in rs) for x in SUPP_METHODS]
        lines.append(f"  {exp:<4}  {f:<9}  {lv:<8}  {lay:<8}  {eps:<5}  {len(rs):>4}   "
                     + "   ".join(f"{v:6.4f}" for v in means))
    return lines


def summarize(inputs, out: Path, expected: int | None = None, ref_path: Path = REF) -> bool:
    """汇总补跑：检查与各档均值写 summary.txt，汇总行写 CSV；有检查不通过时返回 False"""
    import scheme1_plots as sp

    recs = load_records(inputs)
    expected = len(jobs()) if expected is None else expected
    problems = checks(recs, expected, load_ref(ref_path))
    rows = [row for r in recs for row in summary_rows(r, r["meta"])]
    out.mkdir(parents=True, exist_ok=True)
    sp.write_rows(out / "supp_rows.csv", rows)
    fp = sp.result_fingerprint([{k: v for k, v in r.items() if k != "secs"} for r in rows])
    lines = [f"## E2、E6 补跑三个基线：{len(recs)}/{expected} 个实例（E2 的 ε ∈ {{{', '.join(f'{e:g}' for e in E2_EXTRA)}}}，"
             f"E6 全部档位）；结果指纹 {fp}", ""]
    lines += table_lines(recs)
    lines += ["", "检查：" + ("全部通过（实例齐全、方案可行、分配无误、B2 与原实验逐位相同、B2 不劣于同航线的 B1 与 B4）"
                             if not problems else "；".join(problems))]
    (out / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(lines))
    return not problems


# ---------------------------------------------------------------------------
# 本地并入原实验的结果并作图
# ---------------------------------------------------------------------------

def merge_e6(orig: list[dict], supp: list[dict]) -> list[dict]:
    """把补跑的三个基线并入 E6 原记录（就地修改并返回 orig）

    :raises ValueError: 某个原实例没有补跑记录，或补跑的 B2 与原记录不同
    """
    by = {key_of(dict(r["meta"], exp="E6")): r for r in supp if r["meta"]["exp"] == "E6"}
    for r in orig:
        s = by.get(key_of(dict(r["meta"], exp="E6")))
        if s is None or s["methods"]["B2"]["summary"]["obj"] != r["methods"]["B2"]["summary"]["obj"]:
            raise ValueError(f"E6 补跑缺失或 B2 不同：{r['meta']}")
        r["methods"].update({m: s["methods"][m] for m in NEW_METHODS})
    return orig


def merge_e2(e2_rows: list[dict], e1_rows: list[dict], supp: list[dict]) -> list[dict]:
    """E2 的全部 7 种方法的汇总行：原 E2 行 + E1 中同一批实例（N = 50、ε = 0.1、0.25）的三个基线 + 补跑的三个基线

    :raises ValueError: 补跑的 B2 与原 E2 行不同
    """
    b2 = {(r["layout"], int(r["seed"]), r["eps"]): r["obj"] for r in e2_rows if r["method"] == "B2"}
    rows = list(e2_rows)
    rows += [dict(r, exp="E2") for r in e1_rows
             if r["method"] in NEW_METHODS and int(r["n"]) == e123.E2_N and r["eps"] in e123.E1_EPS]
    for s in supp:
        m = s["meta"]
        if m["exp"] != "E2":
            continue
        if s["methods"]["B2"]["summary"]["obj"] != b2.get((m["layout"], m["seed"], m["eps"])):
            raise ValueError(f"E2 补跑的 B2 与原实验不同：{m}")
        rows += [row for row in summary_rows(s, dict(m, exp="E2")) if row["method"] in NEW_METHODS]
    return rows


def figures(supp_dirs, e1e3: Path, e6_dir: Path, out: Path) -> list[Path]:
    """并入原实验的结果，画 7 种方法的 E2（F12、任务时长增幅等）与 E6（F16、F17、X11–X14）的图，图名与原实验相同

    :param supp_dirs: 补跑产物目录（含 records/）
    :param e1e3: E1–E3 汇总产物目录（含 E1_rows.csv、E2_rows.csv）
    :param e6_dir: E6 汇总产物目录（含 records/）
    :param out: 输出目录，图写在 figures/zh 与 figures/en 下
    :return: 写出的图
    """
    import scheme1_plots as sp

    supp = load_records(supp_dirs)
    e2 = merge_e2(sp.read_rows(e1e3 / "E2_rows.csv"), sp.read_rows(e1e3 / "E1_rows.csv"), supp)
    recs6 = merge_e6(e6.load_records([e6_dir]), supp)
    out.mkdir(parents=True, exist_ok=True)
    sp.write_rows(out / "E2_rows_7methods.csv", e2)
    files: list[Path] = []
    for lang in ("zh", "en"):
        sp.setup(lang)
        d = out / "figures" / lang
        files += e123.figures_e2(e2, d, lang, methods=sp.METHOD_ORDER)
        for f in e6.FACTORS:
            if f == "freshness":
                files += sp.save(e6.fig_freshness(recs6, "norm_aoi", lang, sp.METHOD_ORDER), d, "E6_F17_freshness_norm_aoi")
                files += sp.save(e6.fig_freshness(recs6, "on_time_rate", lang, sp.METHOD_ORDER), d,
                                 "E6_F17_freshness_on_time")
            else:
                files += sp.save(e6.fig_factor_lines(recs6, f, lang, sp.METHOD_ORDER), d, e6.FIG_NAMES[f])
    return files


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="方案一 E2、E6 补跑三个基线")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("shard")
    p.add_argument("--shard", type=int, required=True)
    p.add_argument("--shards", type=int, required=True)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("summary")
    p.add_argument("--inputs", type=Path, nargs="+", required=True)
    p.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("ref")
    p.add_argument("--e1e3", type=Path, required=True)
    p.add_argument("--e6", type=Path, required=True)
    p = sub.add_parser("figures")
    p.add_argument("--supp", type=Path, nargs="+", required=True)
    p.add_argument("--e1e3", type=Path, required=True)
    p.add_argument("--e6", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    if a.cmd == "shard":
        run_jobs(shard_jobs(a.shard, a.shards), a.out, a.workers, f"S{a.shard}")
        return 0
    if a.cmd == "summary":
        return 0 if summarize(a.inputs, a.out) else 1
    if a.cmd == "ref":
        print(f"B2 参考值：{write_ref(a.e1e3, a.e6)} 行，写入 {REF}")
        return 0
    files = figures(a.supp, a.e1e3, a.e6, a.out)
    print(f"图：{len(files) // 2} 张（各有 PDF 与 PNG），中英文各一套")
    return 0


if __name__ == "__main__":
    sys.exit(main())
