"""도구 계층.

설계 원칙 세 가지:
  1. 모든 도구가 as_of를 강제로 받는다 — 미래 데이터를 물리적으로 차단
  2. 모든 호출을 로깅한다 — 감사 추적이자 룩어헤드 검증의 원재료
  3. 캐시 키에 as_of와 cache_ns가 반드시 들어간다 — 시점 간 오염 방지
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable

from .state import ToolCall

CACHE_DB = Path(__file__).parent.parent / ".cache" / "tools.sqlite"


# ─────────────────────────────────────────────────────────────
# 캐시
# ─────────────────────────────────────────────────────────────
class Cache:
    def __init__(self, path: Path = CACHE_DB):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False,
                                    isolation_level=None, timeout=30)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT, ts REAL)"
        )
        self.lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: str):
        with self.lock:
            row = self.conn.execute("SELECT v FROM kv WHERE k=?", (key,)).fetchone()
            if row is None:
                self.misses += 1
                return None
            self.hits += 1
            return json.loads(row[0])

    def put(self, key: str, value) -> None:
        with self.lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO kv VALUES (?,?,?)",
                (key, json.dumps(value, ensure_ascii=False), time.time()),
            )

    @property
    def hit_rate(self) -> float:
        n = self.hits + self.misses
        return self.hits / n if n else 0.0

    def clear(self) -> None:
        with self.lock:
            self.conn.execute("DELETE FROM kv")
            self.hits = self.misses = 0


CACHE = Cache()


def _key(*parts: Any) -> str:
    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _seeded(*parts: Any) -> random.Random:
    """(시점, 자산 등)에 결정론적으로 묶인 난수원. 목 데이터 재현성 확보."""
    return random.Random(int(_key(*parts)[:8], 16))


# ─────────────────────────────────────────────────────────────
# 합성 데이터 (실제 구현에서는 WRDS·한국은행·KRX 연결로 교체)
# ─────────────────────────────────────────────────────────────
_BASE = {
    "국내주식": (5.9, 16.5), "해외주식(선진)": (6.4, 15.2), "해외주식(신흥)": (7.1, 19.8),
    "국내채권(국고)": (3.2, 4.1), "국내채권(크레딧)": (3.9, 5.0),
    "해외채권(선진)": (3.6, 6.2), "해외채권(신흥)": (5.2, 9.4),
    "국내부동산": (5.4, 10.8), "해외부동산": (5.8, 12.6), "사모주식(PE)": (8.2, 21.0),
    "인프라": (5.6, 11.2), "헤지펀드": (4.8, 7.6), "원자재": (3.4, 17.4),
    "단기자금": (2.6, 0.9),
}

_INDICATORS = {
    "장단기금리차": 0.24, "제조업PMI": 49.6, "실업률갭": -0.4,
    "신용스프레드": 1.18, "근원CPI": 2.6, "실질정책금리": 1.1,
}


# ─────────────────────────────────────────────────────────────
# 도구 레지스트리
# ─────────────────────────────────────────────────────────────
REGISTRY: dict[str, dict] = {}


def tool(name: str, desc: str, params: dict):
    def deco(fn: Callable):
        REGISTRY[name] = {"fn": fn, "desc": desc, "params": params}
        return fn
    return deco


@tool("list_indicators", "조회 가능한 거시 지표 목록", {})
def list_indicators(*, as_of: str) -> list[str]:
    return sorted(_INDICATORS)


@tool("get_indicator", "거시 지표 시계열",
      {"name": "지표명", "lookback_m": "조회 개월수 (기본 24)"})
def get_indicator(*, as_of: str, name: str, lookback_m: int = 24) -> dict:
    if name not in _INDICATORS:
        return {"error": f"알 수 없는 지표: {name}", "available": sorted(_INDICATORS)}
    rng = _seeded(as_of, name)
    base = _INDICATORS[name]
    series = [round(base + rng.gauss(0, abs(base) * 0.12 + 0.05), 3)
              for _ in range(min(lookback_m, 60))]
    return {"name": name, "as_of": as_of, "latest": series[-1],
            "mean": round(sum(series) / len(series), 3), "series": series[-12:]}


@tool("get_yield_curve", "만기별 금리", {})
def get_yield_curve(*, as_of: str) -> dict:
    rng = _seeded(as_of, "curve")
    short = 2.9 + rng.gauss(0, 0.2)
    return {"as_of": as_of, "curve": {
        "3M": round(short, 2), "2Y": round(short + 0.15, 2),
        "5Y": round(short + 0.28, 2), "10Y": round(short + 0.39, 2),
        "30Y": round(short + 0.46, 2)}}


@tool("get_valuation", "자산군 밸류에이션 (CAPE·배당·자사주)",
      {"asset": "자산군명"})
def get_valuation(*, as_of: str, asset: str) -> dict:
    if asset not in _BASE:
        return {"error": f"알 수 없는 자산군: {asset}"}
    rng = _seeded(as_of, asset, "val")
    return {"asset": asset, "as_of": as_of,
            "cape": round(14 + rng.gauss(0, 4), 1),
            "dividend_yield": round(max(0.0, rng.gauss(2.1, 0.8)), 2),
            "buyback_yield": round(max(0.0, rng.gauss(0.9, 0.5)), 2)}


@tool("get_returns", "과거 수익률", {"asset": "자산군명", "years": "조회 연수"})
def get_returns(*, as_of: str, asset: str, years: int = 10) -> dict:
    """as_of 이전 구간만 반환한다. 미래 수익률은 이 도구로 접근할 수 없다."""
    if asset not in _BASE:
        return {"error": f"알 수 없는 자산군: {asset}"}
    from . import market
    m = market.slice_until(as_of, years, asset)
    if len(m) < 6:
        return {"asset": asset, "as_of": as_of, "note": "관측치 부족", "monthly": m}
    avg = sum(m) / len(m)
    vol = math.sqrt(sum((x - avg) ** 2 for x in m) / max(1, len(m) - 1))
    return {"asset": asset, "as_of": as_of, "n_months": len(m),
            "ann_mean": round(avg * 12 * 100, 2),
            "ann_vol": round(vol * math.sqrt(12) * 100, 2),
            "recent_12m": [round(x * 100, 2) for x in m[-12:]]}


@tool("get_growth_forecast", "실질성장·인플레 컨센서스", {})
def get_growth_forecast(*, as_of: str) -> dict:
    rng = _seeded(as_of, "growth")
    return {"as_of": as_of,
            "real_gdp": round(2.0 + rng.gauss(0, 0.4), 2),
            "inflation": round(2.2 + rng.gauss(0, 0.3), 2)}


@tool("get_regime", "매크로 에이전트가 판정한 현재 국면", {})
def get_regime(*, as_of: str, _regime: dict | None = None) -> dict:
    return _regime or {"error": "국면이 아직 판정되지 않았습니다"}


@tool("get_peer_view", "다른 자산군 에이전트의 현재 추정 — 에이전트 간 통신 창구",
      {"asset": "자산군명"})
def get_peer_view(*, as_of: str, asset: str, _cma: dict | None = None) -> dict:
    v = (_cma or {}).get(asset)
    if not v:
        return {"error": f"{asset}의 추정이 아직 제출되지 않았습니다"}
    return {"asset": asset, "mu": v["mu"], "sigma": v["sigma"],
            "confidence": v["confidence"]}


AGENT_TOOLS = {
    "macro": ["list_indicators", "get_indicator", "get_yield_curve"],
    "asset": ["get_valuation", "get_returns", "get_growth_forecast",
              "get_regime", "get_peer_view"],
}


# ─────────────────────────────────────────────────────────────
# 마스킹 — 룩어헤드 검증용
# ─────────────────────────────────────────────────────────────
def mask_payload(obj: Any) -> Any:
    """날짜와 고유명사를 제거하고 수치 패턴만 남긴다."""
    if isinstance(obj, dict):
        return {k: ("[MASKED]" if k in ("as_of", "asset", "name") else mask_payload(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [mask_payload(x) for x in obj]
    return obj


# ─────────────────────────────────────────────────────────────
# 호출 진입점
# ─────────────────────────────────────────────────────────────
class ToolBudgetExceeded(Exception):
    pass


def call_tool(tool_name: str, *, agent: str, as_of: str, cache_ns: str = "default",
              budget: dict | None = None, ctx: dict | None = None,
              args: dict | None = None) -> tuple[Any, ToolCall]:
    """도구 1회 호출. 결과와 감사 레코드를 함께 반환한다.

    도구 인자는 args dict로 받는다 — 도구가 name 같은 인자를 쓰더라도
    이 함수의 파라미터와 충돌하지 않게 하기 위함.
    """
    if tool_name not in REGISTRY:
        raise KeyError(f"등록되지 않은 도구: {tool_name}")
    args = dict(args or {})

    if budget is not None:
        used = budget.get(agent, 0)
        if used >= budget.get("_max", 5):
            raise ToolBudgetExceeded(f"{agent}: 도구 호출 상한 초과")
        budget[agent] = used + 1

    ck = _key("tool", tool_name, args, as_of, cache_ns)
    cached = CACHE.get(ck)
    if cached is not None:
        result, hit = cached, True
    else:
        fn = REGISTRY[tool_name]["fn"]
        extra = {}
        if tool_name == "get_regime":
            extra["_regime"] = (ctx or {}).get("regime")
        if tool_name == "get_peer_view":
            extra["_cma"] = (ctx or {}).get("cma")
        result = fn(as_of=as_of, **args, **extra)
        if cache_ns == "masked":
            result = mask_payload(result)
        CACHE.put(ck, result)
        hit = False

    rec: ToolCall = {"agent": agent, "tool": tool_name, "args": args, "as_of": as_of,
                     "cache_ns": cache_ns, "hit": hit, "ts": time.time()}
    return result, rec


def tool_schemas(kind: str) -> list[dict]:
    """LLM 툴콜링에 넘길 스키마."""
    return [{"name": n, "description": REGISTRY[n]["desc"],
             "parameters": REGISTRY[n]["params"]}
            for n in AGENT_TOOLS[kind]]
