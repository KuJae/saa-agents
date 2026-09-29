"""상태 스키마 — 모든 노드가 공유하는 계약.

여기를 바꾸면 모든 노드가 영향을 받습니다. 변경 전 팀 합의 필요.
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, TypedDict

# ─────────────────────────────────────────────────────────────
# 자산군 유니버스 (국민연금 기준)
# ─────────────────────────────────────────────────────────────
UNIVERSE: list[str] = [
    "국내주식", "해외주식(선진)", "해외주식(신흥)",
    "국내채권(국고)", "국내채권(크레딧)", "해외채권(선진)", "해외채권(신흥)",
    "국내부동산", "해외부동산", "사모주식(PE)", "인프라", "헤지펀드",
    "원자재", "단기자금",
]

EQUITY = {"국내주식", "해외주식(선진)", "해외주식(신흥)", "사모주식(PE)"}

MAX_DEBATE_ROUNDS = 3
MAX_TOOL_CALLS_PER_AGENT = 5


# ─────────────────────────────────────────────────────────────
# 값 객체
# ─────────────────────────────────────────────────────────────
class Regime(TypedDict):
    label: Literal["확장", "후기 순환", "침체", "회복"]
    probs: dict[str, float]
    confidence: float
    rationale: str


class AssetView(TypedDict):
    """자산군 에이전트의 산출물. Black-Litterman의 입력이 된다."""
    asset: str
    mu: float                      # 기대수익률 (%)
    sigma: float                   # 기대변동성 (%)
    confidence: float              # 0~1 — BL 이탈 폭을 결정
    method_values: dict[str, float]  # 방법론별 원값 보존
    rationale: str


class Challenge(TypedDict):
    round: int
    target: str                    # 지목된 자산군
    text: str
    status: Literal["open", "resolved", "partial"]


class Critique(TypedDict):
    by: str
    target: str
    text: str


class RiskVerdict(TypedDict):
    method: str
    stress: dict[str, float]
    cvar95: float
    top3_concentration: float
    liquidity: float
    verdict: Literal["승인", "조건부", "반려"]
    note: str


class ToolCall(TypedDict):
    """감사 추적이자 룩어헤드 검증의 원재료."""
    agent: str
    tool: str
    args: dict[str, Any]
    as_of: str
    cache_ns: str
    hit: bool
    ts: float


class CallRecord(TypedDict):
    node: str
    model: str
    tokens_in: int
    tokens_out: int
    seconds: float
    cached: bool


class Event(TypedDict):
    node: str
    kind: str
    detail: str


# ─────────────────────────────────────────────────────────────
# 그래프 상태
# ─────────────────────────────────────────────────────────────
def _merge_dict(a: dict, b: dict) -> dict:
    """병렬 노드가 같은 dict에 쓸 때의 리듀서."""
    return {**(a or {}), **(b or {})}


class SAAState(TypedDict, total=False):
    # 고정 입력
    as_of: str                     # 기준일 — 모든 도구가 강제로 받는다
    ips: dict[str, Any]
    universe: list[str]
    cache_ns: str                  # "default" | "masked" | "variance"
    mode: str                      # "mock" | "real"

    # 1 매크로
    regime: Regime | None

    # 2 CMA + 토론
    cma: Annotated[dict[str, AssetView], _merge_dict]
    debate_round: int
    open_challenges: list[Challenge]
    resolved_challenges: Annotated[list[Challenge], operator.add]

    # 3 공분산
    cov: list[list[float]] | None

    # 4 포트폴리오
    portfolios: Annotated[dict[str, list[float]], _merge_dict]
    ips_pass: dict[str, bool]
    ips_reasons: dict[str, str]

    # 5 검토·투표
    critiques: Annotated[list[Critique], operator.add]
    rankings: dict[str, list[str]]
    borda: dict[str, int]

    # 6 위험
    risk: dict[str, RiskVerdict]

    # 7 결합
    combine_w: dict[str, float]
    final: list[float]
    attribution: dict[str, list[float]]
    memo: str

    # 감사·비용
    tool_calls: Annotated[list[ToolCall], operator.add]
    cost_log: Annotated[list[CallRecord], operator.add]
    trace: Annotated[list[Event], operator.add]

    # 종료 사유
    halted: str | None


def initial_state(as_of: str, ips: dict, *, cache_ns: str = "default",
                  mode: str = "mock") -> SAAState:
    return SAAState(
        as_of=as_of, ips=ips, universe=list(UNIVERSE),
        cache_ns=cache_ns, mode=mode,
        regime=None, cma={}, debate_round=0,
        open_challenges=[], resolved_challenges=[],
        cov=None, portfolios={}, ips_pass={}, ips_reasons={},
        critiques=[], rankings={}, borda={}, risk={},
        combine_w={}, final=[], attribution={}, memo="",
        tool_calls=[], cost_log=[], trace=[], halted=None,
    )
