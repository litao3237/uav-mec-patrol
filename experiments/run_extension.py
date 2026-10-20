"""七算法敏感性与GIS扩展；复用已冻结执行器，单独保存协议与源码身份。"""
from __future__ import annotations
import argparse
from copy import deepcopy
from dataclasses import replace
import hashlib
import logging
from pathlib import Path

import run_seven_methods as runner
from experiment_common import current_source_hashes
from uav_mec.instances import build_stanislaus_real_instance
from uav_mec.analysis.experiment_snapshot import content_hash

ROOT=Path(__file__).resolve().parents[1]
SNAPSHOT=ROOT/'data/real_case/stanislaus/usfs_fire_occurrences_selected59_2026-09-22.json'
GIS_CONFIG=ROOT/'configs/real_stanislaus.yaml'
BASE_PROTOCOL=deepcopy(runner.PROTOCOL)


def protocol(study: str, level: float) -> dict:
    """固定因素与重复层级；同一场景跨设置共享任务，GIS不计为独立地图。"""
    if study=='contact' and level not in [1,2,3,4]:raise ValueError('接触上限不在预定矩阵')
    if study=='bandwidth' and level not in [.5,1.,1.5]:raise ValueError('带宽倍数不在预定矩阵')
    if study=='gis' and level != 1:raise ValueError('GIS使用固定地图设置，level必须为1')
    if study not in ['contact','bandwidth','gis']:raise ValueError('未知实验类型')
    p=deepcopy(BASE_PROTOCOL)
    p.update(id='v25_extension_seven_v1',study=study,level=level,
             tasks=[59 if study=='gis' else 80],scenarios=[45,46,47],
             independent_unit='workload scenario on one fixed map' if study=='gis' else 'scenario',
             comparison='冻结搜索配置；全部方法使用同一实例与两阶段完整验收；不作等耗时排名')
    return p


def source_hashes() -> dict:
    """扩展脚本与GIS输入同样纳入身份校验，避免只记录旧执行器。"""
    return current_source_hashes(Path(__file__), GIS_CONFIG, SNAPSHOT)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study',choices=['contact','bandwidth','gis'],required=True)
    parser.add_argument('--level',type=float,required=True)
    parser.add_argument('--scenario',type=int,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    runner.PROTOCOL=protocol(args.study,args.level)
    original_builder=runner.build_paper_scale_instance
    original_write=runner.write_json
    hashes=source_hashes()
    metadata={}

    def build(cfg,**kwargs):
        # 只改实验因素，不改算法或冻结的原执行器文件。
        if args.study=='gis':
            built=build_stanislaus_real_instance(SNAPSHOT,config_path=GIS_CONFIG,num_tasks=59,
                                                num_uavs=5,scenario_seed=kwargs['scenario_seed'])
            metadata.update(built.metadata)
            return built.instance
        instance=original_builder(cfg,**kwargs)
        if args.study=='contact':
            return replace(instance,max_contacts_per_uav=int(args.level))
        return replace(instance,mecs={k:replace(m,bandwidth_mhz=m.bandwidth_mhz*args.level)
                                      for k,m in instance.mecs.items()})

    def write(path,payload):
        original_write(path,{**payload,'extension_source_hashes':hashes,'case_metadata':metadata})

    runner.build_paper_scale_instance=build
    runner.write_json=write
    runner.run_block(runner.PROTOCOL['tasks'][0],args.scenario,'formal',
                     ROOT/'configs/baseline.yaml',args.output)


if __name__=='__main__':main()
