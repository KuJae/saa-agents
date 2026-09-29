# 자율주행 포트폴리오 — 감독형 자산배분 파이프라인

> **가상 데이터로 만든 학술 프로젝트입니다.**
> KAIST 디지털금융MBA 현장적용프로젝트 산출물이며, 실제 운용 자료가 아닙니다.
> 모든 포트폴리오 수치는 교육용 가정과 Python 계산 결과이며, 실제 기관의 정책·수익률을 재현하지 않습니다.

Ang, Azimbayev, Kim (2026) *The Self-Driving Portfolio*(arXiv:2604.02279)의 에이전트
파이프라인을 과정 교재로 축소 구현한 **교수님 XS MVP를 출발 코드로** 합니다.
투자정책서(IPS)가 전 과정을 제약하고, 계산은 코드가, 근거는 에이전트가, 결정은 사람이 맡습니다.

## 출처와 라이선스

- 출발 코드: [keerhee/pension-fund-strategy-and-performance](https://github.com/keerhee/pension-fund-strategy-and-performance/tree/main/XS_%EC%9E%90%EC%9C%A8%EC%A3%BC%ED%96%89%ED%8F%AC%ED%8A%B8%ED%8F%B4%EB%A6%AC%EC%98%A4)
  `XS_자율주행포트폴리오/self-driving-mvp/`, 커밋 `07c092a`
- 라이선스: [CC BY-NC-SA 4.0](LICENSE) — 원 저장소와 같은 조건(출처 표기 · 비상업 · 동일조건)
- `.claude/skills/harness/`: [revfactory/harness](https://github.com/revfactory/harness) (황민호, Apache-2.0)
- 교수님 원본은 커밋 `2c0c836`에 수정 없이 들어 있습니다. 이 레포에서 바꾼 부분은
  `git diff 2c0c836 -- .claude _reference ips.md`로 볼 수 있습니다.

## 파이프라인

| 단계 | 에이전트 | 하는 일 | 산출 |
|---|---|---|---|
| 0 | `ips-guardian` | IPS 해석과 위반 판정 (다른 단계가 호출) | — |
| 1 | `cma-builder` | 학습구간만으로 기대수익률·공분산 (W03) | `cma.json` |
| 2 | `alloc-mvo` · `alloc-bl` · `alloc-riskparity` | 세 방법이 독립적으로 후보 산출 (W04·W05) | `alloc_*.json` |
| 3 | `ic-critic` | 위반안 자동 기각 → 4관점 채점 → 1안 권고 | `ic_vote.json` |
| 4 | `meta-reviewer` | 평가구간을 처음 열어 예측 대 실현 대조, 수정 제안(자동 반영 금지) | `meta_review.json` |
| 5 | (오케스트레이터) | 데이터·정책·코드·지시문·산출물 해시 기록 | `manifest.json` |

자산 11개(ETF) · 학습 84개월 / 평가 35개월 · 가상 기금 KFP의 `ips.md`.

## 돌리는 법 — 프롬프트

**터미널 명령을 치지 않습니다.** Claude Code에서 이 폴더를 열고 순서대로 말하면 됩니다.
에이전트·스킬·`ips.md`가 레포에 들어 있으므로 교수님 README의 P1(환경)·P2(하네스 구성)·P3(IPS 작성)은
이미 되어 있습니다.

| # | 프롬프트 | 무엇이 생기는가 |
|---|---|---|
| P4 | 만든 에이전트들을 표로 보여줘 | 구조 이해 |
| P5 | cma-builder 를 실행해줘 | `cma.json` |
| P6 | alloc-mvo, alloc-bl, alloc-riskparity 를 모두 실행해줘 | `alloc_*.json` |
| P7 | ic-critic 으로 심사하고 표결해줘 | `ic_vote.json` |
| P8 | meta-reviewer 로 예측과 실현을 대조해줘 | `meta_review.json` |
| P9 | 사람이 판단해야 할 지점만 정리해줘 | 감독 대상 목록 |
| P10 | ips.md 의 유효 종목 수 하한을 3.5 로 낮추고 다시 돌려줘 | 정책의 효과 확인 |

한 번에 돌리려면 "한 사이클 돌려줘"라고 하면 됩니다(1→5단계).

## 검증

```bash
python3 verify.py
```

약 3초에 7개 항목을 확인하고, 하나라도 실패하면 종료코드 1로 끝납니다.

| # | 검사 | 확인하는 것 |
|---|---|---|
| 1 | 골든 재현 | 교수님 `runs/2026-08-22`와 같은 숫자가 나오는가 |
| 2 | 결정성 | 두 번 돌리면 JSON이 바이트까지 같은가 |
| 3 | 오류 주입 | 한도별 위반 후보 9개를 전부 기각하고, 복합 위반은 위반을 모두 기록하는가 |
| 4 | 룩어헤드 | 평가구간 수익률을 교란해도 CMA·후보·표결이 그대로인가 |
| 4b | 탐지기 자체 검증 | 누출을 일부러 심으면 4번이 잡는가 |
| 5 | IPS 본문·부록 | 에이전트가 읽는 부록 YAML이 본문 조항과 같은가 |
| 6 | RUN manifest | 기록된 해시가 실제 파일과 맞고, 같은 RUN 덮어쓰기를 거부하는가 |

`ips.md`를 바꾸면 1번이 실패하는 것이 정상입니다. 골든은 하한 4.0 기준 실행입니다.

## 폴더

```
.claude/agents/     에이전트 7개 — 역할·원칙·입출력·에러·협업
.claude/skills/     스킬 6개 — 각 에이전트가 어떻게 일하는지의 명세 + 하네스
ips.md              정책. 행동을 바꾸려면 코드가 아니라 이 문서를 고친다
_reference/         계산 구현. 스킬이 호출한다 — 숫자는 여기서만 나온다
data/               월간 총수익률 패널 (yfinance, 2015-08 ~ 2025-07)
runs/{날짜}/         한 사이클의 산출물 6개 + manifest
verify.py           검증 하네스
docs/index.html     이전 설계의 목업 (새 구조 기준으로 다시 만들 예정)
```

## 이전 구현

LangGraph 기반 이전 구현(22개 방법론 · 보르다 결합 · mock LLM · 백테스트)은
[`legacy-langgraph`](https://github.com/KuJae/saa-agents/tree/legacy-langgraph) 브랜치에 그대로 있습니다.
[설계 목업](https://kujae.github.io/saa-agents/)도 그 설계를 보여줍니다.
