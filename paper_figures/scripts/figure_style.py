"""论文实验图统一样式及固定物理尺寸导出。"""
from __future__ import annotations
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.lines import Line2D
import numpy as np
from prepare_experiment_data import ROOT

OUT=ROOT/'paper_figures/output'
BLUE='#306587'
ORANGE='#A46D36'
TEAL='#397B73'
GRAY='#78858F'
INK='#29343D'
WIDTH=183/25.4


def configure() -> None:
    """强制嵌入 Times New Roman；找不到字体时失败，避免不同机器默默替换。"""
    font_manager.findfont('Times New Roman',fallback_to_default=False)
    plt.rcParams.update({'font.family':'Times New Roman','font.size':9,
        'axes.labelsize':9,'axes.titlesize':9.5,'axes.titleweight':'bold','axes.titlepad':9,
        'xtick.labelsize':8.5,'ytick.labelsize':8.5,'legend.fontsize':8.5,
        'axes.spines.top':False,'axes.spines.right':False,'axes.linewidth':.75,
        'axes.edgecolor':GRAY,'text.color':INK,'axes.labelcolor':INK,
        'xtick.color':INK,'ytick.color':INK,'lines.linewidth':1.35,
        'lines.markersize':4.5,'legend.frameon':False,'pdf.fonttype':42,
        'ps.fonttype':42,'svg.fonttype':'none','mathtext.fontset':'stix',
        'figure.facecolor':'white','axes.facecolor':'white','savefig.facecolor':'white',
        'figure.dpi':150,'savefig.dpi':300,'hatch.linewidth':.6})


def figure(height_mm:float=96):
    fig=plt.figure(figsize=(WIDTH,height_mm/25.4),layout='constrained')
    fig.get_layout_engine().set(w_pad=.05,h_pad=.07,wspace=.10,hspace=.13)
    return fig


def panel(ax,letter:str,title:str,ylabel:str|None=None,xlabel:str|None=None):
    ax.set_title(f'({letter}) {title}',loc='left')
    if ylabel: ax.set_ylabel(ylabel)
    if xlabel: ax.set_xlabel(xlabel)
    ax.grid(axis='y',color='#E5E9EC',linewidth=.55,zorder=0)
    ax.set_axisbelow(True)


def series(ax,x,y,*,color=ORANGE,marker='s',label=None,ls='-',error=None):
    if error is None: ax.plot(x,y,color=color,marker=marker,ls=ls,label=label,zorder=3)
    else: ax.errorbar(x,y,yerr=error,color=color,marker=marker,ls=ls,label=label,
                     capsize=2.3,elinewidth=.7,zorder=3,markerfacecolor='white')
    ax.set_xticks(x)
    ax.margins(x=.12,y=.20)


def counts(ax,x,y,labels,dy=8):
    for px,py,label in zip(x,y,labels):
        if np.isfinite(py):
            ax.annotate(str(label),(px,py),xytext=(0,dy),textcoords='offset points',
                        ha='center',va='bottom',fontsize=8.5,color=INK)


def rate_bars(ax,labels,success,total,*,colors=None,hatches=None):
    x=np.arange(len(labels)); values=np.array(success)/np.array(total)*100
    bars=ax.bar(x,values,width=.56,color=colors or ORANGE,edgecolor=INK,linewidth=.45,zorder=3)
    if hatches:
        for bar,hatch in zip(bars,hatches): bar.set_hatch(hatch)
    counts(ax,x,values,[f'{a}/{b}' for a,b in zip(success,total)],dy=4)
    ax.set_xticks(x,labels)
    ax.set_ylim(0,118); ax.set_yticks([0,25,50,75,100])
    return bars


def method_legend(fig):
    handles=[Line2D([],[],color=BLUE,marker='o',ls='--',label='Generic ALNS'),
             Line2D([],[],color=ORANGE,marker='s',label='Proposed Hybrid')]
    fig.legend(handles=handles,loc='outside upper center',ncols=2)


def paired_plot(ax,rows,letter,title):
    """每行固定一个种子组合；横轴使用同一行两端的真实绝对能耗。"""
    y=np.arange(len(rows)); g=np.array([r['generic_j'] for r in rows])/1000
    h=np.array([r['hybrid_j'] for r in rows])/1000
    ax.hlines(y,np.minimum(g,h),np.maximum(g,h),color=GRAY,lw=1,zorder=2)
    ax.scatter(g,y,s=29,facecolors='white',edgecolors=BLUE,marker='o',linewidth=1,zorder=4)
    ax.scatter(h,y,s=16,color=ORANGE,marker='s',zorder=5)
    ax.set_yticks(y,[f'S{r["scenario_seed"]}/A{r["algorithm_seed"]}' for r in rows])
    ax.invert_yaxis(); ax.margins(x=.13,y=.075)
    panel(ax,letter,title,xlabel='UAV energy (kJ)')
    ax.grid(axis='y',visible=False); ax.grid(axis='x',color='#E5E9EC',lw=.55)


def save(fig,name:str,title:str,registry:list):
    """不用 tight 裁切改变论文宽度，SVG 保留文本，PDF 嵌入字体。"""
    if not name.startswith(('fig03_','fig04_','fig05_','fig06_','fig07_','fig08_','fig09_',
                            'fig10_','fig11_','fig12_','fig13_','figS1_','figS2_')):
        raise ValueError(f'拒绝写入保留的概念图或未知文件名：{name}')
    for ext in ('pdf','svg','png'):
        path=OUT/ext/f'{name}.{ext}'; path.parent.mkdir(parents=True,exist_ok=True)
        metadata={'Title':title,'Creator':'UAV-MEC research / Matplotlib'} if ext=='pdf' else None
        fig.savefig(path,dpi=300,metadata=metadata)
    # Matplotlib 会预建视区外的刻度文字，即使 visible=True 也不真正绘制。
    # 登记时排除这些刻度，确保后续 PDF 完整性检查只要求实际显示的标签。
    excluded=set()
    for ax in fig.axes:
        for axis in (ax.xaxis,ax.yaxis):
            lower,upper=sorted(axis.get_view_interval())
            for tick in axis.get_major_ticks()+axis.get_minor_ticks():
                if not ax.axison or not axis.get_visible() or not lower<=tick.get_loc()<=upper:
                    excluded.update((id(tick.label1),id(tick.label2)))
    visible=[obj for obj in fig.findobj(matplotlib.text.Text)
             if obj.get_visible() and obj.get_text() and id(obj) not in excluded]
    texts=[obj.get_text() for obj in visible]
    fonts=[obj.get_fontsize() for obj in visible]
    if min(fonts)<8.5: raise ValueError(f'{name} 出现低于 8.5 pt 的文字。')
    registry.append({'name':name,'title':title,'width_mm':183,
                     'height_mm':round(fig.get_size_inches()[1]*25.4,3),
                     'font_range_pt':[min(fonts),max(fonts)],'axes':len(fig.axes),'texts':texts})
    plt.close(fig)
