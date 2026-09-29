"""실행 엔트리.

  python run.py once                 1개 시점 실행
  python run.py backtest --n 4       분기별 백테스트
  python run.py variance --n 20      같은 입력 반복 → 판단 편차 측정
  python run.py masked               원본 vs 마스킹 도구 호출 대조
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from saa.graph import build
from saa.state import UNIVERSE, initial_state
from saa.tools import CACHE

IPS = {
    "version": "v4.2",
    "equity_cap": 0.55,
    "bands": {
        "국내주식": [10, 20], "해외주식(선진)": [20, 38], "해외주식(신흥)": [3, 10],
        "국내채권(국고)": [15, 32], "국내채권(크레딧)": [3, 12],
        "해외채권(선진)": [2, 10], "해외채권(신흥)": [0, 5],
        "국내부동산": [2, 9], "해외부동산": [2, 9], "사모주식(PE)": [2, 10],
        "인프라": [1, 7], "헤지펀드": [0, 6], "원자재": [0, 4], "단기자금": [1, 8],
    },
    "market": [15.5, 30.5, 5.5, 24.5, 6.5, 4.5, 2.0, 5.0, 4.5, 5.5, 3.0, 1.5, 0.5, 1.0],
}


def run_once(as_of: str, *, cache_ns="default", variance=False, quiet=False):
    app, client = build(cache_ns=cache_ns, variance=variance)
    cfg = {"configurable": {"thread_id": f"bt_{as_of}_{cache_ns}"}}
    out = app.invoke(initial_state(as_of, IPS, cache_ns=cache_ns), cfg)
    if not quiet:
        _report(out, client)
    return out, client


def _report(s, client):
    print(f"\n{'='*66}\n기준일 {s['as_of']}  ·  IPS {s['ips']['version']}\n{'='*66}")
    r = s["regime"]
    print(f"국면       {r['label']} (확신도 {r['confidence']})")
    print(f"토론       {s['debate_round']}라운드 · 해결 {len(s['resolved_challenges'])}건"
          f" · 미해결 {len(s['open_challenges'])}건")
    if s.get("halted"):
        print(f"           ! {s['halted']}")
    npass = sum(s["ips_pass"].values())
    print(f"IPS 심사   {npass}/{len(s['ips_pass'])} 통과")
    for m, ok in s["ips_pass"].items():
        if not ok:
            print(f"           × {m}: {s['ips_reasons'][m]}")
    print(f"순위투표   " + " · ".join(
        f"{m} {v}" for m, v in sorted(s["borda"].items(), key=lambda x: -x[1])[:4]))
    bad = [f"{m}({v['verdict']})" for m, v in s["risk"].items() if v["verdict"] != "승인"]
    print(f"위험심사   {'전부 승인' if not bad else ' '.join(bad)}")
    print(f"결합가중   " + " · ".join(
        f"{m} {v}%" for m, v in sorted(s["combine_w"].items(), key=lambda x: -x[1])))
    print("\n최종 배분")
    for a, w in zip(s["universe"], s["final"]):
        if w >= 0.05:
            print(f"  {a:<16} {w:6.2f}%   " + "█" * int(w / 1.2))
    print(f"  {'합계':<16} {sum(s['final']):6.2f}%")

    n_llm = len(client.calls)
    n_cached = sum(1 for c in client.calls if c["cached"])
    tok = sum(c["tokens_in"] + c["tokens_out"] for c in client.calls)
    by = Counter(c["node"] for c in client.calls)
    print(f"\nLLM 호출   {n_llm}회 (캐시 {n_cached}) · 토큰 {tok:,}")
    print(f"           " + " · ".join(f"{k} {v}" for k, v in by.most_common()))
    print(f"도구 호출  {len(s['tool_calls'])}회 · 캐시 적중률 {CACHE.hit_rate:.1%}")


def cmd_backtest(n: int | None, *, every_m: int = 3, export: str | None = None):
    from saa import backtest, market
    dates = market.rebalance_dates(every_m)
    if n:
        dates = dates[:n]
    print(f"리밸런싱 {len(dates)}개 시점 · 파이프라인 실행 중\n")

    states, costs = {}, []

    def runner(as_of):
        out, cl = run_once(as_of, quiet=True)
        states[as_of] = out
        costs.append((as_of, len(cl.calls),
                      sum(c["tokens_in"] + c["tokens_out"] for c in cl.calls)))
        return out

    bt = backtest.run(runner, dates, every_m=every_m, verbose=False)
    backtest.report(bt)

    tc = sum(c[1] for c in costs)
    tt = sum(c[2] for c in costs)
    print(f"\n파이프라인  {len(costs)}회 실행 · LLM {tc:,}회 · 토큰 {tt:,}")
    print(f"            도구 캐시 적중률 {CACHE.hit_rate:.1%}")

    if export:
        import json as _j
        payload = {"backtest": bt,
                   "cost": [{"as_of": a, "calls": c, "tokens": t} for a, c, t in costs]}
        Path(export).write_text(_j.dumps(payload, ensure_ascii=False), encoding="utf-8")
        print(f"            → {export}")
    return bt


def cmd_variance(n: int, as_of: str):
    print(f"판단 편차 측정 · {as_of} · {n}회 반복\n")
    vals = defaultdict(list)
    for _ in range(n):
        out, _ = run_once(as_of, variance=True, quiet=True)
        for a, v in out["cma"].items():
            vals[a].append(v["mu"])
    print(f"  {'자산군':<16} {'평균':>7} {'표준편차':>9} {'범위':>9}")
    import statistics as st
    rows = []
    for a in UNIVERSE:
        v = vals[a]
        sd = st.pstdev(v) if len(v) > 1 else 0.0
        rows.append((a, st.mean(v), sd, max(v) - min(v)))
    for a, m, sd, rg in sorted(rows, key=lambda x: -x[2]):
        print(f"  {a:<16} {m:7.2f} {sd:9.3f} {rg:9.2f}")
    print(f"\n  최대 편차 {max(r[2] for r in rows):.3f}%p — "
          f"방법론 간 편차와 비교하면 에이전트 비결정성의 상대적 크기가 나옵니다.")


def cmd_masked(as_of: str):
    print(f"룩어헤드 대조 · {as_of}\n")
    a, _ = run_once(as_of, cache_ns="default", quiet=True)
    b, _ = run_once(as_of, cache_ns="masked", quiet=True)

    def by_agent(s):
        d = defaultdict(Counter)
        for t in s["tool_calls"]:
            d[t["agent"]][t["tool"]] += 1
        return d

    A, B = by_agent(a), by_agent(b)
    print(f"  {'에이전트':<16} {'원본':>5} {'마스킹':>7} {'증가':>7}  판정")
    for ag in sorted(set(A) | set(B)):
        na, nb = sum(A[ag].values()), sum(B[ag].values())
        delta = (nb - na) / na * 100 if na else 0.0
        flag = "통과" if abs(delta) < 15 else ("불안정" if delta < 100 else "위반")
        print(f"  {ag:<16} {na:5d} {nb:7d} {delta:6.0f}%  {flag}")
    print("\n  조회량이 크게 늘었다면 원본 실행에서 조회 없이 답했다는 뜻입니다.")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["once", "backtest", "variance", "masked"])
    p.add_argument("--as-of", default="2026-09-01")
    p.add_argument("--n", type=int, default=4)
    p.add_argument("--clear-cache", action="store_true")
    p.add_argument("--every", type=int, default=3, help="리밸런싱 주기 (개월)")
    p.add_argument("--export", default=None, help="결과 JSON 경로")
    p.add_argument("--all", action="store_true", help="전 구간 43개 시점")
    a = p.parse_args()
    if a.clear_cache:
        CACHE.clear(); print("캐시 초기화\n")
    if a.cmd == "once":
        run_once(a.as_of)
    elif a.cmd == "backtest":
        cmd_backtest(None if a.all else a.n, every_m=a.every, export=a.export)
    elif a.cmd == "variance":
        cmd_variance(a.n, a.as_of)
    else:
        cmd_masked(a.as_of)
