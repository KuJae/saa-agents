# CLAUDE.md

이 파일은 Claude Code가 자동으로 읽습니다. 이어받을 때 이걸 먼저 보세요.

## 이 프로젝트가 뭔가

KAIST 디지털금융MBA 현장적용프로젝트. **가상 데이터로 만든 학술 프로젝트이며
실제 운용 자료가 아닙니다.**

LLM 에이전트가 자본시장 가정을 산출하고, 22개 방법론으로 포트폴리오를 구성한 뒤
상호 검토와 위험 심사를 거쳐 **결합**하는 파이프라인. 투자정책서(IPS)가 전 과정을
통제합니다. 원 논문은 Ang, Azimbayev, Kim (2026) "The Self-Driving Portfolio".

사용자(재구)는 팀에서 **인프라와 검증**을 맡습니다. 상태 스키마, 캐싱,
룩어헤드 검증이 담당 영역입니다. 프롬프트 내용은 연기금 수강 팀원들이 채웁니다.

## GitHub

- 레포: <https://github.com/KuJae/saa-agents> (Public, 기본 브랜치 `main`)
- 목업: <https://kujae.github.io/saa-agents/> (Pages, `main` 브랜치 `/docs` 폴더)
- `gh` CLI가 KuJae 계정으로 로그인되어 있어 푸시 인증이 따로 필요 없습니다.
- git 저장소 루트는 이 폴더입니다. 상위 `~/Downloads`에서 git 명령을 치지 마세요.

## 다음 작업

```
확신도 보정 이력 구현      과거 CMA 추정 vs 실현 수익률 대조
실행 결과 JSON export      run.py --export
목업이 JSON을 읽게 전환    docs/index.html 하드코딩 제거
프롬프트 채우기            saa/prompts.py — 팀원 몫
실제 데이터 연결           WRDS·한국은행·KRX
```

## 확정된 설계 결정 — 뒤집지 마세요

**결합 방식.** 하나를 선택하지 않고 7개 방법론을 가중 결합합니다
(`보르다 점수 × 위험계수`). 제안서 원문과 같습니다. 설명책임 문제는
자산군별 기여 분해로 해결했습니다.

**순위 투표.** 1위표만 세지 않고 전 후보에 순위를 매겨 보르다로 집계합니다.
호불호가 갈리는 후보와 두루 인정받는 후보를 구분하기 위해서입니다.

**토론 3라운드 상한.** challenger가 반박하면 **지목된 자산군만** 재추정합니다.
상한에 걸려도 미해결 반박을 버리지 않고 해당 자산군의 확신도를 낮춥니다.
수렴하지 못했다는 사실 자체가 정보이기 때문입니다.

**하이브리드 경계.** LLM 에이전트 7종, 결정론적 함수 6종, 하이브리드 1종.
`optimizers`와 `cov_estimator`는 LLM을 전혀 호출하지 않습니다. 원 논문이 전부
"에이전트"라고 부른 것을 구분해 명시한 것이 이 프로젝트의 설계 기여입니다.
**함수 노드를 LLM으로 바꾸지 마세요.**

**룩어헤드 차단은 데이터 계층에서.** `market.py`가 실현 수익률을 갖고,
도구는 `slice_until(as_of)`로 이전 구간만 줍니다. `slice_between`은
백테스트 전용 채점표라 도구 계층에서 호출하면 안 됩니다.

## 구조

```
saa/state.py      상태 스키마 — 변경 전 팀 합의 필요
saa/tools.py      도구 계층, 캐시, 마스킹
saa/llm.py        mock/real 어댑터
saa/prompts.py    팀원이 채우는 파일
saa/nodes.py      노드 구현
saa/graph.py      배선, 조건부 엣지
saa/market.py     실현 수익률 패널
saa/backtest.py   NAV, 컷오프 전후 분리
docs/index.html   설계 목업 11개 화면
```

## 실행

```bash
python run.py once            # 1개 시점
python run.py backtest --all  # 43개 시점, 약 4초
python run.py variance --n 20 # 판단 편차
python run.py masked          # 룩어헤드 대조
```

mock 모드라 API 키 없이 돌고 비용이 0입니다. real 전환은 `saa/llm.py`의
`_call_real()`만 채우면 됩니다.

## 검증 하네스는 자체 검증됩니다

mock에는 학습 기억이 없으므로 **기본 실행에서 누출 0으로 나오는 것이 정답입니다.**
탐지기가 작동하는지 확인하려면:

```bash
SIMULATE_LEAKAGE=1 python run.py masked --clear-cache   # 주식군만 +150% 위반
SIMULATE_LEAKAGE=1 python run.py backtest --all         # 컷오프 이전만 +3.70%p
```

이 플래그는 **하네스 검증 전용**입니다. 이걸로 나온 숫자를 성과로 보고하면 안 됩니다.

## 대화 규칙

- 한국어로 답하세요.
- 사용자는 파이썬은 읽을 수 있지만 터미널·git은 익숙하지 않습니다.
  명령어는 복사해 붙일 수 있게 그대로 주고, 한 번에 한 단계씩 진행하세요.
- 숫자를 지어내지 마세요. 실행해서 나온 값만 쓰세요.
- 코드를 고치면 `python run.py once`로 최소 한 번은 돌려보고 보고하세요.
