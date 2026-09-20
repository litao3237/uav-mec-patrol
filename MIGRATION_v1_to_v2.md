# v1 -> v2 迁移说明

| v1 | v2 | 原因 |
|---|---|---|
| `model.py` | `domain/entities.py + solution.py + enums.py` | 分离场景实体和决策解 |
| `Contact(uav_id, mec_id, x, y)` | `ContactPoint + ContactVisit` | 候选接触点可被任意 UAV 使用，适合 ALNS insert/replace |
| `routes: dict[str, list[str]]` | `Route + RouteStop` | 避免字符串分支和后续算子歧义 |
| `task_mode: "LOCAL"/contact_id` | `TaskDecision` | 强类型，减少字符串错误 |
| `event_evaluator.py` | `evaluation/validator.py + events.py + channel.py + geometry.py` | 评价职责拆分 |
| `resource_cvx.py` | `optimization/resource/problem.py + cvx_solver.py + result.py` | 模型与求解过程分离 |
| `verify_kkt.py` | `optimization/resource/kkt_verify.py` | 与 P1-R 放在同一模块 |
| `smoke_tests.py` | `tests/` + pytest | 支持长期回归测试 |
| `requirements.txt` | `pyproject.toml` | 统一使用 uv |
| 无 ALNS 结构 | `algorithms/alns/` | 为后续外层 P1-D 算法预留 |
