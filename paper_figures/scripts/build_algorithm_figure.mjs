/**
 * 生成论文算法主图：总体离散搜索、可重复调用的资源评价及三个结构操作示例。
 * 只描述构图数据；最终文件仍由 Microsoft Visio 原生形状绘制和导出。
 * 筛选与严格 CVX 分别对应探索阶段和基线/精英阶段，避免暗示每个候选都精确求解。
 */
import {writeFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';

const C = {
  ink: '#29343D', gray: '#73808A', secondary: '#59666F', border: '#B6BEC5', white: '#FFFFFF',
  blue: '#306587', blueFill: '#EEF4F8', orange: '#A46D36', orangeFill: '#FBF5EE',
  teal: '#397B73', tealFill: '#EFF6F4', faint: '#F8F9FA', neutralFill: '#EDF0F2',
};
const scene = {
  name: 'fig02_hybrid_alns_framework', width: 1000, height: 945, widthMm: 183,
  description: 'Hierarchical Hybrid ALNS overview: five numbered search steps, repeated resource evaluation, and illustrative structural moves.',
  shapes: [],
};
const ids = new Set();

/** 使用稳定标识和语义图层，确保 Visio 内的设备、文字及路径均可独立编辑。 */
function add(type, id, properties) {
  if (ids.has(id)) throw new Error(`算法图存在重复图元标识：${id}`);
  ids.add(id);
  scene.shapes.push({type, id, group: 'structure', ...properties});
}
function rect(id, x, y, w, h, fill = C.white, stroke = C.border, group = id, extra = {}) {
  add('rect', id, {x, y, w, h, fill, stroke, linePt: 0.75, group, ...extra});
}
function text(id, x, y, w, h, value, size = 8.5, bold = false, group = 'labels', extra = {}) {
  add('text', id, {x, y, w, h, text: value, fontPt: size, bold, align: 'center',
    fill: null, stroke: null, color: C.ink, group, ...extra});
}
function line(id, points, stroke = C.ink, arrow = true, group = 'connections', extra = {}) {
  add('polyline', id, {points, stroke, fill: null, arrow, linePt: 0.9, group, ...extra});
}
function circle(id, x, y, radius = 4, stroke = C.blue, fill = C.white, group = 'move_contact') {
  add('ellipse', id, {x: x-radius, y: y-radius, w: radius*2, h: radius*2,
    fill, stroke, linePt: 0.8, group});
}
function diamond(id, x, y, group = 'move_contact') {
  add('polygon', id, {points: [[x,y-6],[x+6,y],[x,y+6],[x-6,y],[x,y-6]],
    fill: C.white, stroke: C.teal, linePt: 0.9, group});
}

/** 分区标题与步骤编号分别建立区域、主步骤两级信息层次，灰度打印也可辨认。 */
function panelHeading(id, x, y, width, letter, title, color = C.ink, withRule = true) {
  rect(id+'_marker', x, y, 36, 30, color, null, 'panel_titles');
  text(id+'_letter', x, y, 36, 30, `(${letter})`, 9.5, true, 'panel_titles', {color:C.white});
  text(id, x+47, y, width-47, 30, title, 10.2, true, 'panel_titles', {align:'left'});
  if (withRule) line(id+'_rule', [[x,y+40],[x+width,y+40]], color, false, 'panel_titles', {linePt:0.6});
}
function stepBadge(id, y, number, color, inverted = false) {
  circle(id+'_badge', 98, y, 12, inverted ? null : color, inverted ? C.white : color, id);
  text(id+'_number', 86, y-12, 24, 24, number, 8.7, true, id,
    {color:inverted ? color : C.white});
}

// 总体流程仅呈现成功通过基线校验的主路径；失败退出和近失扩展细节在图注中交代。
rect('search_background', 30, 64, 520, 627, C.faint, null, 'panel_backgrounds');
panelHeading('panel_search', 30, 16, 520, 'a', 'Discrete search');
panelHeading('panel_evaluation', 645, 16, 330, 'b', 'Resource evaluation', C.teal);

rect('initialization', 75, 70, 460, 62, C.white, C.border);
rect('initialization_header', 75, 70, 460, 32, C.neutralFill, null, 'initialization');
stepBadge('initialization', 86, '01', C.gray);
text('initialization_title', 120, 74, 403, 25, 'Initialize solution', 9.2, true, 'initialization', {align:'left'});
text('initialization_body', 88, 103, 434, 24, 'Greedy routes + feasibility repair', 8.5, false, 'initialization');
line('initialize_to_search', [[305,132],[305,170]], C.ink, true, 'connections', {linePt:1.2});

rect('alns', 75, 170, 460, 108, C.blueFill, C.blue);
rect('alns_header', 75, 170, 460, 35, C.blue, null, 'alns');
stepBadge('alns', 187.5, '02', C.blue, true);
text('alns_title', 120, 174, 403, 27, 'ALNS exploration', 9.4, true, 'alns', {align:'left',color:C.white});
text('alns_destroy_repair', 88, 213, 434, 23, 'Select operators → destroy / repair', 8.5, false, 'alns');
text('alns_update', 88, 243, 434, 23, 'Evaluate → accept / reject → update weights', 8.5, false, 'alns');
line('alns_iteration', [[75,255],[45,255],[45,191],[75,191]], C.blue, true, 'alns');
line('search_to_baseline', [[305,278],[305,324]], C.ink, true, 'connections', {linePt:1.2});
text('exploration_stop', 326, 286, 186, 25, 'Iteration budget reached', 8.1, false, 'labels', {color:C.secondary});

rect('baseline', 75, 324, 460, 54, C.white, C.teal);
stepBadge('baseline', 340, '03', C.teal);
text('baseline_title', 120, 328, 403, 24, 'Validate exploration best', 9, true, 'baseline', {align:'left'});
text('baseline_body', 88, 353, 434, 21, 'Strict CVX resource solution', 8.3, false, 'baseline');
line('baseline_to_elite', [[305,378],[305,424]], C.ink, true, 'connections', {linePt:1.2});
text('baseline_pass', 323, 387, 132, 24, 'Validated baseline', 8.1, false, 'labels', {color:C.secondary});

rect('elite', 75, 424, 460, 120, C.orangeFill, C.orange);
rect('elite_header', 75, 424, 460, 35, C.orange, null, 'elite');
stepBadge('elite', 441.5, '04', C.orange, true);
text('elite_title', 120, 428, 403, 27, 'Elite structural refinement', 9.4, true, 'elite', {align:'left',color:C.white});
text('elite_candidates', 88, 466, 434, 23, 'Generate / shortlist candidates', 8.5, false, 'elite');
text('elite_acceptance', 88, 493, 434, 23, 'Evaluate → accept meaningful energy gains', 8.5, false, 'elite');
text('elite_families', 88, 518, 434, 20, 'Route · contact · batch · task mode', 8.1, false, 'elite', {color:C.orange});
line('elite_iteration', [[75,520],[45,520],[45,446],[75,446]], C.orange, true, 'elite');
line('elite_to_output', [[305,544],[305,604]], C.ink, true, 'connections', {linePt:1.2});
text('elite_stop', 329, 561, 207, 28, 'No improvement / round limit', 8.1, false, 'labels', {color:C.secondary});

rect('output', 75, 604, 460, 77, C.white, C.gray, 'output', {linePt:1});
rect('output_header', 75, 604, 460, 32, C.neutralFill, null, 'output');
stepBadge('output', 620, '05', C.gray);
text('output_title', 120, 608, 403, 25, 'Final solution', 9.2, true, 'output', {align:'left'});
text('output_content', 88, 640, 434, 33,
  'Routes, offloading and resource allocation\nUAV energy and task completion times', 8.3, false, 'output');

// 右侧是反复调用的评价服务。成对箭头明确传入候选、返回分数/状态，避免末尾串行求解的误解。
rect('evaluation_panel', 645, 70, 330, 484, C.tealFill, C.border);
text('evaluation_scope', 654, 80, 312, 28, 'For fixed discrete decisions', 9, true, 'evaluation_panel');
text('evaluation_variables', 658, 115, 304, 39,
  'Allocate UAV CPU,\nMEC bandwidth and CPU', 8.5, false, 'evaluation_panel');

rect('screening', 665, 176, 290, 100, C.white, C.teal);
rect('screening_header', 665, 176, 290, 35, '#DCECE7', null, 'screening');
text('screening_title', 677, 183, 266, 26, 'Exploration screening', 8.9, true, 'screening');
text('screening_proxy', 677, 216, 266, 23, 'Proxy + feasibility precheck', 8.2, false, 'screening');
text('screening_cvx', 677, 244, 266, 23, 'CVX when required', 8.2, false, 'screening');
line('exploration_request', [[535,214],[665,214]], C.teal, true, 'evaluation_calls');
line('exploration_response', [[665,252],[535,252]], C.teal, true, 'evaluation_calls');
text('exploration_request_label', 543, 186, 112, 24, 'Candidate', 8.1, false, 'evaluation_calls');
text('exploration_response_label', 543, 256, 112, 24, 'Score', 8.1, false, 'evaluation_calls');

rect('strict_cvx', 665, 323, 290, 219, C.white, C.teal);
rect('strict_cvx_header', 665, 323, 290, 39, C.teal, null, 'strict_cvx');
text('strict_cvx_title', 677, 328, 266, 29, 'Strict CVX resource solve', 8.9, true, 'strict_cvx', {color:C.white});
text('strict_cvx_objective', 677, 379, 266, 25, 'Minimize UAV energy', 8.5, false, 'strict_cvx');
text('strict_cvx_constraints', 677, 407, 266, 24, 'Timing and capacity constraints', 8.1, false, 'strict_cvx');
line('strict_cvx_separator', [[685,443],[934,443]], C.border, false, 'strict_cvx', {linePt: 0.5});
rect('strict_cvx_return_background', 676, 453, 268, 78, C.tealFill, null, 'strict_cvx');
text('strict_cvx_return', 677, 460, 266, 62,
  'Return energy, feasibility\nand resource allocation', 8.5, false, 'strict_cvx');
line('baseline_request', [[535,342],[665,342]], C.teal, true, 'evaluation_calls');
line('baseline_response', [[665,368],[535,368]], C.teal, true, 'evaluation_calls');
text('baseline_request_label', 536, 314, 110, 24, 'Baseline', 8.1, false, 'evaluation_calls');
text('baseline_response_label', 536, 373, 110, 24, 'Status', 8.1, false, 'evaluation_calls');
line('elite_request', [[535,474],[665,474]], C.teal, true, 'evaluation_calls');
line('elite_response', [[665,512],[535,512]], C.teal, true, 'evaluation_calls');
text('elite_request_label', 543, 446, 112, 24, 'Candidates', 8.1, false, 'evaluation_calls');
text('elite_response_label', 543, 517, 112, 24, 'Energy', 8.1, false, 'evaluation_calls');

// KKT 是资源最优结构的理论说明与小规模交叉验证，不画成额外运行阶段。
rect('kkt_note', 645, 583, 330, 98, C.faint, C.border);
text('kkt_title', 657, 590, 306, 26, 'KKT analytical support', 8.7, true, 'kkt_note', {color:C.secondary});
text('kkt_body', 657, 620, 306, 48,
  'Resource allocation laws\nSmall-instance CVX cross-checks', 8.3, false, 'kkt_note');

// 下方为候选变化示意，不表示所有变化都会被接受；每个例子仍须通过可行性与能耗评价。
panelHeading('panel_moves', 30, 705, 945, 'c', 'Examples of structural moves', C.orange, false);
for (const [id, x, title] of [
  ['move_contact',30,'Contact-point adjustment'],
  ['move_batch',352,'Batch merging'],
  ['move_mode',674,'Task-mode reassignment'],
]) {
  rect(id+'_panel', x, 747, 296, 181, C.white, C.border, id);
  rect(id+'_header', x, 747, 296, 36, C.orangeFill, null, id);
  text(id+'_title', x+8, 754, 280, 27, title, 8.8, true, id);
}

// 相同任务访问顺序下，将上传位置从 c 调整到覆盖区内的 c′。
for (const [tag, shift, contactY, label] of [['before',0,826,'c'],['after',151,857,'c′']]) {
  add('ellipse', `contact_coverage_${tag}`, {x:78+shift,y:810,w:44,h:80,
    fill:C.tealFill,stroke:C.teal,linePt:0.6,dash:2,group:'move_contact'});
  line(`contact_route_${tag}`, [[62+shift,881],[100+shift,contactY],[138+shift,881]], C.blue, true, 'move_contact');
  circle(`contact_task_i_${tag}`,62+shift,881);
  circle(`contact_task_j_${tag}`,138+shift,881);
  diamond(`contact_point_${tag}`,100+shift,contactY);
  text(`contact_label_${tag}`,125+shift,contactY-14,25,22,label,8.2,false,'move_contact',{italic:true});
  text(`contact_i_${tag}`,47+shift,885,30,23,'i',8.1,false,'move_contact',{italic:true});
  text(`contact_j_${tag}`,123+shift,885,30,23,'j',8.1,false,'move_contact',{italic:true});
}
text('contact_before',51,786,99,24,'Before',8.1,false,'move_contact');
text('contact_after',202,786,99,24,'After',8.1,false,'move_contact');
line('contact_change_arrow',[[159,849],[190,849]],C.gray,true,'move_contact');
text('contact_note',41,905,274,20,'Same task order',8.1,false,'move_contact');

/** 小卡片表示一项任务的数据，用相同字母跟踪合并或模式切换前后的同一任务。 */
function taskCard(id,x,y,label,group) {
  rect(id,x,y,20,24,C.orangeFill,C.orange,group);
  text(id+'_label',x+1,y+1,18,22,label,8.1,false,group,{italic:true});
}
// 两个批次合并到较晚的接触 c₂，保留 a、b、d 三项任务，避免暗示任务被丢弃。
text('batch_before',374,786,105,24,'Before',8.1,false,'move_batch');
text('batch_after',534,786,104,24,'After',8.1,false,'move_batch');
rect('batch_early',384,814,83,34,C.faint,C.border,'move_batch');
rect('batch_late',384,863,83,34,C.faint,C.border,'move_batch');
text('batch_contact_early',356,816,25,25,'c₁',8.1,false,'move_batch',{italic:true});
text('batch_contact_late',356,866,25,25,'c₂',8.1,false,'move_batch',{italic:true});
taskCard('batch_a_before',396,819,'a','move_batch');
taskCard('batch_b_before',429,819,'b','move_batch');
taskCard('batch_d_before',412,868,'d','move_batch');
line('batch_early_branch',[[467,831],[488,831],[488,855]],C.gray,false,'move_batch');
line('batch_late_branch',[[467,880],[488,880],[488,855]],C.gray,false,'move_batch');
line('batch_merge_arrow',[[488,855],[531,855]],C.gray,true,'move_batch');
rect('batch_merged',535,834,96,43,C.faint,C.border,'move_batch');
taskCard('batch_a_after',544,843,'a','move_batch');
taskCard('batch_b_after',573,843,'b','move_batch');
taskCard('batch_d_after',602,843,'d','move_batch');
text('batch_contact_merged',559,878,48,23,'c₂',8.1,false,'move_batch',{italic:true});
text('batch_note',362,905,276,20,'Combine tasks at a later contact',8.1,false,'move_batch');

// 处理模式示意使用机载芯片与 MEC 机柜；连接方向仅表示任务处理位置的改变。
text('mode_before',696,786,99,24,'Local',8.1,false,'move_mode');
text('mode_after',864,786,99,24,'MEC',8.1,false,'move_mode');
taskCard('mode_task_local',734,815,'a','move_mode');
taskCard('mode_task_mec',903,815,'a','move_mode');
line('mode_local_to_cpu',[[744,839],[744,856]],C.blue,true,'move_mode');
line('mode_offload_to_mec',[[913,839],[913,856]],C.teal,true,'move_mode',{dash:3});
rect('mode_cpu',725,861,38,31,C.blueFill,C.blue,'move_mode');
for(let i=0;i<3;i++) {
  line(`mode_cpu_left_${i}`,[[719,867+i*9],[725,867+i*9]],C.blue,false,'move_mode',{linePt:0.6});
  line(`mode_cpu_right_${i}`,[[763,867+i*9],[769,867+i*9]],C.blue,false,'move_mode',{linePt:0.6});
}
rect('mode_mec_server',893,856,40,42,C.white,C.teal,'move_mode');
for(let i=0;i<3;i++) rect(`mode_mec_rack_${i}`,899,862+i*11,28,7,C.tealFill,C.teal,'move_mode');
line('mode_change_arrow',[[800,853],[854,853]],C.gray,true,'move_mode');
text('mode_note',684,905,276,20,'Switch the processing location',8.1,false,'move_mode');

// 在写入最终场景前检查基本几何，避免无效坐标导致 Visio 部分生成后才报错。
for(const shape of scene.shapes) {
  const coordinates = shape.points ?? [[shape.x,shape.y],[shape.x+shape.w,shape.y+shape.h]];
  if(coordinates.some(point => point.some(value => !Number.isFinite(value)))) {
    throw new Error(`算法图含无效坐标：${shape.id}`);
  }
  if(coordinates.some(([x,y]) => x<0 || y<0 || x>scene.width || y>scene.height)) {
    throw new Error(`算法图图元超出画布：${shape.id}`);
  }
}
const output=fileURLToPath(new URL('../visio/assets/fig02_hybrid_alns_framework.scene.json',import.meta.url));
writeFileSync(output, JSON.stringify(scene,null,2)+'\n','utf8');
console.log(`已更新最终算法构图：${scene.shapes.length} 个原生图元，${scene.widthMm} mm × ${(scene.height*scene.widthMm/scene.width).toFixed(1)} mm。`);
