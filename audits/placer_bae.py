"""팀 레포 검증 — Placer-BAE/self-driving-portfolio 의 발견 사항을 누구나 재현할 수 있게 한다.

  git clone https://github.com/Placer-BAE/self-driving-portfolio.git
  pip install -r self-driving-portfolio/backend/requirements.txt pandas
  python3 audits/placer_bae.py self-driving-portfolio

팀 코드는 고치지 않는다. backend/ 를 import해서 파이프라인을 돌리고,
README·중간발표 대본·이사회 메모에 적힌 수치와 주장을 실행 결과와 대조한다.
항목마다 통과/실패를 출력하고, 하나라도 실패하면 종료코드 1로 끝난다.
2026-10-12 커밋 78ae658 기준으로 작성했다.
"""
from __future__ import annotations

import json
import os
import re
import sys
import warnings

import numpy as np

if len(sys.argv) != 2:
    sys.exit(__doc__)
REPO = os.path.abspath(sys.argv[1])
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(REPO, "backend"))
warnings.filterwarnings("ignore")

TOL = 0.05   # 문서 수치는 소수 둘째 자리까지 적혀 있으므로 반올림 오차만 허용

# 문서에 적힌 값 (출처: README.md 98행, 중간발표_대본.md 65·80·81행, cio_agent.py 메모 문구)
CLAIMED = {
    "README 기대수익률": ("expected_return_pct", 6.66),
    "README 변동성": ("volatility_pct", 9.65),
    "README 샤프": ("sharpe_ratio", 0.30),
    "대본 주식 비중": ("equity", 44.9),
    "대본 채권 비중": ("fixed_income", 41.7),
    "대본 실물자산 비중": ("real_assets", 5.1),
    "대본 현금 비중": ("cash", 8.1),
    "대본 추적오차": ("tracking_error_pct", 2.41),
    "대본 예상 MDD": ("max_drawdown_est_pct", -25.6),
}
DOC_FILES = ["backend/app/agents/llm_client.py", "run_project.bat", "frontend/src/api.ts"]
REQ_ALIASES = {"python-dotenv": "dotenv", "uvicorn[standard]": "uvicorn"}


def check_requirements():
    """backend/app 가 import하는 외부 패키지가 requirements.txt 에 모두 있는가."""
    req = set()
    for line in open(os.path.join(REPO, "backend", "requirements.txt"), encoding="utf-8"):
        name = re.split(r"[<>=~ ]", line.strip(), maxsplit=1)[0].lower()
        if name:
            req.add(REQ_ALIASES.get(name, name).split("[")[0])
    used = set()
    for root, _, files in os.walk(os.path.join(REPO, "backend", "app")):
        for f in files:
            if f.endswith(".py"):
                src = open(os.path.join(root, f), encoding="utf-8").read()
                used |= set(re.findall(r"^\s*(?:import|from)\s+(\w+)", src, re.M))
    external = {m for m in used if m not in sys.stdlib_module_names and m != "app"}
    missing = sorted(external - req)
    return not missing, [f"외부 import {sorted(external)}",
                         "requirements.txt 누락: " + (", ".join(missing) if missing else "없음")]


def final(res):
    fp = res["ensemble_step"]["final_portfolio"]
    return {**fp, **fp["category_exposures"]}


def weights(res):
    return np.array(list(res["ensemble_step"]["final_portfolio"]["weights"].values()))


def main() -> int:
    from app.config import DEFAULT_IPS, IPSConfig
    from app.pipeline import SelfDrivingPortfolioPipeline
    run = lambda ips=DEFAULT_IPS, macro=None: SelfDrivingPortfolioPipeline(ips).run(macro)

    print(f"팀 레포 검증 · {REPO}\n")
    results = []

    def report(no, title, res):
        ok, lines = res
        results.append(ok)
        print(f"[{no:>2}] {title} — {'통과' if ok else '실패'}")
        for line in filter(None, lines):
            print(f"     {line}")

    report(1, "설치 목록", check_requirements())

    base, again = run(), run()
    fp = final(base)
    same = json.dumps(base["ensemble_step"], sort_keys=True, default=str) == \
        json.dumps(again["ensemble_step"], sort_keys=True, default=str)
    report(2, "결정성", (same, ["두 번 실행 결과가 같다" if same else "두 번 실행 결과가 다르다"]))

    lines, ok = [], True
    for label, (key, claimed) in CLAIMED.items():
        hit = abs(float(fp[key]) - claimed) <= TOL
        ok &= hit
        lines.append(f"{'○' if hit else '×'} {label}: 문서 {claimed} · 실행 {float(fp[key]):.2f}")
    report(3, "문서 수치 재현", (ok, lines))

    # IPS를 바꾸면 최종안이 바뀌거나, 적격안이 없을 때 멈춰야 한다
    scenarios = [("README 시연: 최대 변동성 12 → 8.5", IPSConfig(volatility_max=8.5)),
                 ("극단 한도: 주식 0~5%, 변동성 0~1%",
                  IPSConfig(equity_min=0, equity_max=5, volatility_min=0, volatility_max=1))]
    lines, ok = [], True
    for label, ips in scenarios:
        r = run(ips)
        moved = float(np.abs(weights(r) - weights(base)).max() * 100)
        n_ok = sum(v["is_compliant"] for v in r["cro_reports"].values())
        ok &= moved > 1e-6
        lines.append(f"{'○' if moved > 1e-6 else '×'} {label}: 최종 비중 최대 변화 {moved:.6f}%p · 적격 후보 {n_ok}개")
    report(4, "IPS 민감도", (ok, lines))

    ips = DEFAULT_IPS
    checks = [
        (f"변동성 {fp['volatility_pct']:.2f}% ∈ [{ips.volatility_min}, {ips.volatility_max}]",
         ips.volatility_min <= fp["volatility_pct"] <= ips.volatility_max),
        (f"주식 {fp['equity']:.1f}% ∈ [{ips.equity_min}, {ips.equity_max}]",
         ips.equity_min <= fp["equity"] <= ips.equity_max),
        (f"현금 {fp['cash']:.1f}% ≥ {ips.cash_min}", fp["cash"] >= ips.cash_min),
        (f"추적오차 {fp['tracking_error_pct']:.2f}% ≤ {ips.tracking_error_limit}",
         fp["tracking_error_pct"] <= ips.tracking_error_limit),
        (f"예상 MDD {fp['max_drawdown_est_pct']:.2f}% ≥ {ips.max_drawdown_limit}",
         fp["max_drawdown_est_pct"] >= ips.max_drawdown_limit),
    ]
    report(5, "최종안 IPS 준수", (all(c for _, c in checks),
                              [f"{'○' if c else '×'} {t}" for t, c in checks]))

    cro, mw = base["cro_reports"], base["ensemble_step"]["method_weights"]
    bad_w = sum(w for k, w in mw.items() if not cro[k]["is_compliant"])
    n_ok = sum(v["is_compliant"] for v in cro.values())
    report(6, "위반 후보 배제", (bad_w == 0,
                            [f"후보 {len(cro)}개 중 IPS 적격 {n_ok}개",
                             f"앙상블 비중 중 위반 후보 몫 {bad_w*100:.1f}% (README: 위반 시 거부권)"]))

    memo = base["board_memo"]
    rank = {r["method_key"]: r["rank"] for r in base["review_step"]["rankings"]}
    w = base["ensemble_step"]["final_portfolio"]["weights"]
    treas = sum(w[k] for k in ("sh_treas", "int_treas", "lt_treas")) * 100
    compliant = all(c for _, c in checks)
    claims = [
        ("'IPS 100% 준수' 문구", "100% 준수" in memo, compliant, "최종안 실제 준수" if compliant else "최종안 실제로는 위반"),
        ("최대 엔트로피 '11위'", "11위" in memo, rank["max_entropy"] == 11, f"실제 {rank['max_entropy']}위"),
        ("최대 엔트로피 '5.6% 비중'", "5.6% 비중" in memo, abs(mw["max_entropy"]*100 - 5.6) <= TOL,
         f"실제 {mw['max_entropy']*100:.1f}%"),
        ("'금 2.1%'", "금 2.1%" in memo, abs(w["gold"]*100 - 2.1) <= TOL, f"실제 {w['gold']*100:.1f}%"),
        ("'원자재 1.6%'", "원자재 1.6%" in memo, abs(w["commodities"]*100 - 1.6) <= TOL,
         f"실제 {w['commodities']*100:.1f}%"),
        ("'국채 듀레이션 바벨 23.1%'", "23.1%" in memo, abs(treas - 23.1) <= TOL, f"실제 국채 합 {treas:.1f}%"),
    ]
    lines, ok = [], True
    for label, in_memo, true, actual in claims:
        good = (not in_memo) or true
        ok &= good
        lines.append(f"{'○' if good else '×'} 메모 {label}: {actual}")
    report(7, "이사회 메모 ↔ 계산값", (ok, lines))

    other = run(IPSConfig(equity_min=0, equity_max=5, volatility_min=0, volatility_max=1),
                {"gdp_growth_revision": 0.8, "payroll_trend": 0.8, "cpi_inflation": -0.5})
    va = {r["method_key"]: r["vote"] for r in base["review_step"]["rankings"]}
    vb = {r["method_key"]: r["vote"] for r in other["review_step"]["rankings"]}
    report(8, "투표가 입력에 반응", (va != vb,
                              [f"IPS·거시 입력을 모두 바꿔도 보르다 점수 {'동일 — 고정값' if va == vb else '변함'}",
                               f"국면 {base['macro_step']['regime']} → {other['macro_step']['regime']}"]))

    regime = base["macro_step"]["regime"]
    factor = base["covariance_step"]["regime_stress_factor"]
    late = "후기" in regime or "침체" in regime
    report(9, "국면 공분산 조정", (not late or factor > 1.0,
                             [f"국면 '{regime}' · 스트레스 계수 {factor}",
                              "covariance_agent.py 가 영어 'Late-Cycle'로 검사해 한국어 국면명에서 꺼짐" if late and factor == 1.0 else ""]))

    missing = [f for f in DOC_FILES if not os.path.exists(os.path.join(REPO, f))]
    src = ""
    for root, _, files in os.walk(os.path.join(REPO, "backend", "app")):
        src += "".join(open(os.path.join(root, f), encoding="utf-8").read() for f in files if f.endswith(".py"))
    llm = bool(re.search(r"\b(openai|gemini|anthropic|httpx)\b", src.replace("yfinance", ""), re.I))
    report(10, "문서에 적힌 구성 존재", (not missing and llm,
                                [f"README에 있지만 없는 파일: {', '.join(missing) if missing else '없음'}",
                                 f"LLM 호출 코드: {'있음' if llm else '없음 (README는 OpenAI/Gemini 모드를 설명)'}"]))

    n = sum(results)
    print(f"\n{n}/{len(results)} 통과")
    return 0 if n == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
