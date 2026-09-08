"""ROAS 신뢰구간.

왜 필요한가.
    구매 3건 · ROAS 1.4 인 소재를 그냥 끄면, 실제로는 좋은 소재를 노이즈로 죽인 것일 수 있다.
    구매 수가 적을수록 관측 ROAS 는 심하게 흔들린다. 구매 3건짜리 소재의 "진짜 ROAS" 는
    대략 0.4 ~ 3.0 어딘가다. 이 폭을 계산해서, 폭 전체가 목표선 아래일 때만 끈다.

모델
    구매 건수 k 를 포아송으로 본다. 객단가(AOV)는 관측값으로 고정한다.
    Garwood exact interval 로 k 의 신뢰구간 [k_lo, k_hi] 를 구한 뒤

        ROAS = AOV × k / spend

    에 그대로 대입한다. 카이제곱 분위수는 Wilson-Hilferty 근사로 구한다
    (scipy 없이 쓰기 위함, 자유도 2 이상에서 오차 1% 미만).

한계 — 알고 쓰라고 적어둔다.
    · AOV 변동은 반영하지 않는다. 번들/단품이 섞인 소재는 실제 폭이 이보다 조금 넓다.
    · 어트리뷰션 지연을 반영하지 않는다. 그래서 rules.yaml 의 min_days 게이트가 따로 있다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# 표준정규 분위수 (양측 신뢰수준 → 한쪽 꼬리 z)
_Z_TABLE = {0.80: 1.2815515655, 0.90: 1.6448536270, 0.95: 1.9599639845, 0.99: 2.5758293035}


def _z_for(level: float) -> float:
    if level in _Z_TABLE:
        return _Z_TABLE[level]
    # Acklam 근사의 간이 버전 — 표에 없는 신뢰수준용
    p = 1.0 - (1.0 - level) / 2.0
    t = math.sqrt(-2.0 * math.log(1.0 - p))
    return t - (2.515517 + 0.802853 * t + 0.010328 * t * t) / (
        1.0 + 1.432788 * t + 0.189269 * t * t + 0.001308 * t * t * t
    )


def chi2_quantile(p: float, df: float) -> float:
    """카이제곱 분위수 (Wilson-Hilferty 근사). df=0 이면 0."""
    if df <= 0:
        return 0.0
    if df == 2:
        # 자유도 2 는 지수분포라 정확해가 있다. k=0 상단에서 이 경로를 탄다.
        return -2.0 * math.log(1.0 - p)
    z = _z_for(2.0 * p - 1.0) if p >= 0.5 else -_z_for(1.0 - 2.0 * p)
    h = 2.0 / (9.0 * df)
    return max(0.0, df * (1.0 - h + z * math.sqrt(h)) ** 3)


def poisson_interval(k: int, level: float = 0.80) -> tuple[float, float]:
    """관측 건수 k 에 대한 포아송 평균의 Garwood 신뢰구간."""
    alpha = 1.0 - level
    lo = chi2_quantile(alpha / 2.0, 2 * k) / 2.0 if k > 0 else 0.0
    hi = chi2_quantile(1.0 - alpha / 2.0, 2 * k + 2) / 2.0
    return lo, hi


@dataclass(frozen=True)
class RoasInterval:
    point: float
    lower: float
    upper: float
    purchases: int
    aov: float

    def __str__(self) -> str:
        return f"{self.point:.2f} [{self.lower:.2f}~{self.upper:.2f}]"


def roas_interval(
    spend: float,
    revenue: float,
    purchases: int,
    level: float = 0.80,
    fallback_aov: float = 0.0,
) -> RoasInterval:
    """지출·매출·구매수로부터 ROAS 신뢰구간을 만든다.

    구매가 0건이면 관측 AOV 가 없으므로 ``fallback_aov`` (계정 평균 객단가)를 쓴다.
    이때 하단은 0, 상단은 "이 지출로 운 나쁘게 0건이 나왔을 때 가능한 최대 ROAS" 가 된다.
    """
    if spend <= 0:
        return RoasInterval(0.0, 0.0, float("inf"), purchases, 0.0)

    aov = (revenue / purchases) if purchases > 0 else fallback_aov
    k_lo, k_hi = poisson_interval(purchases, level)
    point = revenue / spend
    return RoasInterval(
        point=point,
        lower=aov * k_lo / spend,
        upper=aov * k_hi / spend,
        purchases=purchases,
        aov=aov,
    )
