"""统一读取正式实验数据，校验独立样本、严格筛选及汇总精度。"""
from __future__ import annotations

import csv
from decimal import Decimal
import json
import math
from pathlib import Path
from statistics import mean, stdev

from prepare_experiment_data import DATA, ROOT, digest, preserve_existing, write_json


def load_csv(name: str) -> list[dict[str, str]]:
    with (ROOT/'paper_results'/f'{name}.csv').open(encoding='utf-8',newline='') as file:
        return list(csv.DictReader(file))


def number(row: dict, key: str) -> float:
    """缺失值保持 NaN，禁止把未获得严格解的指标补成零。"""
    value=row[key]
    return float(value) if value not in ('',None) else math.nan


def strict(method: dict) -> bool:
    return method['stage1_status']=='optimal' and method.get('energy_j') is not None and math.isfinite(method['energy_j'])


def dense_strict(row: dict, method: str) -> bool:
    prefix='base' if method=='generic' else 'hybrid'
    return row[f'{prefix}_stage1_status']=='optimal' and row[f'{prefix}_cvx_feasible'] and row[f'{prefix}_cvx_energy_j'] is not None


def unique(rows: list[dict], keys: tuple[str,...]) -> None:
    seen=set()
    for row in rows:
        key=tuple(row[k] for k in keys)
        if key in seen: raise ValueError(f'重复运行记录：{keys}={key}')
        seen.add(key)


def deterministic_rows(rows: list[dict], method: str) -> list[dict]:
    """确定性基线按场景去重，同时检查不同算法种子下重复记录确实一致。"""
    result={}
    for row in rows:
        key=row['scenario_seed']
        if key in result:
            a,b=result[key][method],row[method]
            if a['stage1_status']!=b['stage1_status']:
                raise ValueError(f'确定性方法状态不一致：{method}/S{key}')
            if strict(a) and not math.isclose(a['energy_j'],b['energy_j'],rel_tol=1e-10,abs_tol=1e-5):
                raise ValueError(f'确定性方法能耗不一致：{method}/S{key}')
        else: result[key]=row
    return [result[k] for k in sorted(result)]


def sample_std(values: list[float]) -> float:
    if len(values)<2: raise ValueError('标准差至少需要两个真实运行值。')
    return stdev(values)


class ExperimentData:
    """聚合接口只暴露已验证的数据；绘图不再自行拼接不同版本的运行记录。"""
    def __init__(self):
        preserve_existing()
        manifest=json.loads((DATA/'experiment_sources.json').read_text(encoding='utf-8'))
        self.raw={}
        for name,record in manifest['sources'].items():
            path=ROOT/record['json_path']
            if digest(path.read_bytes())!=record['json_sha256']:
                raise ValueError(f'正式数据快照已改变：{name}')
            self.raw[name]=json.loads(path.read_text(encoding='utf-8'))
        self.tables={p.stem:load_csv(p.stem) for p in (ROOT/'paper_results').glob('*.csv')}
        with (DATA/'main_baseline_8x3.csv').open(encoding='utf-8',newline='') as file:
            self.main8x3=list(csv.DictReader(file))
        unique(self.main8x3,('K','scenario_seed','algorithm_seed'))
        self.checks=[]
        for name in ('dense','baseline','ga','geography'):
            unique(self.raw[name]['rows'],('K','scenario_seed','algorithm_seed') if name=='dense' else ('scenario_seed','algorithm_seed'))
        unique(self.raw['strong']['rows'],('scenario_seed','mode','algorithm_seed'))
        self.validate()

    def compare(self,actual:float,printed:str,label:str) -> None:
        if printed=='': return
        expected=Decimal(printed)
        tolerance=float(Decimal('0.5')*(Decimal(10)**expected.as_tuple().exponent))+1e-10
        if not math.isfinite(actual) or abs(actual-float(expected))>tolerance:
            raise ValueError(f'与正式 CSV 不一致：{label}，重算={actual}，CSV={printed}，容差={tolerance}')
        self.checks.append({'metric':label,'computed':actual,'published':float(expected),'tolerance':tolerance})

    def dense_rows(self,k:int) -> list[dict]:
        return sorted([r for r in self.raw['dense']['rows'] if r['K']==k],key=lambda r:(r['scenario_seed'],r['algorithm_seed']))

    def dense_pairs(self,k:int) -> list[dict]:
        return [
            {
                'scenario_seed':r['scenario_seed'],
                'algorithm_seed':r['algorithm_seed'],
                'generic_j':r['base_cvx_energy_j'],
                'hybrid_j':r['hybrid_cvx_energy_j'],
            }
            for r in self.dense_rows(k)
            if dense_strict(r,'generic') and dense_strict(r,'hybrid')
        ]

    def main_rows(self,k:int) -> list[dict[str,str]]:
        return sorted(
            [r for r in self.main8x3 if int(r['K'])==k],
            key=lambda r:(int(r['scenario_seed']),int(r['algorithm_seed']))
        )

    def pairs(self,k:int|None=None) -> list[dict]:
        if k is None:
            source=self.raw['geography']['rows']
            return [{'scenario_seed':r['scenario_seed'],'algorithm_seed':r['algorithm_seed'],
                     'generic_j':r['generic_alns']['energy_j'],'hybrid_j':r['hybrid']['energy_j']}
                    for r in sorted(source,key=lambda r:(r['scenario_seed'],r['algorithm_seed']))
                    if strict(r['generic_alns']) and strict(r['hybrid'])]
        if k in (50,80):
            return [
                {
                    'scenario_seed':int(r['scenario_seed']),
                    'algorithm_seed':int(r['algorithm_seed']),
                    'generic_j':float(r['B_ALNS_energy_j']),
                    'hybrid_j':float(r['ESI_ALNS_energy_j']),
                }
                for r in self.main_rows(k)
                if r['B_ALNS_status']=='optimal'
                and r['ESI_ALNS_status']=='optimal'
                and r['B_ALNS_energy_j']!=''
                and r['ESI_ALNS_energy_j']!=''
            ]
        return [{'scenario_seed':r['scenario_seed'],'algorithm_seed':r['algorithm_seed'],
                 'generic_j':r['base_cvx_energy_j'],'hybrid_j':r['hybrid_cvx_energy_j']}
                for r in self.dense_rows(k) if dense_strict(r,'generic') and dense_strict(r,'hybrid')]

    def baseline_values(self,method:str,k:int=50) -> list[float]:
        mapping={
            'greedy_repair':('GR_MR_status','GR_MR_energy_j'),
            'nearest_mec':('FTR_NM_status','FTR_NM_energy_j'),
            'ga':('RGA_MR_status','RGA_MR_energy_j'),
            'generic_alns':('B_ALNS_status','B_ALNS_energy_j'),
            'hybrid':('ESI_ALNS_status','ESI_ALNS_energy_j'),
        }
        status_key,energy_key=mapping[method]
        rows=self.main_rows(k)
        if method in ('greedy_repair','nearest_mec'):
            by_scenario={}
            for r in rows:
                by_scenario.setdefault(r['scenario_seed'],r)
            rows=[by_scenario[key] for key in sorted(by_scenario,key=int)]
        return [
            float(r[energy_key]) for r in rows
            if r[status_key]=='optimal' and r[energy_key]!=''
        ]

    def validate(self) -> None:
        """重算已有逐次记录可支持的全部主要汇总，并逐列核对 CSV 舍入精度。"""
        for summary in self.tables['dense_workload']:
            k=int(summary['K']); rows=self.dense_rows(k)
            g=[r for r in rows if dense_strict(r,'generic')]
            h=[r for r in rows if dense_strict(r,'hybrid')]
            pairs=self.dense_pairs(k)
            metrics={'runs':len(rows),'generic_strict':len(g),'hybrid_strict':len(h),
                'generic_energy_mean_j':mean(r['base_cvx_energy_j'] for r in g),
                'hybrid_energy_mean_j':mean(r['hybrid_cvx_energy_j'] for r in h),
                'hybrid_gain_mean_pct':mean(100*(p['generic_j']-p['hybrid_j'])/p['generic_j'] for p in pairs),
                'offload_ratio_mean':mean(r['hybrid_solution']['offloaded']/r['K'] for r in h),
                'contacts_per_uav_mean':mean(r['hybrid_solution']['contacts']/r['M'] for r in h),
                'route_distance_km_mean':mean(r['hybrid_solution']['distance_m']/1000 for r in h),
                'runtime_mean_s':mean(r['total_runtime_s'] for r in rows)}
            for key,value in metrics.items(): self.compare(value,summary[key],f'dense/K{k}/{key}')
        method_names={'GR-MR':'greedy_repair','FTR-NM':'nearest_mec',
            'RGA-MR':'ga','B-ALNS':'generic_alns','ESI-ALNS':'hybrid'}
        for row in self.tables['baseline_summary']:
            k=int(row['K']); method=method_names[row['method']]
            vals=self.baseline_values(method,k)
            self.compare(len(vals),row['strict_count'],f'baseline/K{k}/{method}/strict')
            self.compare(mean(vals),row['mean_energy_j'],f'baseline/K{k}/{method}/mean')
            import statistics
            self.compare(statistics.median(vals),row['median_energy_j'],f'baseline/K{k}/{method}/median')
        for row in self.tables['strong_reference']:
            values=[r for r in self.raw['strong']['rows'] if r['mode']=='standard' and r['stage1_status']=='optimal']
            if row['scenario']!='aggregate': values=[r for r in values if r['scenario_seed']==int(row['scenario'])]
            for r in values:
                calculated=100*(r['strict_energy_j']-r['best_known_energy_j'])/r['best_known_energy_j']
                if abs(calculated-r['gap_to_best_known_pct'])>1e-8: raise ValueError('强参考差距公式核验失败。')
            self.compare(mean(r['gap_to_best_known_pct'] for r in values),row['standard_gap_mean_pct'],f'strong/{row["scenario"]}/gap')
            self.compare(len(values),row['standard_strict'],f'strong/{row["scenario"]}/strict')
        geographic=self.raw['geography']['rows']
        for row in self.tables['real_geography']:
            if row['record_type']=='method':
                method=method_names[row['method_or_metric']]
                records=deterministic_rows(geographic,method) if method in ('greedy_repair','nearest_mec') else geographic
                vals=[r[method]['energy_j'] for r in records if strict(r[method])]
                self.compare(len(vals),row['strict_count'],f'geography/{method}/strict')
                self.compare(len(records),row['total_count'],f'geography/{method}/total')
                if vals: self.compare(mean(vals),row['mean_energy_j'],f'geography/{method}/mean')
            elif row['method_or_metric']=='Mean Hybrid advantage vs Generic':
                pairs=self.pairs()
                self.compare(mean(100*(p['generic_j']-p['hybrid_j'])/p['generic_j'] for p in pairs),row['value'],'geography/paired_gain')
        # 汇总型表格没有逐次分布时仅使用已发布指标，不凭均值合成散点或误差条。
        for name in ('mec_count','uav_count','contact_budget','bandwidth_sensitivity','coverage_radius','spatial_robustness'):
            for r in self.tables[name]:
                if not 0<=int(r['stage1_strict'])<=int(r['runs']): raise ValueError(f'{name} 严格样本量越界。')
                if 'stage2_strict' in r and not 0<=int(r['stage2_strict'])<=int(r['stage1_strict']):
                    raise ValueError(f'{name} Stage-2 样本量超过 Stage-1。')
                if int(r['stage1_strict'])==0 and r.get('energy_mean_j','')!='':
                    raise ValueError(f'{name} 无严格解却填入能耗。')
                # 有效样本存在时，计划绘制的指标不能静默留空；仅无有效样本允许 NaN。
                plotted={
                    'mec_count':('offload_ratio_mean','cpu_util_mean'),
                    'uav_count':('delay_mean_s','contacts_per_uav_mean'),
                    'contact_budget':('energy_mean_j','contacts_per_uav_mean'),
                    'bandwidth_sensitivity':('energy_mean_j','bandwidth_relative_shadow_mean','cpu_relative_shadow_mean'),
                    'coverage_radius':('energy_mean_j','route_distance_km_mean'),
                    'spatial_robustness':('offload_ratio_mean','bandwidth_relative_shadow_mean'),
                }[name]
                stage='stage2_strict' if name in ('mec_count','uav_count') else 'stage1_strict'
                for key in plotted:
                    present=math.isfinite(number(r,key))
                    if present!=(int(r[stage])>0):
                        raise ValueError(f'{name}/{key} 指标缺失状态与 {stage} 样本数不一致。')
        for r in self.tables['iteration_budget']:
            if not 0<=int(r['strict_runs'])<=int(r['runs']):
                raise ValueError('预算实验严格样本量越界。')
            if not math.isfinite(number(r,'runtime_mean_s')) or not math.isfinite(number(r,'conditional_energy_mean_j')):
                raise ValueError('预算实验缺少必要指标。')
        for r in self.tables['ablation']:
            if r['variant']!='Full Hybrid' and sum(int(r[k]) for k in ('full_better','full_equal','ablated_better'))!=int(r['strict_count']):
                raise ValueError(f'消融配对计数不完整：{r["variant"]}')
        counts={k:len(self.pairs(k)) for k in (50,80)}
        if counts!={50:24,80:21} or len(self.pairs())!=8: raise ValueError('配对样本数与正式实验不符。')
        for k,expected in [(50,(14,10,0)),(80,(17,4,0)),(None,(2,6,0))]:
            counts=[0,0,0]
            for p in self.pairs(k):
                delta=p['generic_j']-p['hybrid_j']
                counts[0 if delta>1e-3 else 2 if delta < -1e-3 else 1]+=1
            if tuple(counts)!=expected: raise ValueError(f'{k} 配对改进计数不一致：{counts}')

    def export(self) -> None:
        write_json(DATA/'experiment_validation.json',{'passed':True,'rounding_checks':self.checks,
            'matched_metric_count':len(self.checks),'paired_counts':{'K50':24,'K80':21,'geography':8},
            'statistical_policy':{'energy':'strict Stage-1','qos':'strict Stage-2',
             'sd':'sample standard deviation (ddof=1)','deterministic_unit':'unique scenario',
             'paired_gain':'mean of per-pair percentages','missing':'NaN, never zero'}})
        for name,k in [('paired_K50',50),('paired_K80',80),('paired_geography',None)]:
            path=DATA/f'{name}.csv'
            with path.open('w',encoding='utf-8',newline='') as file:
                rows=self.pairs(k); writer=csv.DictWriter(file,fieldnames=list(rows[0]))
                writer.writeheader(); writer.writerows(rows)
