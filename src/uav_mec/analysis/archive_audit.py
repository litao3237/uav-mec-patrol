"""离线重建结果的一致性检查；保留原有约束及数值容差。"""
import math

def assert_audit_equivalent(recomputed, archived, path="audit") -> None:
    """允许跨平台浮点末位差异，但约束集合、状态与通过判定必须完全一致。

    Windows/Linux的对数运算可能相差约2e-16；直接比较整份JSON哈希会误报。
    此处仅处理离线重建的一致性，绝不改变物理残差容差或重新分类有效样本。
    """
    if isinstance(recomputed, dict):
        assert isinstance(archived, dict) and recomputed.keys() == archived.keys(), path
        for key in recomputed:
            if key == "worst_constraint" and recomputed[key] != archived[key]:
                # 全部残差约为零时，末位舍入可能改变argmax；只允许近零并列，
                # 不允许在实际违约中更换最差约束，且两个标识必须真实存在。
                near_zero = all(report.get("passed") is True
                                and 0 <= report.get("max_normalized_violation", math.inf) <= 1e-10
                                for report in (recomputed, archived))
                identifiers = {recomputed[key], archived[key]}
                if near_zero and all(identifiers <= {c["id"] for c in report.get("constraints", [])}
                                     for report in (recomputed, archived)):
                    continue
            assert_audit_equivalent(recomputed[key], archived[key], f"{path}.{key}")
    elif isinstance(recomputed, list):
        assert isinstance(archived, list) and len(recomputed) == len(archived), path
        for index, (left, right) in enumerate(zip(recomputed, archived)):
            assert_audit_equivalent(left, right, f"{path}[{index}]")
    elif isinstance(recomputed, bool) or recomputed is None:
        assert recomputed is archived, path
    elif isinstance(recomputed, (int, float)):
        assert isinstance(archived, (int, float)) and not isinstance(archived, bool), path
        assert math.isfinite(recomputed) and math.isfinite(archived), path
        assert math.isclose(recomputed, archived, rel_tol=1e-12, abs_tol=1e-10), path
    else:
        assert recomputed == archived, path
