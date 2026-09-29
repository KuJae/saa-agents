"""시장 수익률 패널.

전 구간(2016-01 ~ 2026-08)의 월간 수익률을 한 번만 생성해 고정한다.
같은 시드를 쓰므로 몇 번을 실행하든 동일한 시장이 나온다.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
룩어헤드 차단의 핵심:

  slice_until(as_of)  →  도구가 쓴다. as_of 이전만 잘라서 준다.
  slice_between(a, b) →  백테스트만 쓴다. 채점용 정답지.

에이전트는 slice_until 만 볼 수 있다. 미래 수익률에 물리적으로 접근할 수
없으므로, 프롬프트로 "미래를 보지 마라"고 지시할 필요가 없다.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np

from .state import UNIVERSE

START_YEAR, START_MONTH = 2016, 1
N_MONTHS = 128                       # 2016-01 ~ 2026-08
MODEL_CUTOFF = "2024-06"             # LLM 학습 데이터 종료 시점 (가정)

# 연율 기대수익률 / 변동성
_ANN = {
    "국내주식": (5.9, 16.5), "해외주식(선진)": (6.4, 15.2), "해외주식(신흥)": (7.1, 19.8),
    "국내채권(국고)": (3.2, 4.1), "국내채권(크레딧)": (3.9, 5.0),
    "해외채권(선진)": (3.6, 6.2), "해외채권(신흥)": (5.2, 9.4),
    "국내부동산": (5.4, 10.8), "해외부동산": (5.8, 12.6), "사모주식(PE)": (8.2, 21.0),
    "인프라": (5.6, 11.2), "헤지펀드": (4.8, 7.6), "원자재": (3.4, 17.4),
    "단기자금": (2.6, 0.9),
}

_GRP = {a: ("주식" if a in {"국내주식", "해외주식(선진)", "해외주식(신흥)", "사모주식(PE)"}
            else "채권" if "채권" in a
            else "현금" if a == "단기자금" else "대체") for a in UNIVERSE}

_CORR = {("주식", "주식"): .78, ("채권", "채권"): .62, ("대체", "대체"): .45,
         ("주식", "채권"): .12, ("주식", "대체"): .52, ("채권", "대체"): .22,
         ("현금", "주식"): .02, ("현금", "채권"): .18, ("현금", "대체"): .04}


def ym(i: int) -> str:
    """월 인덱스 → 'YYYY-MM'."""
    m = START_MONTH - 1 + i
    return f"{START_YEAR + m // 12}-{m % 12 + 1:02d}"


def index_of(date: str) -> int:
    """'YYYY-MM' 또는 'YYYY-MM-DD' → 월 인덱스. 범위 밖은 양끝으로 자른다."""
    y, m = int(date[:4]), int(date[5:7])
    i = (y - START_YEAR) * 12 + (m - START_MONTH)
    return max(0, min(N_MONTHS, i))


CUTOFF_IDX = index_of(MODEL_CUTOFF)


@lru_cache(maxsize=1)
def panel() -> np.ndarray:
    """월간 수익률 행렬 [N_MONTHS × 14]. 한 번만 생성되고 캐시된다."""
    n = len(UNIVERSE)
    rng = np.random.default_rng(20260913)

    C = np.eye(n)
    for i in range(n):
        for j in range(i + 1, n):
            k = (_GRP[UNIVERSE[i]], _GRP[UNIVERSE[j]])
            v = _CORR.get(k, _CORR.get(k[::-1], .2)) + rng.normal(0, .05)
            C[i, j] = C[j, i] = float(np.clip(v, -.2, .95))
    w, V = np.linalg.eigh(C)
    C = V @ np.diag(np.clip(w, 1e-4, None)) @ V.T
    d = np.sqrt(np.diag(C)); C = C / np.outer(d, d)

    mu = np.array([_ANN[a][0] for a in UNIVERSE]) / 100 / 12
    sd = np.array([_ANN[a][1] for a in UNIVERSE]) / 100 / np.sqrt(12)
    S = np.outer(sd, sd) * C

    R = rng.multivariate_normal(mu, S, N_MONTHS)
    # 꼬리를 두껍게 — 정규분포 가정의 한계를 드러내기 위함
    R += rng.standard_t(5, (N_MONTHS, n)) * 0.004
    return R


def slice_until(as_of: str, years: int, asset: str) -> list[float]:
    """도구용. as_of 이전 구간만 반환한다. 미래는 물리적으로 접근 불가."""
    end = index_of(as_of)
    start = max(0, end - years * 12)
    col = UNIVERSE.index(asset)
    return panel()[start:end, col].tolist()


def slice_between(a: int, b: int) -> np.ndarray:
    """백테스트 전용. 채점용 정답지이므로 도구 계층에서 호출하면 안 된다."""
    return panel()[a:b]


def rebalance_dates(every_m: int = 3) -> list[str]:
    return [ym(i) + "-01" for i in range(0, N_MONTHS, every_m)]
