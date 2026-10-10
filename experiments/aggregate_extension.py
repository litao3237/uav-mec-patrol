"""逐块复核七方法扩展实验，保留失败、复用身份与场景层级。"""
from __future__ import annotations
import argparse
from collections import defaultdict
import csv
import hashlib
import json
import math
from pathlib import Path

from uav_mec.analysis.archive_audit import assert_audit_equivalent
from aggregate_seven_methods import CORE_METRICS, require, row_metrics, scenario_summary
from run_seven_methods import METHODS, DETERMINISTIC, PROTOCOL, execution_schedule
from run_extension import source_hashes
from manage_results import verify_recorded_file
from uav_mec.analysis.constraint_audit import audit_both_timelines
from uav_mec.analysis.experiment_snapshot import content_hash, restore_instance, restore_solution, write_json

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'outputs/current/extension'
MAIN = ROOT / 'outputs/current/main/formal'
ARCHIVED = False


def verify_job(job: dict, frozen: dict) -> tuple[list[dict], dict]:
    """重新核验变量和完整时序；复用块必须匹配冻结时登记的原件哈希。"""
    key = f"{job['study']}_{job['level']:g}_S{job['scenario']}"
    # 归档保留原路径作为来源证据，实际读入只使用明确给定的主实验目录。
    path = MAIN / f"K80_S{job['scenario']}.json" if job['reuse_source'] else WORK/'raw'/f'{key}.json'
    if ARCHIVED:
        logical = 'main/raw/' if job['reuse_source'] else 'extension/raw/'
        verify_recorded_file(path, logical + path.name)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    data = json.loads(path.read_text(encoding='utf-8'))
    require(data['complete'] and len(data['rows']) == 17, f'块不完整：{path}')
    expected_protocol = dict(PROTOCOL if job['reuse_source'] else job['protocol'])
    if not job['reuse_source']:
        # 冻结矩阵可将1写为整数；执行器argparse将level解析为浮点数。
        # 仅规范化这一已知字段，其他协议字段仍按完整内容哈希严格核对。
        expected_protocol['level'] = float(expected_protocol['level'])
    require(data['protocol_sha256'] == content_hash(expected_protocol) == content_hash(data['protocol']),
            f'协议不匹配：{path}')
    if job['reuse_source']:
        require(digest == job['reuse_sha256'], f'复用原件已变化：{path}')
    else:
        require(data['extension_source_hashes'] == frozen['source_hashes'], f'源码混用：{path}')
    instance = restore_instance(data['instance'])
    initial = restore_solution(data['initial_solution'])
    require(content_hash(instance) == data['instance_sha256'], f'实例哈希错误：{path}')
    require(content_hash(initial) == data['initial_sha256'], f'初解哈希错误：{path}')
    k, scene = job['protocol']['tasks'][0], job['scenario']
    require((data['tasks'], data['scenario_seed']) == (k, scene), f'场景归属错误：{path}')
    seeds = job['protocol']['algorithm_seeds']
    schedule = [list(v) for v in execution_schedule(k, scene, seeds)]
    require(data['execution_schedule'] == schedule and data['algorithm_seeds'] == seeds,
            f'执行顺序或种子不匹配：{path}')
    expected = {(m, a) for m in METHODS for a in ([None] if m in DETERMINISTIC else seeds)}
    seen, rows = set(), []
    for row in data['rows']:
        rowkey = row['method'], row['algorithm_seed']
        require(rowkey in expected and rowkey not in seen, f'重复或额外记录：{key} {rowkey}')
        seen.add(rowkey)
        require(row['tasks'] == k and row['scenario_seed'] == scene, f'行场景错误：{key}')
        require(row['initial_sha256'] == data['initial_sha256'], f'行初解错误：{key}')
        group = 'B/ESI' if row['method'] in METHODS[-2:] else row['method']
        require(schedule[row['group_order_index']] == [group, row['algorithm_seed']], f'行顺序错误：{key}')
        solution = restore_solution(row['solution'])
        require(content_hash(solution) == row['solution_sha256'], f'方案哈希错误：{key}')
        resource = row['resources']
        for number in (1, 2):
            stage = row[f'stage{number}']
            original = resource['stage1_values'] if number == 1 else resource['diagnostics'].get('stage2_raw_values')
            status = resource['diagnostics'].get(f'stage{number}_status', resource['status'] if number == 1 else 'not_run')
            require(stage['status'] == status and stage['available'] == bool(original), f'阶段快照错误：{key}')
            # 失败结果没有能耗锚点，先检查可用性，不能对空能耗相加后再判断失败。
            if not stage['available']:
                require(not stage['qualified'] and stage['values'] is None, f'缺变量却合格：{key}')
                continue
            require(content_hash(stage['values']) == content_hash(original), f'阶段变量不符：{key}')
            limit = None
            if number == 2:
                require(row['stage1']['qualified'], f'不合格第一阶段进入二次优化：{key}')
                limit = resource['energy_stage1_j'] + resource['diagnostics']['energy_tolerance_j']
            audit = audit_both_timelines(instance, solution, stage['values'], energy_limit_j=limit)
            assert_audit_equivalent(audit, stage['audit'], f'{key}/{rowkey}/stage{number}')
            require(stage['qualified'] == (status == 'optimal' and all(v['passed'] for v in audit.values())),
                    f'阶段资格不符：{key}')
        t = row['timing']
        require(all(math.isfinite(v) and v >= 0 for v in t.values()), f'计时非法：{key}')
        require(math.isclose(t['total_to_resources_s'], sum(t[n] for n in
                ('initialization_s', 'search_s', 'resource_recompute_s')), abs_tol=1e-9), f'计时分项不符：{key}')
        require(math.isclose(t['total_with_audit_s'], t['total_to_resources_s']+t['independent_audit_s'],
                             abs_tol=1e-9), f'验收总计时不符：{key}')
        rows.append({'study':job['study'], 'level':job['level'], 'tasks':k, 'scenario_seed':scene,
                     'method':row['method'], 'algorithm_seed':row['algorithm_seed'],
                     'reused':bool(job['reuse_source']), 'source':path.name,
                     'metrics':row_metrics(row)})
    require(seen == expected, f'缺少方法记录：{key}')
    lookup = {(r['method'], r['algorithm_seed']):r for r in data['rows']}
    for seed in seeds:
        require(lookup['ESI-ALNS',seed]['diagnostics']['exploration_sha256'] ==
                lookup['B-ALNS',seed]['solution_sha256'], f'B/ESI共享起点错误：{key}')
        require(lookup['RGA-MR',seed]['diagnostics']['ga_evaluations'] > 0, f'GA未真实评价：{key}')
    return rows, {'study':job['study'], 'level':job['level'], 'scenario_seed':scene,
                  'file':path.name, 'sha256':digest, 'reused':bool(job['reuse_source']),
                  'instance_sha256':data['instance_sha256']}


def summarize(rows: list[dict]) -> dict:
    """共同有效块与自身有效集分别汇总；确定性复用不增加独立样本数。"""
    counts, conditional, common = [], [], []
    groups = defaultdict(list)
    for row in rows:
        groups[row['study'],row['level']].append(row)
    metrics = sorted(CORE_METRICS | {m for r in rows for m in r['metrics']})
    for (study, level), records in groups.items():
        base = {'study':study, 'level':level}
        lookup = {(r['scenario_seed'],r['algorithm_seed'],r['method']):r for r in records}
        for method in METHODS:
            selected = [r for r in records if r['method']==method]
            counts.append({**base,'method':method,'observed':len(selected),
                           'stage1_qualified':sum(int(r['metrics']['stage1_qualified_rate']) for r in selected),
                           'both_stages_qualified':sum(int(r['metrics']['both_stages_qualified_rate']) for r in selected)})
            for metric in metrics:
                obs = [{'scenario_seed':r['scenario_seed'],'value':r['metrics'][metric]}
                       for r in selected if metric in r['metrics']]
                conditional.append({**base,'method':method,'metric':metric,**scenario_summary(obs)})
        for metric in metrics:
            matched = {m:[] for m in METHODS}
            for scene in [45,46,47]:
                for seed in [100,101,102]:
                    block = {m:lookup[scene,None if m in DETERMINISTIC else seed,m] for m in METHODS}
                    if all(metric in r['metrics'] for r in block.values()):
                        for m,r in block.items():
                            matched[m].append({'scenario_seed':scene,'value':r['metrics'][metric]})
            for method,obs in matched.items():
                common.append({**base,'method':method,'metric':metric,**scenario_summary(obs)})
    return {'counts':counts,'method_conditional_summaries':conditional,'all_method_common_summaries':common}


def main():
    global WORK, MAIN, ARCHIVED
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir', type=Path, required=True)
    parser.add_argument('--main-dir', type=Path, required=True)
    parser.add_argument('--protocol', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--archived', action='store_true', help='只接受发布清单内的原始记录')
    args = parser.parse_args()
    WORK, MAIN, ARCHIVED = args.input_dir, args.main_dir, args.archived
    frozen = json.loads(args.protocol.read_text(encoding='utf-8'))
    if ARCHIVED:
        expected = json.loads((ROOT/'results/extension/frozen_protocol.json').read_text(encoding='utf-8'))
        require(frozen == expected, '归档协议与发布记录不符')
    else:
        require(frozen['source_hashes'] == source_hashes(), '冻结后源码或输入变化，停止聚合')
    rows, sources = [], []
    for job in frozen['jobs']:
        part, source = verify_job(job, frozen)
        rows.extend(part); sources.append(source)
        print(f"复核通过 {job['study']} {job['level']} S{job['scenario']}", flush=True)
    require(len(rows)==408 and sum(not r['reused'] for r in rows)==306, '总记录数不符')
    report = {'integrity_gate_passed':True,'observed_panel_records':408,'new_records':306,
              'reused_panel_records':102,'sources':sources,'protocol':frozen,**summarize(rows),
              'interpretation':'场景内种子平均后场景等权；复用主实验不是新增独立重复。GIS为同一地图的三个负载场景。共同集为空时不产生能耗点；条件均值不能直接作总体排名。'}
    write_json(args.output, report)
    columns = ['study','level','tasks','scenario_seed','method','algorithm_seed','reused','source']
    metrics = sorted(CORE_METRICS | {m for r in rows for m in r['metrics']})
    with args.output.with_suffix('.csv').open('w',encoding='utf-8',newline='') as stream:
        writer = csv.DictWriter(stream,fieldnames=columns+metrics); writer.writeheader()
        writer.writerows({**{k:r[k] for k in columns},**r['metrics']} for r in rows)
    print('408条图表记录（306条新计算）全部复核通过。')


if __name__ == '__main__':
    main()
