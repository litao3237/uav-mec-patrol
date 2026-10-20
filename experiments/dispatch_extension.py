"""冻结扩展实验矩阵，并按场景块限量并发；完整块可恢复，中断块拒绝覆盖。"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import subprocess
import sys

from run_extension import protocol,source_hashes
from experiment_common import current_source_hashes

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'outputs/current/extension'


def main():
    global WORK
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers',type=int,default=3)
    parser.add_argument('--output-dir',type=Path,default=WORK)
    parser.add_argument('--main-dir',type=Path,required=True)
    args=parser.parse_args()
    WORK=args.output_dir.resolve()
    if not 1<=args.workers<=3:raise ValueError('并发上限为3个场景块')
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    jobs=[]
    for study,levels in [('contact',[1,2,3,4]),('bandwidth',[.5,1.,1.5]),('gis',[1.])]:
        for level in levels:
            for s in [45,46,47]:
                reused=(study=='contact' and level==3) or (study=='bandwidth' and level==1)
                source=args.main_dir.resolve()/f'K80_S{s}.json' if reused else None
                if source:
                    value=json.loads(source.read_text(encoding='utf8'))
                    if not value['complete'] or len(value['rows'])!=17:raise ValueError(f'复用块不完整：{source}')
                    if value['source_hashes'] != current_source_hashes():
                        raise ValueError(f'复用主实验与当前源码不同，拒绝混合：{source}')
                jobs.append({'study':study,'level':level,'scenario':s,
                             'protocol':protocol(study,level),
                             'reuse_source':str(source) if source else None,
                             'reuse_sha256':hashlib.sha256(source.read_bytes()).hexdigest() if source else None})
    hashes=source_hashes()
    frozen={'id':'v25_extension_seven_v1','jobs':jobs,'source_hashes':hashes,
            'planned_records':408,'new_records':306,'reused_records_in_panels':102,
            'unique_new_blocks':18,'frozen_at_utc':datetime.now(timezone.utc).isoformat(),
            'workers':args.workers,
            'analysis':'共同有效集优先；若为空保留缺失与七方法覆盖，另列条件均值并明确不可直接排名。',
            'reuse_rule':'Cmax=3及带宽1倍与主实验相同，复用同一3场景，不能计为新增独立重复。'}
    WORK.mkdir(parents=True,exist_ok=True)
    freeze=WORK/'frozen_protocol.json'
    if freeze.exists():
        previous=json.loads(freeze.read_text(encoding='utf8'))
        if previous['source_hashes']!=hashes or previous['jobs']!=jobs:
            raise RuntimeError('冻结协议或执行器发生变化，不能混合结果')
    else:freeze.write_text(json.dumps(frozen,ensure_ascii=False,indent=2),encoding='utf8')
    env=dict(os.environ,PYTHONPATH=str(ROOT/'src'),PYTHONIOENCODING='utf-8',
             OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')

    def execute(job):
        key=f"{job['study']}_{job['level']:g}_S{job['scenario']}"
        out=WORK/'raw'/f'{key}.json';log=WORK/'logs'/f'{key}.log'
        out.parent.mkdir(exist_ok=True);log.parent.mkdir(exist_ok=True)
        if out.exists():
            prior=json.loads(out.read_text(encoding='utf8'))
            if prior.get('complete') and len(prior['rows'])==17 and prior['extension_source_hashes']==hashes:
                return key,'already_complete'
            raise RuntimeError(f'保留中断或不同源码块，拒绝覆盖：{out}')
        logging.info('开始 %s',key)
        with log.open('w',encoding='utf8') as stream:
            result=subprocess.run([sys.executable,str(ROOT/'experiments/run_extension.py'),
                '--study',job['study'],'--level',str(job['level']),'--scenario',str(job['scenario']),
                '--output',str(out)],cwd=ROOT,env=env,stdout=stream,stderr=subprocess.STDOUT)
        if result.returncode:raise RuntimeError(f'场景执行中断：{key}；见{log}')
        return key,'complete'

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        pending=[pool.submit(execute,j) for j in jobs if not j['reuse_source']]
        for future in as_completed(pending):logging.info('完成 %s',future.result())
    (WORK/'execution_complete.json').write_text(json.dumps({'new_blocks':18,'new_records':306,
        'complete':True},indent=2),encoding='utf8')


if __name__=='__main__':main()
