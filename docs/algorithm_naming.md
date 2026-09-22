# Frozen Algorithm Naming Convention

This document is the paper-facing source of truth for algorithm and baseline names.
Code-level identifiers are intentionally kept backward-compatible while ongoing
experiments and historical result files remain readable.

## Final paper-facing names

| Role | Full English name | Abbreviation | Chinese name |
|---|---|---|---|
| Constructive baseline | Greedy Route + MEC Repair | **GR-MR** | 贪心路径 + MEC 修复 |
| Decoupled baseline | Fixed-Task-Route Nearest-MEC | **FTR-NM** | 固定任务路径最近 MEC 方法 |
| Evolutionary baseline | Route-GA + MEC Repair | **RGA-MR** | 路径遗传算法 + MEC 修复 |
| Search-backbone baseline | Base ALNS | **B-ALNS** | 基础自适应大邻域搜索算法 |
| Proposed method | ALNS with Elite Structural Intensification | **ESI-ALNS** | **精英结构强化自适应大邻域搜索算法** |

## Proposed algorithm name

Formal Chinese name:

> **精英结构强化自适应大邻域搜索算法（ESI-ALNS）**

Formal English name:

> **Adaptive Large Neighborhood Search with Elite Structural Intensification (ESI-ALNS)**

For the first occurrence in the paper, use the full Chinese or English name plus
the abbreviation. Thereafter use **ESI-ALNS** consistently in text, tables,
legends, and captions.

## Naming rationale

- **B-ALNS** is the same ALNS exploration backbone used by ESI-ALNS before the
  elite structural phase. It is therefore a backbone/ablation baseline rather
  than a deliberately weakened "generic" method.
- **ESI-ALNS** differs from B-ALNS by its elite structural intensification stage,
  including computing-aware route relocation and supporting contact/batch
  restructuring followed by strict Stage-1 resource recourse.
- **FTR-NM** says "Fixed-Task-Route" rather than "Fixed-Route" because the
  monitoring-task assignment/order is frozen while MEC contact visits may still
  be inserted or reused.
- **RGA-MR** makes clear that GA searches the route/assignment component and MEC
  decisions are handled by a repair stage rather than by a fully joint GA.
- **GR-MR** makes clear that the greedy component constructs the patrol route and
  the MEC step is a subsequent repair.

## Legacy-name mapping

| Legacy paper label | Frozen label |
|---|---|
| Greedy + MEC Repair / Greedy+MEC Repair | GR-MR |
| FR-NM / Fixed-Route Nearest-MEC | FTR-NM |
| Route-GA + deterministic MEC repair / GA Route Search+Repair | RGA-MR |
| Generic ALNS | B-ALNS |
| Proposed Hybrid / Hybrid | ESI-ALNS |

Legacy code identifiers, JSON keys, filenames, workflow names, and function names
may retain terms such as `generic_alns`, `hybrid`, or
`run_uav_mec_hybrid_alns` for reproducibility. These identifiers are
implementation details and must not be used as the final paper-facing algorithm
names.
