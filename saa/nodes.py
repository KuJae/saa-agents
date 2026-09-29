"""노드 구현.

LLM 노드와 결정론적 함수 노드가 명시적으로 구분되어 있습니다.
함수 노드는 LLM을 전혀 호출하지 않습니다 — 이 경계가 이 프로젝트의 설계 기여입니다.
"""
from __future__ import annotations

import math
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import numpy as np
from scipy.optimize import minimize

from . import prompts
from .llm import LLMClient
from .state import (EQUITY, MAX_DEBATE_ROUNDS, MAX_TOOL_CALLS_PER_AGENT,
                    UNIVERSE, SAAState)
from .tools import (AGENT_TOOLS, REGISTRY, ToolBudgetExceeded, _BASE,
                    call_tool, tool_schemas)

LLM: LLMClient = LLMClient()          # graph.build()에서 교체됨


def _desc(kind: str) -> str:
    return "\n".join(f"- {s['name']}: {s['description']}" for s in tool_schemas(kind))


def _ev(node: str, kind: str, detail: str) -> dict:
    return {"node": node, "kind": kind, "detail": detail}


# ═════════════════════════════════════════════════════════════
# 1. macro_agent — LLM
# ═════════════════════════════════════════════════════════════
def macro_agent(s: SAAState) -> dict:
    as_of, ns = s["as_of"], s["cache_ns"]
    budget = {"_max": MAX_TOOL_CALLS_PER_AGENT}
    calls: list = []

    for name, kw in [("get_indicator", {"name": "장단기금리차"}),
                     ("get_indicator", {"name": "제조업PMI"}),
                     ("get_yield_curve", {})]:
        try:
            _, rec = call_tool(name, agent="macro_agent", as_of=as_of,
                               cache_ns=ns, budget=budget, args=kw)
            calls.append(rec)
        except ToolBudgetExceeded:
            break

    regime = LLM.complete("macro_agent",
                          prompts.macro(as_of, _desc("macro")),
                          schema={"kind": "regime"})
    return {"regime": regime, "tool_calls": calls,
            "trace": [_ev("macro_agent", "regime", regime["label"])]}


# ═════════════════════════════════════════════════════════════
# 2. asset_agents — LLM (14 병렬)
# ═════════════════════════════════════════════════════════════
def _one_asset(asset: str, s: SAAState) -> tuple[dict, list]:
    as_of, ns = s["as_of"], s["cache_ns"]
    budget = {"_max": MAX_TOOL_CALLS_PER_AGENT}
    ctx = {"regime": s.get("regime"), "cma": s.get("cma", {})}
    calls = []

    plan = [("get_valuation", {"asset": asset}),
            ("get_returns", {"asset": asset, "years": 10})]
    # 누출 시뮬레이션: 켜면 마스킹 모드에서 주식군이 데이터를 더 조회한다.
    # 실제 LLM 툴콜링에서는 에이전트가 스스로 결정하므로 이 분기가 불필요하다.
    if os.environ.get("SIMULATE_LEAKAGE") and ns == "masked" and asset in EQUITY:
        plan += [("get_returns", {"asset": asset, "years": 20}),
                 ("get_growth_forecast", {}),
                 ("get_peer_view", {"asset": "해외주식(선진)"})]

    for name, kw in plan:
        try:
            _, rec = call_tool(name, agent=asset, as_of=as_of, cache_ns=ns,
                               budget=budget, ctx=ctx, args=kw)
            calls.append(rec)
        except ToolBudgetExceeded:
            break

    mu0, sd0 = _BASE[asset]
    view = LLM.complete("asset_agents",
                        prompts.asset_view(asset, as_of, s.get("regime") or {},
                                           _desc("asset")),
                        schema={"kind": "asset_view"},
                        mock_hint={"asset": asset, "base_mu": mu0, "base_sd": sd0})
    return view, calls


def asset_agents(s: SAAState) -> dict:
    targets = s["universe"]
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(lambda a: _one_asset(a, s), targets))
    cma = {v["asset"]: v for v, _ in results}
    calls = [c for _, cs in results for c in cs]
    return {"cma": cma, "debate_round": 1, "tool_calls": calls,
            "trace": [_ev("asset_agents", "cma", f"{len(cma)}개 자산군 추정 완료")]}


# ═════════════════════════════════════════════════════════════
# 3. challenger — LLM
# ═════════════════════════════════════════════════════════════
def challenger(s: SAAState) -> dict:
    cma = s["cma"]
    rnd = s["debate_round"]
    # 방법론 편차가 큰 순으로 반박 후보 정렬
    spread = {a: max(v["method_values"].values()) - min(v["method_values"].values())
              for a, v in cma.items()}
    cands = sorted(spread, key=spread.get, reverse=True)

    raw = LLM.complete("challenger",
                       prompts.challenge({a: cma[a]["mu"] for a in cma},
                                         "주식군 내 상관은 0.8 이상", rnd),
                       schema={"kind": "challenges"},
                       mock_hint={"round": rnd, "candidates": cands})
    return {"open_challenges": raw,
            "trace": [_ev("challenger", "challenge", f"{rnd}라운드 반박 {len(raw)}건")]}


# ═════════════════════════════════════════════════════════════
# 4. revise_agents — LLM (반박받은 자산군만)
# ═════════════════════════════════════════════════════════════
def revise_agents(s: SAAState) -> dict:
    cma = dict(s["cma"])
    open_ch = s["open_challenges"]
    targets = sorted({c["target"] for c in open_ch})
    resolved, still_open = [], []

    for a in targets:
        chs = [c for c in open_ch if c["target"] == a]
        cur = cma[a]
        out = LLM.complete("asset_agents",
                           prompts.revise(a, cur, chs, _desc("asset")),
                           schema={"kind": "revision"},
                           mock_hint={"current": cur})
        cma[a] = {**cur, "mu": out["mu"], "confidence": out["confidence"],
                  "rationale": out["rationale"]}
        for c in chs:
            resolved.append({**c, "status": "resolved" if out["accepted"] else "open"})
            if not out["accepted"]:
                still_open.append(c)

    return {"cma": cma, "debate_round": s["debate_round"] + 1,
            "open_challenges": still_open, "resolved_challenges": resolved,
            "trace": [_ev("revise_agents", "revision",
                          f"{len(targets)}개 재추정 · 미해결 {len(still_open)}건")]}


# ═════════════════════════════════════════════════════════════
# 5. 조건부 분기 — 함수
# ═════════════════════════════════════════════════════════════
def route_debate(s: SAAState) -> str:
    if not s["open_challenges"]:
        return "cov_estimator"
    if s["debate_round"] >= MAX_DEBATE_ROUNDS:
        return "halt_debate"
    return "revise_agents"


def halt_debate(s: SAAState) -> dict:
    """상한 도달. 미해결 반박을 버리지 않고 확신도에 반영한다."""
    cma = dict(s["cma"])
    hit = sorted({c["target"] for c in s["open_challenges"]})
    for a in hit:
        v = cma[a]
        cma[a] = {**v, "confidence": round(max(0.15, v["confidence"] * 0.72), 2)}
    return {"cma": cma,
            "halted": f"토론 상한 {MAX_DEBATE_ROUNDS}라운드 도달 · 미해결 {len(s['open_challenges'])}건",
            "trace": [_ev("halt_debate", "forced",
                          f"{', '.join(hit)} 확신도 하향")]}


# ═════════════════════════════════════════════════════════════
# 6. cov_estimator — 함수 (LLM 없음)
# ═════════════════════════════════════════════════════════════
def cov_estimator(s: SAAState) -> dict:
    u = s["universe"]
    n = len(u)
    grp = {a: ("주식" if a in EQUITY else "채권" if "채권" in a
               else "현금" if a == "단기자금" else "대체") for a in u}
    base = {("주식", "주식"): .78, ("채권", "채권"): .62, ("대체", "대체"): .45,
            ("주식", "채권"): .12, ("주식", "대체"): .52, ("채권", "대체"): .22,
            ("현금", "주식"): .02, ("현금", "채권"): .18, ("현금", "대체"): .04}
    rng = np.random.default_rng(abs(hash(s["as_of"])) % (2**32))
    C = np.eye(n)
    for i in range(n):
        for j in range(i + 1, n):
            k = (grp[u[i]], grp[u[j]])
            v = base.get(k, base.get(k[::-1], .2)) + rng.normal(0, .07)
            C[i, j] = C[j, i] = float(np.clip(v, -.2, .96))
    w, V = np.linalg.eigh(C)
    C = V @ np.diag(np.clip(w, 1e-4, None)) @ V.T
    d = np.sqrt(np.diag(C)); C = C / np.outer(d, d)

    # Ledoit-Wolf 축소 (상수상관 타깃)
    off = C[~np.eye(n, dtype=bool)]
    T = np.full((n, n), off.mean()); np.fill_diagonal(T, 1.0)
    alpha = 0.31
    Cs = alpha * T + (1 - alpha) * C

    vol = np.array([s["cma"][a]["sigma"] for a in u]) / 100
    S = np.outer(vol, vol) * Cs
    return {"cov": S.tolist(),
            "trace": [_ev("cov_estimator", "shrinkage", f"alpha={alpha}")]}


# ═════════════════════════════════════════════════════════════
# 7. optimizers — 함수 (LLM 없음)
# ═════════════════════════════════════════════════════════════
def optimizers(s: SAAState) -> dict:
    u = s["universe"]
    mu = np.array([s["cma"][a]["mu"] for a in u]) / 100
    S = np.array(s["cov"])
    bands = s["ips"]["bands"]
    lo = np.array([bands[a][0] for a in u]) / 100
    hi = np.array([bands[a][1] for a in u]) / 100
    cons = [{"type": "eq", "fun": lambda w: w.sum() - 1}]
    bnds = list(zip(lo, hi))
    x0 = np.clip(np.ones(len(u)) / len(u), lo, hi); x0 = x0 / x0.sum()

    def solve(f):
        r = minimize(f, x0, method="SLSQP", bounds=bnds, constraints=cons,
                     options={"maxiter": 600, "ftol": 1e-11})
        w = np.clip(r.x, 0, None)
        return (w / w.sum()).tolist()

    mkt = np.array(s["ips"]["market"]) / 100; mkt = mkt / mkt.sum()
    tau, delta = .05, 2.8
    pi = delta * S @ mkt
    conf = np.array([s["cma"][a]["confidence"] for a in u])
    mu_bl = 0.5 * pi + 0.5 * (mu * conf + pi * (1 - conf))

    P = {
        "MV":     solve(lambda w: -(w @ mu) + 3.0 * (w @ S @ w)),
        "BL":     solve(lambda w: -(w @ mu_bl) + 3.0 * (w @ S @ w)),
        "MinV":   solve(lambda w: w @ S @ w),
        "Robust": solve(lambda w: -(w @ (mu - .5 * np.sqrt(np.diag(S))))
                        + 3.0 * (w @ S @ w)),
        "RP":     solve(lambda w: float(((w * (S @ w) / max(1e-9, math.sqrt(w @ S @ w))
                                          - (w @ S @ w) / len(u)) ** 2).sum() * 1e4)),
    }
    iv = 1 / np.sqrt(np.diag(S)); w = np.clip(iv / iv.sum(), lo, hi)
    P["InvVol"] = (w / w.sum()).tolist()
    w = np.clip(np.ones(len(u)) / len(u), lo, hi)
    P["EW"] = (w / w.sum()).tolist()

    return {"portfolios": P,
            "trace": [_ev("optimizers", "solve", f"{len(P)}개 후보 생성")]}


# ═════════════════════════════════════════════════════════════
# 8. ips_gate — 함수 (LLM 없음)
# ═════════════════════════════════════════════════════════════
def ips_gate(s: SAAState) -> dict:
    u = s["universe"]
    bands = s["ips"]["bands"]
    eq_cap = s["ips"].get("equity_cap", 0.55)
    ok, why = {}, {}
    for m, w in s["portfolios"].items():
        bad = [f"{a} {w[i]*100:.1f}%"
               for i, a in enumerate(u)
               if not (bands[a][0] / 100 - 1e-6 <= w[i] <= bands[a][1] / 100 + 1e-6)]
        eq = sum(w[i] for i, a in enumerate(u) if a in EQUITY)
        if eq > eq_cap + 1e-6:
            bad.append(f"주식성 합계 {eq*100:.1f}%")
        ok[m] = not bad
        why[m] = "§4-2/§4-5 위반: " + ", ".join(bad) if bad else "통과"
    return {"ips_pass": ok, "ips_reasons": why,
            "trace": [_ev("ips_gate", "check",
                          f"{sum(ok.values())}/{len(ok)} 통과")]}


def route_ips(s: SAAState) -> str:
    return "escalate" if not any(s["ips_pass"].values()) else "review_agents"


def escalate(s: SAAState) -> dict:
    return {"halted": "IPS를 통과한 후보가 없습니다. 사람의 개입이 필요합니다.",
            "trace": [_ev("escalate", "halt", "human-in-the-loop")]}


# ═════════════════════════════════════════════════════════════
# 9. review_agents — LLM (비판 + 순위)
# ═════════════════════════════════════════════════════════════
N_REVIEWERS = 8


def review_agents(s: SAAState) -> dict:
    valid = [m for m, ok in s["ips_pass"].items() if ok]
    crits = []
    for m in valid[:5]:
        out = LLM.complete("critic_agents",
                           prompts.critique(m, {}, {}),
                           schema={"kind": "critique"}, mock_hint={"target": m})
        crits.append({"by": m, "target": valid[0] if m != valid[0] else valid[-1],
                      "text": out["text"]})

    rankings, borda = {}, {m: 0 for m in valid}
    for i in range(N_REVIEWERS):
        order = LLM.complete("ranker_agents",
                             prompts.ranking(valid, {"reviewer": i}),
                             schema={"kind": "ranking"},
                             mock_hint={"candidates": valid})
        rankings[f"reviewer_{i}"] = order
        for pos, m in enumerate(order):
            borda[m] += len(valid) - 1 - pos

    return {"critiques": crits, "rankings": rankings, "borda": borda,
            "trace": [_ev("review_agents", "vote",
                          f"{N_REVIEWERS}명 순위투표 · 1위 {max(borda, key=borda.get)}")]}


# ═════════════════════════════════════════════════════════════
# 10. risk_agent — 하이브리드 (계산은 함수, 서술은 LLM)
# ═════════════════════════════════════════════════════════════
SCENARIOS = {
    "2008형 신용경색": [-.42, -.38, -.48, .09, -.06, .04, -.18, -.28, -.34, -.45, -.19, -.16, -.31, .01],
    "2020형 급락":     [-.31, -.29, -.33, .05, -.03, .03, -.11, -.14, -.21, -.24, -.12, -.09, -.36, .00],
    "금리 200bp 급등": [-.14, -.12, -.17, -.11, -.13, -.12, -.16, -.13, -.15, -.11, -.10, -.05, .03, .01],
}
LIQ = np.array([1, 1, 1, 1, .9, .9, .7, 0, 0, 0, 0, .3, 1, 1.0])


def risk_agent(s: SAAState) -> dict:
    S = np.array(s["cov"])
    mu = np.array([s["cma"][a]["mu"] for a in s["universe"]]) / 100
    out = {}
    for m, ok in s["ips_pass"].items():
        if not ok:
            continue
        w = np.array(s["portfolios"][m])
        sd = float(np.sqrt(w @ S @ w))
        rc = (w * (S @ w) / sd) / sd
        stress = {k: round(float(w @ np.array(v)) * 100, 1)
                  for k, v in SCENARIOS.items()}
        top3 = round(float(np.sort(rc)[::-1][:3].sum()) * 100, 1)
        liq = round(float(w @ LIQ) * 100, 1)
        cvar = round(float(-(w @ mu) + 2.063 * sd) * 100, 1)
        worst = min(stress.values())
        verdict = ("반려" if (worst < -26 or liq < 55)
                   else "조건부" if (worst < -22 or top3 > 80) else "승인")
        note = LLM.complete("risk_agent",
                            prompts.risk_note(m, {"stress": stress, "top3": top3}),
                            schema={"kind": "risk_note"})["note"]
        out[m] = {"method": m, "stress": stress, "cvar95": cvar,
                  "top3_concentration": top3, "liquidity": liq,
                  "verdict": verdict, "note": note}
    n_bad = sum(1 for v in out.values() if v["verdict"] != "승인")
    return {"risk": out,
            "trace": [_ev("risk_agent", "screen", f"조건부·반려 {n_bad}건")]}


# ═════════════════════════════════════════════════════════════
# 11. combine — 함수 (LLM 없음)
# ═════════════════════════════════════════════════════════════
ADJ = {"승인": 1.0, "조건부": 0.5, "반려": 0.0}


def combine(s: SAAState) -> dict:
    borda, risk = s["borda"], s["risk"]
    raw = {m: borda[m] * ADJ[risk[m]["verdict"]] for m in borda if m in risk}
    tot = sum(raw.values()) or 1.0
    cw = {m: v / tot for m, v in raw.items()}
    n = len(s["universe"])
    final = [sum(cw[m] * s["portfolios"][m][i] for m in cw) for i in range(n)]
    attr = {m: [cw[m] * s["portfolios"][m][i] * 100 for i in range(n)] for m in cw}
    return {"combine_w": {m: round(v * 100, 1) for m, v in cw.items()},
            "final": [round(x * 100, 2) for x in final],
            "attribution": {m: [round(x, 2) for x in v] for m, v in attr.items()},
            "trace": [_ev("combine", "blend", f"{len(cw)}개 결합")]}


# ═════════════════════════════════════════════════════════════
# 12. memo_writer — LLM
# ═════════════════════════════════════════════════════════════
def memo_writer(s: SAAState) -> dict:
    ctx = {"combine_w": s["combine_w"], "regime": (s.get("regime") or {}).get("label"),
           "halted": s.get("halted")}
    out = LLM.complete("memo_writer",
                       prompts.board_memo(dict(zip(s["universe"], s["final"])), ctx),
                       schema={"kind": "memo"})
    return {"memo": out["text"],
            "trace": [_ev("memo_writer", "memo", f"{len(out['text'])}자")]}
