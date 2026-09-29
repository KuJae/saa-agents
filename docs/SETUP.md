# 전략적 자산배분 멀티에이전트 파이프라인

LangGraph 기반. **LLM 없이 전 노드가 끝까지 돕니다.**
그래프 배선·상태 흐름·캐싱·체크포인트를 비용 0으로 먼저 검증한 뒤,
프롬프트만 갈아끼우면 실제 실행으로 전환됩니다.

## 빠른 시작

```bash
pip install langgraph numpy scipy
python run.py once                    # 1개 시점 실행
python run.py backtest --all          # 전 구간 43개 시점 백테스트
python run.py backtest --all --export bt.json   # 결과를 JSON으로
python run.py variance --n 20         # 같은 입력 반복 → 판단 편차
python run.py masked                  # 원본 vs 마스킹 도구 호출 대조
```

## 팀원이 할 일

**`saa/prompts.py` 하나만 열면 됩니다.** 다른 파일은 볼 필요 없습니다.

각 함수의 `# TODO` 부분을 도메인 지식으로 채우세요. mock 모드에서는 이 텍스트가
실제로 쓰이지 않으므로, 비어 있어도 파이프라인은 계속 돕니다.

| 함수 | 채워야 할 것 | 담당 |
|---|---|---|
| `macro()` | 국면 판정 기준, 지표 우선순위 | |
| `asset_view()` | 세 방법론 적용 순서, **확신도 산정 근거** | |
| `challenge()` | 어떤 종류의 모순을 반박할 것인가 | |
| `revise()` | 수용과 방어의 판단 기준 | |
| `critique()` | 방법론 간 비판 관점 | |
| `ranking()` | 순위 부여 기준 | |
| `risk_note()` | 결정적으로 볼 위험 지표 | |
| `board_memo()` | 보고서 구성과 어조 | |

`asset_view()`가 가장 중요합니다. 파이프라인 토큰의 절반 이상을 쓰고,
여기서 나오는 **확신도가 Black-Litterman의 이탈 폭을 직접 결정**합니다.

## 구조

```
macro_agent ─→ asset_agents ←──────────┐
                    ↓                  │ 미해결 반박 & round < 3
               challenger ─→ converged?┘
                    ↓ 수렴 또는 상한 도달
               (halt_debate)
                    ↓
     cov_estimator → optimizers → ips_gate
                                      ↓ 통과 0건
     review_agents ←─────────────  escalate
          ↓
     risk_agent → combine → memo_writer
```

| 파일 | 역할 | 유형 |
|---|---|---|
| `state.py` | 상태 스키마 — **변경 전 팀 합의 필요** | 계약 |
| `market.py` | 실현 수익률 패널 · as_of 경계 강제 | 함수 |
| `backtest.py` | NAV 경로, 컷오프 전후 구간 분리 | 함수 |
| `tools.py` | 도구 계층, 캐시, 마스킹 | 함수 |
| `llm.py` | mock/real 어댑터, 비용 로깅 | 어댑터 |
| `prompts.py` | **팀원이 채우는 파일** | 텍스트 |
| `nodes.py` | 노드 구현 | 혼합 |
| `graph.py` | 배선, 조건부 엣지 | 함수 |

LLM 노드 7종, 결정론적 함수 6종, 하이브리드 1종입니다.
`optimizers`, `cov_estimator`, `ips_gate`, `combine`은 LLM을 **전혀 호출하지 않습니다.**
이 경계를 명시적으로 긋는 것이 이 프로젝트의 설계 기여입니다.

## 설계 원칙

**모든 도구가 `as_of`를 강제로 받습니다.** 미래 데이터를 프롬프트가 아니라
도구 계층에서 물리적으로 차단합니다. 룩어헤드 1차 방어선입니다.

**캐시 키에 `as_of`와 `cache_ns`가 반드시 들어갑니다.** 빠뜨리면 시점 간
데이터가 섞여 룩어헤드를 스스로 만들어냅니다. 마스킹 테스트는 별도
네임스페이스로 분리해야 원본 응답이 재사용되지 않습니다.

**미해결 반박을 버리지 않습니다.** 3라운드 상한에 걸려도 반박을 폐기하지 않고
해당 자산군의 확신도를 낮춥니다. 수렴하지 못했다는 사실 자체가 정보입니다.

**반박받은 자산군만 재추정합니다.** 전량 재실행이면 라운드마다 14회인데
지목된 것만 돌려 3~5회에 그칩니다. 토론을 넣으면서 비용이 선형으로
늘지 않게 하는 핵심 장치입니다.

## real 모드 전환

`saa/llm.py`의 `_call_real()` 하나만 채우면 됩니다. 주석에 예시가 있습니다.
`ANTHROPIC_API_KEY` 환경변수가 필요합니다.

```python
app, client = build(mode="real", cache_ns="default")
```

## 검증 하네스

`variance`와 `masked`는 자체 검증이 됩니다.

**편차 측정** — mock은 결정론적이라 원래 편차가 0입니다. VARIANCE 모드에서만
nonce가 주입되어 하네스가 편차를 잡아내는지 확인할 수 있습니다.

**마스킹 대조** — 기본 실행은 전 에이전트 0%가 나옵니다. mock에는 학습 기억이
없으므로 **이것이 정답입니다.** 탐지기가 작동하는지 확인하려면:

```bash
SIMULATE_LEAKAGE=1 python run.py masked --clear-cache
```

주식군만 조회량이 150% 늘어 `위반`으로 잡힙니다. 실제 LLM에서는 에이전트가
도구를 스스로 고르므로 이 플래그 없이도 차이가 나타납니다.

## VS Code에서 열기

```bash
git clone https://github.com/KuJae/saa-agents.git && cd saa-agents
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
code .
```

`.vscode/` 설정이 들어 있어 열면 바로 동작합니다.

- **F5** 를 누르면 실행 구성 6개가 뜹니다 (1개 시점 / 백테스트 / 편차 측정 / 마스킹 대조 등)
- 중단점을 찍고 노드 안에서 상태가 어떻게 채워지는지 직접 볼 수 있습니다
- 저장하면 ruff가 자동 정렬합니다
- 권장 확장 알림이 뜨면 설치하세요 (Python, Pylance, Ruff, Claude Code)

Claude Code는 VS Code 확장으로도 씁니다. 앱과 둘 중 하나를 고를 필요 없이,
확장을 깔면 VS Code 안에서 그대로 이어서 쓸 수 있습니다.

## 알려진 한계

- 도구 데이터는 합성입니다. WRDS·한국은행·KRX 연결로 교체해야 합니다.
- `optimizers`는 7개만 구현했습니다. 22개로 확장 필요.
- 사후 구간이 27개월로 짧습니다. 통계적 유의성은 주장하지 마세요.
- IPS 조항은 예시입니다. 실제 국민연금 투자정책서로 교체해야 합니다.
- `revise_agents`에서 에이전트가 같은 근거를 반복해도 현재는 감지하지 못합니다.
