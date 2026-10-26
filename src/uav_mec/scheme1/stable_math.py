"""与平台无关的 sin、cos：十进制高精度计算后舍入到最近的双精度数（正确舍入）

各平台数学库的 sin、cos、pow 在少数自变量上末位不同。2026-10-26 实测：Windows 的 math.sin/cos 在火线布点与
候选上传点用到的自变量上有少量调用不是正确舍入（Linux 的结果与正确舍入值一致），pow(x, 2) 与 x·x 在约 0.05%
的随机自变量上不同；局部搜索会因输入的末位差异在个别实例上走向不同的局部最优。实例生成只调用几十次，
十进制计算的开销可以忽略。平方一律写成相乘（IEEE 保证正确舍入），不用 ** 2
"""

from __future__ import annotations

import math
import types
from decimal import Decimal, localcontext

# π 取 80 位有效数字；自变量化简到一个周期内后，误差远小于双精度的半个 ulp
_PI = Decimal("3.1415926535897932384626433832795028841971693993751058209749445923078164062862089986")
_PREC = 60                  # 十进制运算的有效位数
_TAIL = Decimal("1e-55")    # 泰勒级数的截断阈值


def _sin_cos(x: float) -> tuple[float, float]:
    """sin x 与 cos x 的正确舍入值

    Decimal(x) 是双精度数的精确十进制表示，60 位精度下级数误差约 1e-57；float(Decimal) 按最近舍入，
    只有真值离两个双精度数的中点不到 1e-57 时才可能舍错，实际不会发生
    """
    if x == 0.0:
        return x, 1.0                        # sin(±0) = ±0、cos 0 = 1，精确值
    if not math.isfinite(x):
        return math.nan, math.nan            # 实例生成中不会出现
    with localcontext() as ctx:
        ctx.prec = _PREC
        d = Decimal(x)
        two_pi = 2 * _PI
        r = d - (d / two_pi).to_integral_value() * two_pi
        r2 = r * r
        s = term_s = r
        c = term_c = Decimal(1)
        k = 1
        while abs(term_s) > _TAIL or abs(term_c) > _TAIL:
            term_s = -term_s * r2 / ((2 * k) * (2 * k + 1))
            term_c = -term_c * r2 / ((2 * k - 1) * (2 * k))
            s += term_s
            c += term_c
            k += 1
        return float(s), float(c)


def sin(x: float) -> float:
    """正确舍入的 sin x"""
    return _sin_cos(x)[0]


def cos(x: float) -> float:
    """正确舍入的 cos x"""
    return _sin_cos(x)[1]


def math_shim() -> types.SimpleNamespace:
    """标准库 math 的替身：只把 sin、cos 换成正确舍入的版本，供回归检查替换检验脚本中的 math"""
    ns = {k: getattr(math, k) for k in dir(math) if not k.startswith("_")}
    ns.update(sin=sin, cos=cos)
    return types.SimpleNamespace(**ns)
