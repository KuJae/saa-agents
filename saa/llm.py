"""LLM 어댑터.

mock 모드에서는 API 호출 없이 스키마에 맞는 결정론적 응답을 만든다.
그래프 배선·상태 흐름·캐싱·체크포인트를 비용 0으로 검증할 수 있다.

real 모드로 바꾸려면 _call_real()만 채우면 된다. 나머지는 그대로 동작한다.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any

from .state import CallRecord
from .tools import CACHE, _key, _seeded

# 노드별 모델 티어 — 호출 수가 많은 쪽을 싸게 쓴다
TIER = {
    "macro_agent": "high", "asset_agents": "high", "challenger": "high",
    "cio_agent": "high", "memo_writer": "high",
    "critic_agents": "low", "ranker_agents": "low", "risk_agent": "low",
}
MODELS = {"high": "claude-opus-5", "low": "claude-haiku-4-5"}

DETERMINISTIC = {"temperature": 0.0, "seed": 42, "use_cache": True}
VARIANCE = {"temperature": 0.7, "seed": None, "use_cache": False}


@dataclass
class LLMClient:
    mode: str = "mock"                       # "mock" | "real"
    cache_ns: str = "default"
    params: dict = field(default_factory=lambda: dict(DETERMINISTIC))
    calls: list[CallRecord] = field(default_factory=list)
    _nonce: int = field(default_factory=lambda: __import__("random").randrange(1 << 30))

    # ─────────────────────────────────────────────────────
    def complete(self, node: str, prompt: str, *, schema: dict,
                 mock_hint: dict | None = None) -> Any:
        """스키마에 맞는 구조화 응답을 반환."""
        tier = TIER.get(node, "low")
        model = MODELS[tier]
        t0 = time.time()

        ck = _key("llm", node, model, prompt, self.params.get("temperature"),
                  self.params.get("seed"), self.cache_ns)
        if self.params.get("use_cache"):
            hit = CACHE.get(ck)
            if hit is not None:
                self._log(node, model, 0, 0, time.time() - t0, True)
                return hit

        if self.mode == "mock":
            out = self._call_mock(node, prompt, schema, mock_hint or {})
        else:
            out = self._call_real(node, prompt, schema, model)

        if self.params.get("use_cache"):
            CACHE.put(ck, out)

        tin = len(prompt) // 3
        tout = len(json.dumps(out, ensure_ascii=False)) // 3
        self._log(node, model, tin, tout, time.time() - t0, False)
        return out

    def _log(self, node, model, tin, tout, sec, cached) -> None:
        self.calls.append({"node": node, "model": model, "tokens_in": tin,
                           "tokens_out": tout, "seconds": round(sec, 4),
                           "cached": cached})

    # ─────────────────────────────────────────────────────
    def _call_real(self, node: str, prompt: str, schema: dict, model: str) -> Any:
        """실제 API 호출. 여기만 채우면 real 모드로 전환된다.

        import anthropic
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        resp = client.messages.create(
            model=model, max_tokens=2000,
            temperature=self.params["temperature"],
            messages=[{"role": "user", "content": prompt}],
        )
        return json.loads(resp.content[0].text)
        """
        raise NotImplementedError(
            "real 모드는 _call_real()을 채운 뒤 사용하세요. "
            "ANTHROPIC_API_KEY 환경변수도 필요합니다."
        )

    # ─────────────────────────────────────────────────────
    def _call_mock(self, node: str, prompt: str, schema: dict, hint: dict) -> Any:
        """스키마에 맞는 결정론적 가짜 응답.

        값은 (node, prompt) 해시에 묶여 있어 같은 입력이면 항상 같은 출력이 나온다.
        """
        nonce = self._nonce if self.params.get("seed") is None else None
        rng = _seeded(node, prompt, self.params.get("seed"), nonce)
        kind = schema.get("kind")

        if kind == "regime":
            labels = ["확장", "후기 순환", "침체", "회복"]
            raw = [rng.random() for _ in labels]
            raw[1] += 1.6                       # 후기 순환에 무게
            s = sum(raw)
            probs = {l: round(v / s, 3) for l, v in zip(labels, raw)}
            top = max(probs, key=probs.get)
            return {"label": top, "probs": probs,
                    "confidence": round(0.45 + probs[top] * 0.4, 2),
                    "rationale": f"[mock] {top} 판정. 프롬프트 확정 후 실제 근거로 대체됩니다."}

        if kind == "asset_view":
            base_mu = hint.get("base_mu", 5.0)
            base_sd = hint.get("base_sd", 10.0)
            methods = {
                "grinold_kroner": round(base_mu + rng.gauss(0, 0.4), 2),
                "cape": round(base_mu + rng.gauss(-0.3, 0.6), 2),
                "historical": round(base_mu + rng.gauss(0.8, 1.0), 2),
            }
            spread = max(methods.values()) - min(methods.values())
            mu = round(methods["grinold_kroner"] * 0.55
                       + methods["cape"] * 0.27 + methods["historical"] * 0.18, 2)
            conf = round(max(0.25, min(0.85, 0.80 - spread * 0.12)), 2)
            return {"asset": hint.get("asset", "?"), "mu": mu, "sigma": base_sd,
                    "confidence": conf, "method_values": methods,
                    "rationale": f"[mock] 방법론 편차 {spread:.2f}%p 반영."}

        if kind == "challenges":
            rnd = hint.get("round", 1)
            pool = hint.get("candidates", [])
            n = max(0, min(len(pool), {1: 3, 2: 1, 3: 1}.get(rnd, 0)))
            picked = pool[:n]
            return [{"round": rnd, "target": a, "status": "open",
                     "text": f"[mock] {a} 추정의 근거가 불충분합니다. "
                             f"프롬프트 확정 후 실제 반박으로 대체됩니다."}
                    for a in picked]

        if kind == "revision":
            cur = hint.get("current", {})
            delta = rng.gauss(0, 0.22)
            accept = rng.random() < 0.62
            return {"mu": round(cur.get("mu", 5.0) + (delta if accept else 0.0), 2),
                    "confidence": round(max(0.20, cur.get("confidence", 0.5)
                                            + (0.04 if accept else -0.11)), 2),
                    "accepted": accept,
                    "rationale": "[mock] 반박 수용" if accept else "[mock] 기존 입장 유지"}

        if kind == "critique":
            return {"text": f"[mock] {hint.get('target','?')}에 대한 지적. "
                            f"프롬프트 확정 후 대체됩니다."}

        if kind == "ranking":
            cands = list(hint.get("candidates", []))
            rng.shuffle(cands)
            return cands

        if kind == "risk_note":
            return {"note": "[mock] 위험 심사 서술. 프롬프트 확정 후 대체됩니다."}

        if kind == "memo":
            return {"text": "[mock] 이사회 보고서 초안. 프롬프트 확정 후 대체됩니다."}

        raise ValueError(f"알 수 없는 스키마: {kind}")
