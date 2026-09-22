"""绘制敏感性与补充图，显式区分 Stage-1 能耗和 Stage-2 QoS 样本。"""
import numpy as np
from figure_style import *
from experiment_data import number


def conditional_line(ax,rows,xkey,ykey,letter,title,ylabel,xlabel,*,scale=1,stage='stage1_strict'):
    x=[number(r,xkey) for r in rows]; y=[number(r,ykey)*scale for r in rows]
    series(ax,x,y)
    counts(ax,x,y,[f'n={r[stage]}' for r in rows],dy=6)
    panel(ax,letter,title,ylabel,xlabel)
    return x,y


def draw_sensitivity(data,registry):
    mec=data.tables['mec_count']; uav=data.tables['uav_count']
    fig=figure(155); axes=fig.subplots(2,3)
    rate_bars(axes[0,0],[r['num_mecs'] for r in mec],[int(r['stage1_strict']) for r in mec],[int(r['runs']) for r in mec])
    panel(axes[0,0],'a','MEC: strict feasibility','Strict runs (%)','MEC servers, E')
    conditional_line(axes[0,1],mec,'num_mecs','offload_ratio_mean','b','MEC: offloading','Offloaded tasks (%)','MEC servers, E',scale=100,stage='stage2_strict')
    conditional_line(axes[0,2],mec,'num_mecs','cpu_util_mean','c','MEC: CPU occupation','CPU utilization (%)','MEC servers, E',scale=100,stage='stage2_strict')
    rate_bars(axes[1,0],[r['num_uavs'] for r in uav],[int(r['stage1_strict']) for r in uav],[int(r['runs']) for r in uav])
    panel(axes[1,0],'d','UAV: strict feasibility','Strict runs (%)','UAVs, M')
    conditional_line(axes[1,1],uav,'num_uavs','delay_mean_s','e','UAV: delay','Mean delay (s)','UAVs, M',stage='stage2_strict')
    conditional_line(axes[1,2],uav,'num_uavs','contacts_per_uav_mean','f','UAV: contacts','Contacts per UAV','UAVs, M',stage='stage2_strict')
    for ax in axes[1,1:]:
        ax.set_xlim(2.6,8.4); ax.text(3,.08,'N/A',transform=ax.get_xaxis_transform(),ha='center',fontsize=8.5,color=GRAY)
    fig.supxlabel('Rates: Stage-1 strict / 9. Conditional metrics: Stage-2 strict n.\nM=3: no strict terminal solution recovered within the search budget.',fontsize=8.5)
    save(fig,'fig08_mec_uav_sensitivity','MEC-count and UAV-count sensitivity',registry)

    rows=data.tables['contact_budget']; fig=figure(94); axes=fig.subplots(1,3)
    rate_bars(axes[0],[r['max_contacts_per_uav'] for r in rows],[int(r['stage1_strict']) for r in rows],[int(r['runs']) for r in rows])
    panel(axes[0],'a','Strict feasibility','Strict runs (%)','Contact limit per UAV')
    conditional_line(axes[1],rows,'max_contacts_per_uav','energy_mean_j','b','Conditional energy','UAV energy (kJ)','Contact limit per UAV',scale=.001)
    conditional_line(axes[2],rows,'max_contacts_per_uav','contacts_per_uav_mean','c','Realized contacts','Contacts per UAV','Contact limit per UAV')
    fig.supxlabel('Energy and contact means use the Stage-1-strict subset shown by n.',fontsize=8.5)
    save(fig,'fig09_contact_budget','Contact-opportunity sensitivity',registry)

    rows=data.tables['bandwidth_sensitivity']; fig=figure(100); axes=fig.subplots(1,2)
    conditional_line(axes[0],rows,'bandwidth_scale','energy_mean_j','a','Bandwidth sensitivity','UAV energy (kJ)','Bandwidth multiplier',scale=.001)
    ax=axes[1]; x=np.arange(3); width=.30
    for offset,key,color,hatch,label in [(-width/2,'bandwidth_relative_shadow_mean',BLUE,'','Bandwidth'),(width/2,'cpu_relative_shadow_mean',ORANGE,'//','MEC CPU')]:
        values=[number(r,key) for r in rows]
        ax.bar(x+offset,values,width,color=color,edgecolor=INK,lw=.45,hatch=hatch,label=label,zorder=3)
        counts(ax,x+offset,values,[f'{v:.3f}' for v in values],dy=4)
    ax.set_xticks(x,['0.5','1.0','1.5']); ax.set_ylim(0,.0165); ax.set_yticks([0,.004,.008,.012,.016])
    ax.legend(loc='upper right')
    panel(ax,'b','Stage-1 shadow prices','Relative shadow price','Bandwidth multiplier')
    fig.supxlabel('Strict subsets: 8/9, 9/9, 9/9; shadow prices use Stage-1 multipliers.',fontsize=8.5)
    save(fig,'fig10_bandwidth_shadow','Bandwidth sensitivity and resource shadow prices',registry)

    rows=data.tables['iteration_budget']; fig=figure(96); axes=fig.subplots(1,2)
    fig.suptitle('Iteration-budget sensitivity',fontsize=10,fontweight='bold')
    x=[int(r['iterations']) for r in rows]; energy=[number(r,'conditional_energy_mean_j')/1000 for r in rows]
    series(axes[0],x,energy); counts(axes[0],x,energy,[f'{r["strict_runs"]}/{r["runs"]}' for r in rows],dy=6)
    panel(axes[0],'a','Conditional energy','UAV energy (kJ)','Iteration budget')
    series(axes[1],x,[number(r,'runtime_mean_s') for r in rows])
    panel(axes[1],'b','Computational cost','Mean runtime (s)','Iteration budget')
    fig.supxlabel('Separate budget runs; not prefixes of a single convergence trajectory.',fontsize=8.5)
    save(fig,'fig11_iteration_budget','Iteration-budget sensitivity',registry)

    rows=data.tables['spatial_robustness']; fig=figure(100); axes=fig.subplots(1,3)
    labels=['Uniform','Clustered','Boundary-\nbiased']; x=np.arange(3)
    rate_bars(axes[0],labels,[int(r['stage1_strict']) for r in rows],[int(r['runs']) for r in rows])
    panel(axes[0],'a','Strict feasibility','Strict runs (%)')
    for ax,letter,key,scale,title,ylabel in zip(axes[1:],'bc',
        ['offload_ratio_mean','bandwidth_relative_shadow_mean'],[100,1],
        ['Offloading','Bandwidth pressure'],['Offloaded tasks (%)','Relative BW shadow price']):
        values=[number(r,key)*scale for r in rows]
        ax.bar(x,values,.55,color=ORANGE if letter=='b' else BLUE,edgecolor=INK,lw=.45,zorder=3)
        ax.set_xticks(x,labels); ax.margins(y=.26)
        counts(ax,x,values,[f'n={r["stage1_strict"]}' for r in rows],dy=5)
        panel(ax,letter,title,ylabel)
    fig.supxlabel('Conditional metrics use strict subsets; absolute energy is not compared.',fontsize=8.5)
    save(fig,'figS1_spatial_robustness','Spatial-distribution robustness',registry)

    rows=data.tables['coverage_radius']; fig=figure(94); axes=fig.subplots(1,2)
    conditional_line(axes[0],rows,'radius_scale','energy_mean_j','a','Conditional energy','UAV energy (kJ)','Coverage-radius multiplier',scale=.001)
    conditional_line(axes[1],rows,'radius_scale','route_distance_km_mean','b','Route geometry','Route distance (km)','Coverage-radius multiplier')
    fig.supxlabel('All three settings have 9/9 strict runs; larger coverage need not lower energy.',fontsize=8.5)
    save(fig,'figS2_coverage_radius','MEC coverage-radius sensitivity',registry)
