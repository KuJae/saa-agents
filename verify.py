"""검증 하네스 — 교수님 XS MVP 파이프라인이 ZeroOne 기안의 통과 기준을 지키는지 확인한다.

  python3 verify.py

항목마다 통과/실패를 출력하고, 하나라도 실패하면 종료코드 1로 끝난다.
모든 실행은 임시 폴더에서 한다 — runs/ 는 건드리지 않는다.

  1  골든 재현        runs/2026-08-22 와 같은 숫자가 나오는가     기안 90일 4–6주
  2  결정성          두 번 돌리면 바이트까지 같은가             기안 90일 4–6주
  3  오류 주입        한도 위반 후보를 전부 기각·기록하는가       기안 p.15 · 90일 1–3주
  4  룩어헤드        평가구간을 바꿔도 사전 산출물이 그대로인가
  4b 탐지기 자체 검증  누출을 일부러 심으면 4번이 잡는가
  5  IPS 본문·부록    에이전트가 읽는 부록이 본문과 같은가        ips-guardian 원칙 1
  6  RUN manifest    해시가 산출물과 맞고 덮어쓰기를 거부하는가   기안 p.24
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import sys
import tempfile
import warnings

sys.dont_write_bytecode = True
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "_reference", "scripts"))

import alloc_bl  # noqa: E402
import alloc_mvo  # noqa: E402
import alloc_rp  # noqa: E402
import cma  # noqa: E402
import common  # noqa: E402
import ic_critic  # noqa: E402
import manifest  # noqa: E402
import meta_review  # noqa: E402

GOLDEN = "2026-08-22"
RUN = "verify"
TOL = 1e-4
STAGES = [("cma.json", cma), ("alloc_mvo.json", alloc_mvo), ("alloc_bl.json", alloc_bl),
          ("alloc_rp.json", alloc_rp), ("ic_vote.json", ic_critic),
          ("meta_review.json", meta_review)]
PRE_EVAL = STAGES[:-1]          # 평가구간을 보면 안 되는 단계 — meta_review 전까지


# ─────────────────────────────────────────────────────────────
# 공통
# ─────────────────────────────────────────────────────────────
def run_cycle(runs_dir: str, stages=STAGES) -> dict[str, str]:
    """임시 runs 폴더에서 한 사이클을 돌리고 산출 JSON 원문을 돌려준다."""
    saved = common.RUNS
    common.RUNS = runs_dir
    try:
        # SLSQP가 탐색 중 경계 밖 값을 잘랐다는 경고. 최종해는 1번 골든 비교가 검증한다.
        with contextlib.redirect_stdout(io.StringIO()), warnings.catch_warnings():
            warnings.filterwarnings("ignore", "Values in x were outside bounds")
            for _, mod in stages:
                mod.main(RUN)
    finally:
        common.RUNS = saved
    d = os.path.join(runs_dir, RUN)
    return {name: open(os.path.join(d, name), encoding="utf-8").read() for name, _ in stages}


def json_diff(a, b, path: str, out: dict) -> None:
    """두 JSON을 재귀 비교. 실수는 TOL 안이면 같다고 본다. 'run' 키는 실행 ID라 제외."""
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k == "run":
                continue
            if k not in a or k not in b:
                out["msgs"].append(f"{path}.{k} 한쪽에만 있음")
            else:
                json_diff(a[k], b[k], f"{path}.{k}", out)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out["msgs"].append(f"{path} 길이 {len(a)} ≠ {len(b)}")
        for i, (x, y) in enumerate(zip(a, b)):
            json_diff(x, y, f"{path}[{i}]", out)
    elif (isinstance(a, (int, float)) and isinstance(b, (int, float))
          and not isinstance(a, bool) and not isinstance(b, bool)):
        d = abs(a - b)
        out["max"] = max(out["max"], d)
        if d > TOL:
            out["msgs"].append(f"{path}: {a} ≠ {b}")
    elif a != b:
        out["msgs"].append(f"{path}: {a!r} ≠ {b!r}")


# ─────────────────────────────────────────────────────────────
# 1 골든 재현
# ─────────────────────────────────────────────────────────────
def check_golden(base: dict[str, str]):
    out = {"msgs": [], "max": 0.0}
    for name, text in base.items():
        golden = common.load(name, GOLDEN)
        json_diff(json.loads(text), golden, name, out)
    mvo = json.loads(base["alloc_mvo.json"])
    vote = json.loads(base["ic_vote.json"])
    meta = json.loads(base["meta_review.json"])
    tot = {c["agent"]: c["total"] for c in vote["candidates"]}
    lines = [f"{len(base)}개 파일 · 최대 차이 {out['max']:.2e} (허용 {TOL:g})",
             f"MVO 유효N {mvo['expected']['effective_n']:.2f}"
             f"{' 기각' if mvo['ips_violations'] else ''} · BL {tot['alloc-bl']:.2f} · "
             f"RP {tot['alloc-riskparity']:.2f} → 채택 {vote['winner']} · MAE {meta['mae']*100:.2f}%p"]
    return not out["msgs"], lines + out["msgs"][:10]


# ─────────────────────────────────────────────────────────────
# 2 결정성
# ─────────────────────────────────────────────────────────────
def check_determinism(base: dict[str, str], again: dict[str, str]):
    bad = [n for n in base if base[n] != again[n]]
    return not bad, (["두 번 실행한 JSON 6개가 바이트까지 같다"] if not bad
                     else [f"다름: {', '.join(bad)}"])


# ─────────────────────────────────────────────────────────────
# 3 오류 주입
# ─────────────────────────────────────────────────────────────
# KFP 정상 기준안 — 주식 45 · 채권 40 · 대체 15, 최대 20%, 유효N 8.8
BASE_W = {"SPY": 20, "EFA": 15, "EEM": 10, "IEF": 10, "TLT": 10, "LQD": 8, "HYG": 6,
          "TIP": 6, "VNQ": 5, "GLD": 5, "DBC": 5}

# (이름, 기준안에서 바꿀 비중(%), 기대 위반 문구 전체)
INJECTIONS = [
    ("개별 상한 30% 초과", {"SPY": 35, "EFA": 5, "EEM": 5},
     ["개별 상한 초과: SPY 35.0% > 30%"]),
    ("주식 상한 60% 초과", {"SPY": 25, "EFA": 25, "EEM": 15, "IEF": 5, "TLT": 5, "LQD": 5,
                        "HYG": 5, "TIP": 5, "VNQ": 4, "GLD": 3, "DBC": 3},
     ["equity 상한 초과: 65.0% > 60%"]),
    ("채권 하한 25% 미달", {"SPY": 25, "EFA": 20, "EEM": 15, "IEF": 5, "TLT": 5, "LQD": 4,
                        "HYG": 3, "TIP": 3, "VNQ": 7, "GLD": 7, "DBC": 6},
     ["fixed_income 하한 미달: 20.0% < 25%"]),
    ("대체 상한 25% 초과", {"SPY": 15, "EFA": 10, "EEM": 10, "IEF": 10, "TLT": 10, "LQD": 5,
                        "HYG": 5, "TIP": 5, "VNQ": 10, "GLD": 10, "DBC": 10},
     ["alternative 상한 초과: 30.0% > 25%"]),
    ("대체 하한 5% 미달", {"SPY": 20, "EFA": 20, "EEM": 10, "IEF": 12, "TLT": 12, "LQD": 8,
                       "HYG": 8, "TIP": 8, "VNQ": 0, "GLD": 2, "DBC": 0},
     ["alternative 하한 미달: 2.0% < 5%"]),
    ("유효 종목 수 4.0 미만", {"SPY": 30, "EFA": 0, "EEM": 0, "IEF": 30, "TLT": 25, "LQD": 0,
                         "HYG": 0, "TIP": 0, "VNQ": 0, "GLD": 15, "DBC": 0},
     ["유효 종목 수 3.77 < 4.0"]),
    ("비중 합 ≠ 100%", {"SPY": 18},
     ["비중 합 0.9800 ≠ 1"]),
    ("공매도", {"SPY": 22, "EEM": -2, "IEF": 20},
     ["공매도 발생 (최소 -0.020)"]),
    ("복합 위반 — 전부 기록하는가", {"SPY": 40, "EFA": 25, "EEM": 5, "IEF": 10, "TLT": 10,
                              "LQD": 0, "HYG": 0, "TIP": 0, "VNQ": 0, "GLD": 10, "DBC": 0},
     ["개별 상한 초과: SPY 40.0% > 30%", "equity 상한 초과: 70.0% > 60%",
      "fixed_income 하한 미달: 20.0% < 25%", "유효 종목 수 3.92 < 4.0"]),
]


def check_injection():
    ips = common.load_ips()
    tick = list(common.load_panel().columns)
    vec = lambda pct: [pct[t] / 100 for t in tick]
    lines, ok = [], True

    rp = common.load("alloc_rp.json", GOLDEN)["weights"]
    controls = [("정상 대조군 (기준안)", vec(BASE_W)),
                ("정상 대조군 (교수님 RP 비중)", [rp[t] for t in tick])]
    for name, w in controls:
        v = common.check_ips(w, tick, ips)
        ok &= not v
        lines.append(f"{'○' if not v else '×'} {name}: 위반 {len(v)}건" + (f" {v}" if v else ""))

    for name, change, expected in INJECTIONS:
        v = common.check_ips(vec({**BASE_W, **change}), tick, ips)
        hit = sorted(v) == sorted(expected)
        ok &= hit
        lines.append(f"{'○' if hit else '×'} {name}: 기각 · 위반 {len(v)}건")
        if not hit:
            lines.append(f"    기대 {expected}")
            lines.append(f"    실제 {v}")
    return ok, lines


# ─────────────────────────────────────────────────────────────
# 4 룩어헤드 · 4b 탐지기 자체 검증
# ─────────────────────────────────────────────────────────────
def perturbed_panel(split: str):
    """split 이후 수익률만 교란한 패널. 사전 산출물이 이걸 봤다면 숫자가 바뀐다."""
    R = common.load_panel()
    after = R.index > split
    R.loc[after] = -3.0 * R.loc[after] + 0.05
    return R, int(after.sum())


def lookahead_probe(tmp: str, tag: str, stages, split: str) -> list[str]:
    """원본과 교란 패널로 같은 단계를 돌려 결과가 달라진 파일 목록을 돌려준다."""
    clean = run_cycle(os.path.join(tmp, tag + "_clean"), stages)
    R, _ = perturbed_panel(split)
    saved = common.load_panel
    common.load_panel = lambda: R.copy()
    try:
        dirty = run_cycle(os.path.join(tmp, tag + "_dirty"), stages)
    finally:
        common.load_panel = saved
    return [n for n in clean if clean[n] != dirty[n]]


def check_lookahead(tmp: str):
    _, n_after = perturbed_panel(cma.SPLIT)
    changed = lookahead_probe(tmp, "look", STAGES, cma.SPLIT)
    pre = [n for n in changed if n != "meta_review.json"]
    meta_moved = "meta_review.json" in changed
    lines = [f"기준일 {cma.SPLIT} 이후 {n_after}개월을 교란",
             f"사전 산출물 5개: {'변화 없음' if not pre else '변함 → ' + ', '.join(pre)}",
             f"meta_review: {'달라짐 (교란이 실제로 들어갔다)' if meta_moved else '그대로 — 교란이 안 들어감'}"]
    return not pre and meta_moved, lines


def check_detector(tmp: str):
    leak = "2024-07-31"
    saved = cma.SPLIT
    cma.SPLIT = leak           # CMA가 평가구간 2년을 더 보게 만든다 — 교란 기준일은 그대로
    try:
        caught = lookahead_probe(tmp, "det", PRE_EVAL, saved)
    finally:
        cma.SPLIT = saved
    lines = [f"CMA 학습구간을 {leak}까지 늘려 누출을 심음",
             f"탐지: {', '.join(caught) if caught else '못 잡음'}"]
    return bool(caught), lines


# ─────────────────────────────────────────────────────────────
# 5 IPS 본문 · 부록 일치
# ─────────────────────────────────────────────────────────────
BODY_GROUPS = {"주식": "equity", "채권": "fixed_income", "대체": "alternative"}
BODY_SCALARS = [   # (항목, 본문 정규식, load_ips 키, 본문 값 → 부록 단위)
    ("실질 목표수익률 (2항)", r"실질수익률 \*\*연 ([\d.]+)%", "real_return_target", 0.01),
    ("변동성 상한 (3항)", r"변동성 \*\*([\d.]+)% 이하", "vol_cap", 0.01),
    ("MDD 한도 (3항)", r"최대낙폭\(MDD\)은 \*\*(-?[\d.]+)%", "mdd_limit", 0.01),
    ("개별 종목 상한 (4항)", r"개별 종목\(ETF\) 비중은 \*\*([\d.]+)%", "asset_max", 0.01),
    ("유효 종목 수 하한 (5항)", r"유효 종목 수\(1/Σw²\)가 \*\*([\d.]+) 이상", "effective_n_min", 1.0),
]


def ips_mismatches(path: str) -> list[str]:
    """본문과 부록 A가 다른 항목을 돌려준다. 본문에서 값을 못 찾아도 문제로 센다."""
    text = open(path, encoding="utf-8").read()
    body = text.split("## 부록 A")[0]
    ips = common.load_ips(path)
    bad = []
    for label, pat, key, unit in BODY_SCALARS:
        m = re.search(pat, body)
        if not m:
            bad.append(f"{label}: 본문에서 값을 찾지 못함")
        elif abs(float(m.group(1)) * unit - ips[key]) > 1e-9:
            bad.append(f"{label}: 본문 {m.group(1)} ≠ 부록 {ips[key]}")
    rows = dict((g, (lo, hi)) for g, lo, hi in re.findall(
        r"^\|\s*(주식|채권|대체)\s*\|\s*([\d.]+)%\s*\|\s*([\d.]+)%\s*\|", body, re.M))
    for kor, eng in BODY_GROUPS.items():
        if kor not in rows:
            bad.append(f"{kor} 범위 (4항): 본문 표에서 찾지 못함")
            continue
        g = ips["groups"].get(eng)
        lo, hi = float(rows[kor][0]) / 100, float(rows[kor][1]) / 100
        if g is None:
            bad.append(f"{kor} 범위 (4항): 부록에 {eng} 그룹 없음")
        elif abs(lo - g["min"]) > 1e-9 or abs(hi - g["max"]) > 1e-9:
            bad.append(f"{kor} 범위 (4항): 본문 {lo:.0%}~{hi:.0%} ≠ 부록 {g['min']:.0%}~{g['max']:.0%}")
    return bad


def check_ips_consistency(tmp: str):
    path = os.path.join(ROOT, "ips.md")
    bad = ips_mismatches(path)
    lines = [f"본문 항목 {len(BODY_SCALARS) + len(BODY_GROUPS)}개 대조: "
             + ("전부 일치" if not bad else f"불일치 {len(bad)}건")] + bad

    # 자체 검증 — 부록만 3.5로 바꾼 사본은 불일치로 잡혀야 한다 (교수님 P10 상황)
    txt = open(path, encoding="utf-8").read()
    mutated = os.path.join(tmp, "ips_mutated.md")
    with open(mutated, "w", encoding="utf-8") as f:
        f.write(txt.replace("effective_n_min: 4.0", "effective_n_min: 3.5"))
    caught = ips_mismatches(mutated)
    lines.append(f"자체 검증 — 부록만 3.5로 바꾼 사본: {'잡음' if caught else '못 잡음'}")
    return not bad and bool(caught), lines


# ─────────────────────────────────────────────────────────────
# 6 RUN manifest
# ─────────────────────────────────────────────────────────────
def check_manifest(runs_dir: str):
    saved = common.RUNS
    common.RUNS = runs_dir
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            manifest.main(RUN, model="verify")
        m = common.load("manifest.json", RUN)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                manifest.main(RUN, model="verify")
            refused = False
        except SystemExit:
            refused = True
    finally:
        common.RUNS = saved

    files = {**m["code"], **m["prompts"], m["data"]["path"]: m["data"]["sha256"],
             m["ips"]["path"]: m["ips"]["sha256"]}
    bad = [p for p, h in files.items() if manifest.sha256(os.path.join(ROOT, p)) != h]
    bad += [f for f, h in m["outputs"].items()
            if manifest.sha256(os.path.join(runs_dir, RUN, f)) != h]
    lines = [f"해시 {len(files) + len(m['outputs'])}개 재계산: "
             + ("전부 일치" if not bad else f"불일치 {', '.join(bad)}"),
             f"산출물 {len(m['outputs'])}/{len(manifest.OUTPUTS)}개 기록 · 기준일 {m['as_of']}",
             f"같은 RUN 재기록: {'거부함' if refused else '덮어씀 — 원칙 위반'}"]
    ok = not bad and refused and len(m["outputs"]) == len(manifest.OUTPUTS)
    return ok, lines


# ─────────────────────────────────────────────────────────────
def main() -> int:
    print(f"검증 하네스 · 교수님 XS MVP · 골든 runs/{GOLDEN}\n")
    results = []

    def report(no, title, res):
        ok, lines = res
        results.append(ok)
        print(f"[{no:>2}] {title} — {'통과' if ok else '실패'}")
        for line in lines:
            print(f"     {line}")

    with tempfile.TemporaryDirectory() as tmp:
        base = run_cycle(os.path.join(tmp, "a"))
        again = run_cycle(os.path.join(tmp, "b"))
        report(1, "골든 재현", check_golden(base))
        report(2, "결정성", check_determinism(base, again))
        report(3, "오류 주입", check_injection())
        report(4, "룩어헤드", check_lookahead(tmp))
        report("4b", "탐지기 자체 검증", check_detector(tmp))
        report(5, "IPS 본문·부록", check_ips_consistency(tmp))
        report(6, "RUN manifest", check_manifest(os.path.join(tmp, "a")))

    n = sum(results)
    print(f"\n{n}/{len(results)} 통과")
    return 0 if n == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
