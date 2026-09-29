# -*- coding: utf-8 -*-
"""⑦ manifest — 한 사이클의 감사 기록을 남긴다 (IPS 7.2항 · ZeroOne 기안 p.24).
   어떤 데이터·정책·코드·지시문으로 이 숫자가 나왔는지 해시로 고정한다.
   이미 기록된 RUN은 덮어쓰지 않는다 — 바꿔 돌리려면 새 RUN ID를 쓴다."""
import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import argparse, glob, hashlib, platform, subprocess
from datetime import datetime, timezone
import numpy, pandas, scipy, common

OUTPUTS = ["cma.json", "alloc_mvo.json", "alloc_bl.json", "alloc_rp.json",
           "ic_vote.json", "meta_review.json"]

def sha256(path):
    with open(path, "rb") as f: return hashlib.sha256(f.read()).hexdigest()

def rel(path):
    return os.path.relpath(path, common.ROOT).replace(os.sep, "/")

def hashes(pattern):
    return {rel(p): sha256(p) for p in sorted(glob.glob(os.path.join(common.ROOT, pattern)))}

def git_state():
    """커밋과 미커밋 변경 여부. runs/는 산출물이라 판정에서 뺀다. git이 없으면 None."""
    try:
        git = lambda *a: subprocess.run(("git",) + a, cwd=common.ROOT, capture_output=True,
                                        text=True, check=True).stdout.strip()
        return {"commit": git("rev-parse", "HEAD"),
                "dirty": bool(git("status", "--porcelain", "--", ".", ":(exclude)runs"))}
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "dirty": None}

def build(run, model=None):
    d = os.path.join(common.RUNS, run)
    missing = [f for f in OUTPUTS if not os.path.exists(os.path.join(d, f))]
    if missing: raise SystemExit("산출물이 빠져 있다: " + ", ".join(missing))
    data = os.path.join(common.ROOT, "data", "panel_monthly.csv")
    ips = os.path.join(common.ROOT, "ips.md")
    R = common.load_panel()
    return {"run": run,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "model": model, "git": git_state(),
            "data": {"path": rel(data), "sha256": sha256(data), "rows": len(R),
                     "first": str(R.index[0].date()), "last": str(R.index[-1].date())},
            "as_of": common.load("cma.json", run)["as_of"],
            "ips": {"path": rel(ips), "sha256": sha256(ips), "constraints": common.load_ips(ips)},
            "code": hashes("_reference/scripts/*.py"),
            "prompts": {**hashes(".claude/agents/*.md"), **hashes(".claude/skills/*/SKILL.md")},
            "env": {"python": platform.python_version(), "numpy": numpy.__version__,
                    "scipy": scipy.__version__, "pandas": pandas.__version__},
            "outputs": {f: sha256(os.path.join(d, f)) for f in OUTPUTS}}

def main(run, model=None):
    p = os.path.join(common.RUNS, run, "manifest.json")
    if os.path.exists(p):
        raise SystemExit("이미 기록된 RUN이다: %s — 덮어쓰지 않는다. 새 RUN ID로 다시 돌린다." % rel(p))
    m = build(run, model)
    p = common.save("manifest.json", m, run)
    print("  데이터 %s ~ %s (%d개월) · 기준일 %s"
          % (m["data"]["first"], m["data"]["last"], m["data"]["rows"], m["as_of"]))
    print("  코드 %d개 · 지시문 %d개 · 산출물 %d개 해시 고정"
          % (len(m["code"]), len(m["prompts"]), len(m["outputs"])))
    print("  git %s%s · 모델 %s" % ((m["git"]["commit"] or "없음")[:7],
                                  " (미커밋 변경 있음)" if m["git"]["dirty"] else "", model or "기록 안 됨"))
    print("  → %s" % rel(p))

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("run"); ap.add_argument("--model", default=None)
    a = ap.parse_args(); main(a.run, a.model)
