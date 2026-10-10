"""复核软端到端预算实验，按场景汇总能耗差并同时报告超时和合格率。"""
import argparse
from collections import defaultdict
import json
import math
import hashlib
from pathlib import Path
from statistics import mean
import numpy as np

from run_budget_check import PROTOCOL
from manage_results import verify_recorded_file
from uav_mec.analysis.archive_audit import assert_audit_equivalent
from uav_mec.analysis.constraint_audit import audit_both_timelines
from uav_mec.analysis.experiment_snapshot import content_hash,restore_instance,restore_solution,write_json

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'outputs/current/budget'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--archived', action='store_true')
    args = parser.parse_args()
    frozen = json.loads((ROOT/'results/budget/frozen_source_hashes.json').read_text(encoding='utf-8')) if args.archived else None
    rows=[];seen=set();hashes=set();sources=[]
    for p in sorted(args.input_dir.glob('K*_S*.json')):
        data=json.loads(p.read_text(encoding='utf-8'))
        assert data['complete'] and not data['pilot'] and data['protocol']==PROTOCOL,p
        hashes.add(content_hash(data['source_hashes']))
        sources.append({'file':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
        # 历史记录校验原时点身份和发布字节；新运行则必须与当前源码一致。
        if args.archived:
            verify_recorded_file(p, 'budget/raw/' + p.name)
            assert data['source_hashes'] == frozen, p
        else:
            for name,digest in data['source_hashes'].items():
                source=ROOT / name.replace('\\', '/')
                assert hashlib.sha256(source.read_bytes()).hexdigest()==digest,name
        instance=restore_instance(data['instance'])
        assert content_hash(instance)==data['instance_sha256']
        for row in data['rows']:
            key=(row['tasks'],row['scenario_seed'],row['algorithm_seed'],row['method'])
            assert key not in seen,key
            seen.add(key)
            solution=restore_solution(row['solution']);resource=row['resources']
            assert content_hash(solution)==row['solution_sha256']
            for stage in (1,2):
                saved=row[f'stage{stage}']
                values=resource['stage1_values'] if stage==1 else resource['diagnostics'].get('stage2_raw_values')
                status=resource['diagnostics'].get(f'stage{stage}_status',resource['status'] if stage==1 else 'not_run')
                assert saved['status']==status and saved['available']==bool(values),key
                # 失败能耗在JSON中为null；无阶段变量时先核对失败状态，不能构造None+容差。
                if not values:
                    assert not saved['qualified'] and saved['values'] is None and saved['audit'] is None,key
                    continue
                assert content_hash(values)==content_hash(saved['values']),key
                limit=None
                if stage==2:
                    assert row['stage1']['qualified'] and resource['energy_stage1_j'] is not None,key
                    limit=resource['energy_stage1_j']+resource['diagnostics'].get('energy_tolerance_j',0.)
                audit=audit_both_timelines(instance,solution,values,energy_limit_j=limit)
                assert_audit_equivalent(audit,saved['audit'],str(key))
                assert saved['qualified']==(status=='optimal' and all(a['passed'] for a in audit.values())),key
            assert math.isfinite(row['measured_end_to_end_s']) and row['measured_end_to_end_s']>=0
            budget=PROTOCOL['budget_s'][str(row['tasks'])]
            assert row['nominal_end_to_end_budget_s']==budget,key
            assert row['within_nominal_budget']==(row['measured_end_to_end_s']<=budget),key
            assert math.isclose(row['overrun_s'],max(0.,row['measured_end_to_end_s']-budget),abs_tol=1e-9),key
            assert row['measured_end_to_end_s']>=row['timing']['total_with_audit_s'],key
            rows.append(row)
    expected={(k,s,a,m) for k in PROTOCOL['tasks'] for s in PROTOCOL['scenarios']
              for a in PROTOCOL['algorithm_seeds'] for m in PROTOCOL['methods']}
    assert seen==expected and len(hashes)==1,(len(seen),len(expected))
    look={(r['tasks'],r['scenario_seed'],r['algorithm_seed'],r['method']):r for r in rows}
    paired=[];coverage=[]
    for k in PROTOCOL['tasks']:
        scene_values=defaultdict(list);pairs=[]
        for s in PROTOCOL['scenarios']:
            for a in PROTOCOL['algorithm_seeds']:
                base=look[k,s,a,'B-ALNS'];esi=look[k,s,a,'ESI-ALNS']
                if all(r['stage1']['qualified'] and r['stage2']['qualified'] for r in [base,esi]):
                    b=base['stage1']['audit']['saved']['metrics']['energy_j']
                    e=esi['stage1']['audit']['saved']['metrics']['energy_j']
                    gain=100*(b-e)/b
                    scene_values[s].append(gain);pairs.append({'scenario':s,'seed':a,'gain_pct':gain,'energy_difference_j':b-e})
        values=np.array([mean(v) for v in scene_values.values()])
        ci=None
        if len(values)>=2:
            rng=np.random.default_rng(20261009)
            ci=np.quantile(rng.choice(values,(10000,len(values)),replace=True).mean(axis=1),[.025,.975]).tolist()
        paired.append({'tasks':k,'nominal_budget_s':PROTOCOL['budget_s'][str(k)],'paired_runs':len(pairs),
            'independent_scenarios':len(values),'mean_saving_pct':float(values.mean()) if len(values) else None,
            'descriptive_95_ci':ci,'pairs':pairs,'per_scenario':dict(scene_values)})
        for method in PROTOCOL['methods']:
            group=[r for r in rows if r['tasks']==k and r['method']==method]
            coverage.append({'tasks':k,'method':method,'planned':len(group),
                'both_qualified':sum(r['stage1']['qualified'] and r['stage2']['qualified'] for r in group),
                'within_budget_and_qualified':sum(r['within_nominal_budget'] and r['stage1']['qualified'] and r['stage2']['qualified'] for r in group),
                'mean_end_to_end_s':mean(r['measured_end_to_end_s'] for r in group),
                'overrun_count':sum(r['overrun_s']>0 for r in group),
                'mean_overrun_s':mean(r['overrun_s'] for r in group),'max_overrun_s':max(r['overrun_s'] for r in group)})
    report={'complete':True,'integrity_gate_passed':True,'records':len(rows),'protocol':PROTOCOL,
        'paired':paired,'coverage':coverage,'sources':sources,
        'source_hashes_verified':True,'source_identity':'recorded' if args.archived else 'current',
        'interpretation':'相同名义预算；实际时间可超出，所有超时均保留。配对差按场景汇总，不是硬实时或完全等耗时证明。'}
    write_json(args.output,report)
    print(json.dumps({'records':len(rows),'paired':[{k:v for k,v in r.items() if k not in ['pairs','per_scenario']} for r in paired],
                      'coverage':coverage},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
