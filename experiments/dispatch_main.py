"""检查低中高负载先导并冻结七方法协议，再启动可恢复的正式场景块。"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone
from experiment_common import current_source_hashes

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'outputs/current/main'


def main():
    global WORK
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers',type=int,default=3)
    parser.add_argument('--output-dir',type=Path,default=WORK)
    args=parser.parse_args()
    WORK=args.output_dir.resolve()
    if not 1<=args.workers<=3:raise ValueError('独立场景进程数须位于1—3')
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    pilots=[]
    for count in (30,50,80):
        p=WORK/f'pilot/K{count}_S45.json'
        item=json.loads(p.read_text(encoding='utf-8'))
        if not item['complete'] or len(item['rows'])!=7 or item.get('execution_error'):
            raise ValueError(f'先导未完整结束：{p}')
        if any(r['stage2']['qualified'] and not r['stage1']['qualified'] for r in item['rows']):
            raise ValueError(f'两阶段验收状态不一致：{p}')
        pilots.append(item)
    protocol=pilots[0]['protocol']
    if any(p['protocol']!=protocol for p in pilots):raise ValueError('先导协议不一致')
    hashes=current_source_hashes()
    if any(p['source_hashes'] != hashes for p in pilots):
        raise RuntimeError('先导执行后源码已变化，请在新目录重新执行先导')
    freeze_path=WORK/'frozen_protocol.json'
    if freeze_path.exists():
        frozen=json.loads(freeze_path.read_text(encoding='utf-8'))
        if frozen['source_hashes']!=hashes or frozen['protocol']!=protocol:
            raise RuntimeError('源码或协议在正式运行后变化，禁止混合结果')
    else:
        frozen={'protocol':protocol,'source_hashes':hashes,'frozen_at_utc':datetime.now(timezone.utc).isoformat(),
                'workers':args.workers,'purpose':'固定配置七方法对比；并发场景耗时不作单机串行速度排名',
                'pilot_scope':'检查执行和记录完整性，未按性能调参；正式场景仍使用原定45—52',
                'expected_rows':816}
        freeze_path.write_text(json.dumps(frozen,ensure_ascii=False,indent=2),encoding='utf-8')
    env=dict(os.environ,PYTHONPATH=str(ROOT/'src'),PYTHONIOENCODING='utf-8',
             OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
    def run_block(k,s):
        output=WORK/f'formal/K{k}_S{s}.json';log=WORK/f'logs/K{k}_S{s}.log'
        output.parent.mkdir(parents=True,exist_ok=True);log.parent.mkdir(parents=True,exist_ok=True)
        if output.exists():
            prior=json.loads(output.read_text(encoding='utf-8'))
            if (prior.get('complete') and len(prior['rows'])==17 and prior['protocol']==protocol
                    and prior['source_hashes']==hashes and prior['tasks']==k and prior['scenario_seed']==s):
                return k,s,'already_complete'
            # 中断块保留原件，避免把半块悄悄覆盖成无记录的重试。
            raise RuntimeError(f'存在未完成块，需保留诊断并另设重跑目录：{output}')
        logging.info('开始 K%s S%s',k,s)
        with log.open('w',encoding='utf-8') as stream:
            result=subprocess.run([sys.executable,str(ROOT/'experiments/run_seven_methods.py'),
                '--phase','formal','--tasks',str(k),'--scenario',str(s),'--output',str(output)],
                cwd=ROOT,env=env,stdout=stream,stderr=subprocess.STDOUT)
        if result.returncode:raise RuntimeError(f'场景失败 K{k} S{s}，日志：{log}')
        return k,s,'complete'
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        pending=[pool.submit(run_block,k,s) for k in protocol['tasks'] for s in protocol['scenarios']]
        for result in as_completed(pending):logging.info('完成 %s',result.result())
    # 完整资源快照较大，验收计数逐文件累计，避免无必要地加载整个矩阵。
    blocks=records=stage1_count=both_count=0
    for path in (WORK/'formal').glob('*.json'):
        data=json.loads(path.read_text(encoding='utf-8'))
        blocks+=1;records+=len(data['rows'])
        stage1_count+=sum(r['stage1']['qualified'] for r in data['rows'])
        both_count+=sum(r['stage1']['qualified'] and r['stage2']['qualified'] for r in data['rows'])
    if blocks!=48 or records!=816:
        raise RuntimeError('正式记录数与冻结矩阵不一致')
    summary={'complete':True,'blocks':48,'rows':816,'all_stage1_qualified':stage1_count,
             'both_qualified':both_count}
    (WORK/'execution_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    logging.info('七方法正式运行结束：%s',summary)


if __name__=='__main__':main()
