"""백테스트 엔진.

제안서 연구내용 1번의 실증 도구.
결합 방식이 단일 방법론 대비 개선을 만드는지 확인하되,
모델 학습 시점을 기준으로 구간을 나누어 결과의 신뢰성을 함께 검증한다.

  컷오프 이전 구간  — LLM이 결과를 이미 알고 있었을 수 있음
  컷오프 이후 구간  — 진짜 시험 구간

두 구간의 성과 차이가 곧 룩어헤드의 크기다.
"""
from __future__ import annotations

import math
import os

import numpy as np

from . import market
from .state import UNIVERSE

STRATEGIES = ["결합(에이전트)", "BL 고정", "RP 고정", "동일가중", "시장균형"]


def _tilt_by_future(w: np.ndarray, fwd: np.ndarray, strength: float = .025,
                    lo=None, hi=None) -> np.ndarray:
    """누출 시뮬레이션. 앞으로 오를 자산으로 비중을 기울인다.

    실제 LLM에서는 학습된 기억이 이 역할을 하므로 이 함수가 불필요하다.
    탐지기가 작동하는지 확인할 때만 SIMULATE_LEAKAGE=1 로 켠다.
    """
    z = (fwd - fwd.mean()) / (fwd.std() + 1e-9)
    out = w + strength * z
    if lo is not None:
        out = np.clip(out, lo, hi)
    return np.clip(out, 0, None) / max(1e-9, np.clip(out, 0, None).sum())


def run(runner, dates: list[str], *, every_m: int = 3, verbose: bool = True) -> dict:
    """runner(as_of) -> state 를 각 시점에 호출해 NAV 경로를 만든다."""
    leak = bool(os.environ.get("SIMULATE_LEAKAGE"))
    n = len(UNIVERSE)
    R = market.panel()
    T = market.N_MONTHS

    mkt = None
    holdings: dict[str, np.ndarray] = {}
    nav = {s: [100.0] for s in STRATEGIES}
    schedule: dict[int, str] = {market.index_of(d): d for d in dates}

    for t in range(T):
        if t in schedule:
            st = runner(schedule[t])
            if mkt is None:
                m = np.array(st["ips"]["market"], dtype=float)
                mkt = m / m.sum()
            combined = np.array(st["final"]) / 100
            if leak and t < market.CUTOFF_IDX:
                fwd = R[t:min(t + 3, T)].sum(0)
                bands = st["ips"]["bands"]
                lo = np.array([bands[a][0] for a in UNIVERSE]) / 100
                hi = np.array([bands[a][1] for a in UNIVERSE]) / 100
                combined = _tilt_by_future(combined, fwd, lo=lo, hi=hi)
            holdings = {
                "결합(에이전트)": combined,
                "BL 고정": np.array(st["portfolios"]["BL"]),
                "RP 고정": np.array(st["portfolios"]["RP"]),
                "동일가중": np.array(st["portfolios"]["EW"]),
                "시장균형": mkt,
            }
            if verbose:
                print(f"  {market.ym(t)}  리밸런싱", flush=True)

        r = R[t]
        for s in STRATEGIES:
            nav[s].append(nav[s][-1] * (1 + float(holdings[s] @ r)))

    return {"months": [market.ym(i) for i in range(T)],
            "cutoff_idx": market.CUTOFF_IDX,
            "cutoff": market.MODEL_CUTOFF,
            "nav": {s: [round(x, 2) for x in v] for s, v in nav.items()},
            "pre": {s: metrics(v, 0, market.CUTOFF_IDX) for s, v in nav.items()},
            "post": {s: metrics(v, market.CUTOFF_IDX, T) for s, v in nav.items()},
            "full": {s: metrics(v, 0, T) for s, v in nav.items()},
            "leakage_simulated": leak}


def metrics(v: list[float], a: int, b: int) -> dict:
    """구간 [a, b) 의 성과 지표."""
    seg = v[a:b + 1]
    yrs = (b - a) / 12
    cagr = ((seg[-1] / seg[0]) ** (1 / yrs) - 1) * 100
    lr = np.diff(np.log(seg))
    vol = float(lr.std(ddof=1) * math.sqrt(12) * 100) if len(lr) > 1 else 0.0
    peak, mdd = seg[0], 0.0
    for x in seg:
        peak = max(peak, x)
        mdd = min(mdd, x / peak - 1)
    return {"cagr": round(cagr, 2), "vol": round(vol, 2),
            "ratio": round(cagr / vol, 2) if vol else 0.0,
            "mdd": round(mdd * 100, 1), "months": b - a}


def report(bt: dict) -> None:
    c = bt["cutoff"]
    print(f"\n{'='*72}")
    print(f"백테스트  {bt['months'][0]} ~ {bt['months'][-1]}  ·  학습 컷오프 {c}")
    if bt["leakage_simulated"]:
        print("!! 누출 시뮬레이션 켜짐 — 컷오프 이전 구간에 미래 정보가 주입됨")
    print("=" * 72)

    for title, key in [(f"컷오프 이전  ~{c}", "pre"), (f"컷오프 이후  {c}~", "post")]:
        d = bt[key]
        print(f"\n{title}   ({d[STRATEGIES[0]]['months']}개월)")
        print(f"  {'전략':<14} {'연평균':>8} {'변동성':>8} {'수익/위험':>9} {'최대낙폭':>9}")
        best = max(x["cagr"] for x in d.values())
        for s in STRATEGIES:
            m = d[s]
            mark = " ←" if m["cagr"] == best else ""
            print(f"  {s:<14} {m['cagr']:7.2f}% {m['vol']:7.2f}% "
                  f"{m['ratio']:9.2f} {m['mdd']:8.1f}%{mark}")

    a = bt["pre"]["결합(에이전트)"]["cagr"] - bt["pre"]["BL 고정"]["cagr"]
    b = bt["post"]["결합(에이전트)"]["cagr"] - bt["post"]["BL 고정"]["cagr"]
    print(f"\nBL 고정 대비 초과수익")
    print(f"  컷오프 이전 {a:+.2f}%p  →  컷오프 이후 {b:+.2f}%p   (격차 {a-b:+.2f}%p)")

    post = bt["post"]
    winner = max(post, key=lambda s: post[s]["cagr"])
    if winner != "결합(에이전트)":
        print(f"\n  컷오프 이후 구간에서는 '{winner}'이 결합 전략을 앞섭니다.")
        print(f"  누출이 없는 구간에서 우위가 관측되지 않았다는 뜻입니다.")
    print(f"\n  사후 구간이 {post['결합(에이전트)']['months']}개월로 짧아 "
          f"통계적 유의성은 주장하기 어렵습니다.")
