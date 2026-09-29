"""프롬프트.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
이 파일만 채우면 됩니다. 다른 파일은 열지 않아도 됩니다.
각 함수는 문자열 하나를 반환합니다. TODO 부분을 도메인 지식으로 채워주세요.
mock 모드에서는 이 텍스트가 실제로 쓰이지 않으므로, 비어 있어도 파이프라인은 돕니다.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
from __future__ import annotations

import json
from typing import Any

_JSON = "반드시 JSON만 출력하세요. 설명, 머리말, 코드펜스를 붙이지 마세요."


def macro(as_of: str, tool_desc: str) -> str:
    """담당: TODO

    경기 국면을 판정하게 하는 프롬프트.
    - 어떤 지표를 먼저 보게 할 것인가
    - 지표가 서로 엇갈릴 때 무엇을 우선할 것인가
    - 4개 국면의 경계를 어떻게 정의할 것인가
    """
    return f"""당신은 기관투자자의 거시경제 분석 담당입니다.
기준일: {as_of}
사용 가능한 도구:
{tool_desc}

{as_of} 시점에 가용한 정보만으로 경기 국면을 판정하세요.
이후 시점의 정보를 사용해서는 안 됩니다.

# TODO — 판정 기준을 여기에 기술
# 예) 장단기 금리차와 PMI를 우선 확인하고, 신용스프레드로 교차 검증한다.
#     실물과 금융 지표가 엇갈리면 후기 순환으로 분류한다.

출력 형식:
{{"label": "확장|후기 순환|침체|회복",
  "probs": {{"확장": 0.0, "후기 순환": 0.0, "침체": 0.0, "회복": 0.0}},
  "confidence": 0.0,
  "rationale": "판단 근거"}}
{_JSON}"""


def asset_view(asset: str, as_of: str, regime: dict, tool_desc: str) -> str:
    """담당: TODO

    자산군별 기대수익률·변동성·확신도를 추정하게 하는 프롬프트.
    여기가 파이프라인 전체 토큰의 절반 이상을 씁니다. 가장 중요합니다.

    - 세 방법론(Grinold-Kroner / CAPE / 과거평균)을 어떤 순서로 적용할 것인가
    - 방법론이 갈릴 때 무엇을 우선할 것인가
    - 확신도를 무엇에 근거해 매길 것인가  ← 이게 BL 이탈 폭을 결정합니다
    """
    return f"""당신은 {asset} 자산군 담당 애널리스트입니다.
기준일: {as_of}
현재 국면: {regime.get('label')} (확신도 {regime.get('confidence')})
사용 가능한 도구:
{tool_desc}

{as_of} 시점에 가용한 정보만으로 향후 5년 기대수익률을 추정하세요.

# TODO — 추정 절차를 여기에 기술
# 예) 1) Grinold-Kroner로 배당+자사주+실질성장+물가+밸류에이션 변화를 분해
#     2) CAPE 기반 추정으로 교차 검증
#     3) 과거평균은 참고만 — 밸류에이션 확대분이 섞여 있어 상방 편향
#     4) 확신도는 세 방법론 간 편차에 반비례하게 매긴다

출력 형식:
{{"asset": "{asset}", "mu": 0.0, "sigma": 0.0, "confidence": 0.0,
  "method_values": {{"grinold_kroner": 0.0, "cape": 0.0, "historical": 0.0}},
  "rationale": "추정 근거"}}
{_JSON}"""


def challenge(cma: dict, corr_hint: str, round_no: int) -> str:
    """담당: TODO

    다른 에이전트의 추정에서 모순을 찾아 반박하게 하는 프롬프트.
    여기가 약하면 토론이 형식적으로 흐릅니다.

    - 어떤 종류의 모순을 찾을 것인가 (상관 대비 스프레드, 국면 정합성, 확신도 과잉)
    - 반박을 몇 개까지 낼 것인가
    """
    return f"""당신은 자산배분 검토 담당입니다. 현재 {round_no}라운드입니다.

제출된 추정:
{json.dumps(cma, ensure_ascii=False, indent=1)}

참고: {corr_hint}

# TODO — 반박 기준을 여기에 기술
# 예) - 상관이 0.8을 넘는 두 자산의 기대수익률 차이에 구조적 근거가 있는가
#     - 국면 판정과 방향이 어긋나는 추정이 있는가
#     - 방법론 간 편차 대비 확신도가 과도한 자산이 있는가
# 근거가 충분하면 반박하지 마세요. 억지 반박은 토론을 형식적으로 만듭니다.

출력 형식 (반박이 없으면 빈 배열):
[{{"round": {round_no}, "target": "자산군명", "status": "open", "text": "반박 내용"}}]
{_JSON}"""


def revise(asset: str, current: dict, challenges: list, tool_desc: str) -> str:
    """담당: TODO

    반박을 받은 에이전트가 수정 여부를 결정하게 하는 프롬프트.
    수용과 방어 둘 다 정당한 선택임을 명시해야 합니다.
    """
    return f"""당신은 {asset} 담당 애널리스트입니다. 반박을 받았습니다.

현재 추정: {json.dumps(current, ensure_ascii=False)}
반박: {json.dumps(challenges, ensure_ascii=False, indent=1)}

# TODO — 수정 판단 기준을 여기에 기술
# 반박이 타당하면 추정이나 확신도를 조정하고, 타당하지 않으면 근거를 들어 방어하세요.
# 방어도 정당한 선택입니다. 다만 1라운드와 같은 근거를 반복하는 것은 답변이 아닙니다.

사용 가능한 도구:
{tool_desc}

출력 형식:
{{"mu": 0.0, "confidence": 0.0, "accepted": true, "rationale": "수정 또는 방어 근거"}}
{_JSON}"""


def critique(method: str, weights: dict, peers: dict) -> str:
    """담당: TODO — 방법론 간 상호 비판."""
    return f"""당신은 {method} 방법론 담당입니다. 다른 방법론의 결과를 검토하세요.

내 결과: {json.dumps(weights, ensure_ascii=False)}
다른 후보: {json.dumps(peers, ensure_ascii=False)}

# TODO — 비판 관점을 기술 (제약 접촉, 위험 집중, 가정 위반 등)

출력 형식: {{"text": "지적 내용"}}
{_JSON}"""


def ranking(candidates: list, context: dict) -> str:
    """담당: TODO — 전 후보에 순위 부여 (보르다 집계용)."""
    return f"""후보 포트폴리오 전체에 1위부터 순위를 매기세요.

후보: {candidates}
맥락: {json.dumps(context, ensure_ascii=False)}

# TODO — 평가 기준을 기술
# 1위만 고르는 것이 아니라 전 후보를 줄 세워야 합니다.
# 호불호가 갈리는 후보와 두루 무난한 후보를 구분하는 것이 목적입니다.

출력 형식: ["1위 방법론", "2위 방법론", ...]
{_JSON}"""


def risk_note(method: str, metrics: dict) -> str:
    """담당: TODO — 위험 지표를 읽고 판정 사유를 서술."""
    return f"""{method} 후보의 위험 심사 결과를 서술하세요.

지표: {json.dumps(metrics, ensure_ascii=False, indent=1)}

# TODO — 어떤 지표를 결정적으로 볼 것인지 기술

출력 형식: {{"note": "판정 사유"}}
{_JSON}"""


def board_memo(final: dict, context: dict) -> str:
    """담당: TODO — 이사회 보고서 초안.

    IPS 제9조(문서화·보고) 요건을 충족해야 합니다.
    결합 방식이므로 자산군별 기여 분해를 반드시 언급하세요.
    """
    return f"""기금운용본부 명의의 이사회 보고서 초안을 작성하세요.

최종 배분: {json.dumps(final, ensure_ascii=False)}
맥락: {json.dumps(context, ensure_ascii=False, indent=1)}

# TODO — 보고서 구성과 어조를 기술
# 필수 포함: 결론 / 결합 방식 채택 사유 / 시장균형 대비 이탈 / 이사회 판단 사항

출력 형식: {{"text": "보고서 전문"}}
{_JSON}"""
