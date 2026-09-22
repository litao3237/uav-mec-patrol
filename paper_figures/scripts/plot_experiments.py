"""离线重建全部 13 组实验图；数据准备与路线复现独立于常规绘图。"""
from __future__ import annotations
import logging
import importlib.metadata
import platform
from experiment_data import ExperimentData
from prepare_experiment_data import DATA,preserve_existing,write_json
from figure_style import configure
from plot_primary import draw_primary
from plot_sensitivity import draw_sensitivity
from plot_reference_geography import draw_reference_geography


def main():
    logging.basicConfig(level=logging.INFO,format='%(levelname)s %(message)s')
    logging.getLogger('fontTools').setLevel(logging.WARNING)
    data=ExperimentData(); data.export(); configure(); registry=[]
    for draw in (draw_primary,draw_sensitivity,draw_reference_geography):
        draw(data,registry)
        logging.info('已导出 %d 组论文实验图。',len(registry))
    if len(registry)!=13: raise RuntimeError(f'实验图数量错误：{len(registry)}')
    # 按论文顺序组织交付，不依赖脚本内部生成顺序。
    registry.sort(key=lambda r:r['name'])
    write_json(DATA/'figure_registry.json',{'figures':registry,'python':platform.python_version(),
        'versions':{n:importlib.metadata.version(n) for n in ('numpy','matplotlib','pyproj','Pillow','pypdf','pdfplumber')}})
    preserve_existing()
    logging.info('全部图形已生成，原有图与汇总数据哈希保持一致。')
    # 单一入口完成实际 PDF 核验和交付打包，不触发下载或重新求解。
    from verify_experiment_figures import main as verify_and_package
    verify_and_package()


if __name__=='__main__':
    main()
