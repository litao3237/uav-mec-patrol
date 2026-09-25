"""补充实验的无损实例/方案快照；非有限结果显式记为缺失，不输出非法JSON。"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from uav_mec.domain import (
    ContactPoint, ContactVisit, DiscreteSolution, ExecutionMode, Instance,
    MEC, Route, RouteStop, StopType, Task, TaskDecision, UAV,
)


def json_ready(value: Any) -> Any:
    """递归保留原始字段；NaN/Inf用null表示，状态与失败原因由调用方另存。"""
    if is_dataclass(value):
        return json_ready(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(k): json_ready(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(v) for v in value]
    if hasattr(value, "item"):
        return json_ready(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def content_hash(value: Any) -> str:
    """统一JSON编码计算摘要，便于跨机器核对实例、方案及协议。"""
    encoded = json.dumps(json_ready(value), sort_keys=True, ensure_ascii=False,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def write_json(path: Path, value: Any) -> None:
    """同目录原子替换检查点，作业中断时保留最近一份完整结果。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(json_ready(value), ensure_ascii=False,
                                    indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def restore_instance(data: dict) -> Instance:
    """从全量快照恢复实例，不依赖未来可能变化的生成器默认参数。"""
    values = dict(data)
    for group, cls in (("tasks", Task), ("mecs", MEC), ("uavs", UAV),
                       ("contact_points", ContactPoint)):
        values[group] = {key: cls(**row) for key, row in data[group].items()}
    values["depot_xy"] = tuple(values["depot_xy"])
    return Instance(**values)


def restore_solution(data: dict) -> DiscreteSolution:
    """恢复路线类型和决策枚举，保证离线核验使用原始离散方案。"""
    return DiscreteSolution(
        routes={key: Route(row["uav_id"], tuple(
            RouteStop(StopType(s["kind"]), s["ref_id"]) for s in row["stops"]
        )) for key, row in data["routes"].items()},
        contact_visits={key: ContactVisit(**row) for key, row in data["contact_visits"].items()},
        task_decisions={key: TaskDecision(ExecutionMode(row["mode"]), row["contact_visit_id"])
                        for key, row in data["task_decisions"].items()},
        metadata=data.get("metadata", {}),
    )
