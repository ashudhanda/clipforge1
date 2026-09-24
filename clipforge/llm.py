"""Multi-provider LLM access for ClipForge.

Providers (chosen in config.yaml -> llm.provider):
    none          LLM disabled — rule-based logic only (default, free, fast)
    gemini        Google Gemini, free API key from Google AI Studio.
                  Key lives in secrets.yaml (llm.gemini_key) — never logged.
    openai_compat Any OpenAI-compatible chat API: OpenAI, Groq, OpenRouter,
                  or a local Ollama (http://localhost:11434/v1).
                  Needs llm.base_url + llm.model + optional llm.openai_key.

Only stdlib HTTP is used (urllib) — no extra SDK dependency.
complete() returns the model text or None on ANY failure (callers always
have a rule-based fallback). Long transcripts are sent in chunks via
chunk_transcript() so context limits never break a run.
"""

import json
import logging
import urllib.request

from . import config as C

log = logging.getLogger("clipforge")

_GEMINI_URL_TMPL = ("https://generativelanguage.googleapis.com/v1beta/models/"
                    "{model}:generateContent")
_TIMEOUT_S = 60


def provider():
    return (C.load_config().get("llm", {}).get("provider") or "none").lower()


def enabled():
    p = provider()
    if p == "gemini":
        return bool(_gemini_key() and _model_name())
    if p == "openai_compat":
        return bool(_base_url() and _model_name())
    return False


def _model_name():
    return (C.load_config().get("llm", {}).get("model") or "").strip()


def _base_url():
    return (C.load_config().get("llm", {}).get("base_url") or "").strip().rstrip("/")


def _gemini_key():
    return (C.load_secrets().get("llm", {}).get("gemini_key") or "").strip()


def _openai_key():
    return (C.load_secrets().get("llm", {}).get("openai_key") or "").strip()


def _post(url, payload, headers=None, timeout=_TIMEOUT_S):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _gemini_complete(prompt, max_tokens):
    model = _model_name() or "gemini-2.0-flash"
    url = _GEMINI_URL_TMPL.format(model=model) + "?key=" + _gemini_key()
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.7,
                                 "maxOutputTokens": max_tokens}}
    data = _post(url, body)
    parts = data["candidates"][0]["content"]["parts"]
    return "".join(p.get("text", "") for p in parts).strip()


def _openai_compat_complete(prompt, max_tokens):
    headers = {}
    if _openai_key():
        headers["Authorization"] = "Bearer " + _openai_key()
    body = {"model": _model_name(),
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7, "max_tokens": max_tokens}
    data = _post(_base_url() + "/chat/completions", body, headers)
    return data["choices"][0]["message"]["content"].strip()


def complete(prompt, max_tokens=300):
    """One completion. Returns text, or None when disabled/failing.

    Never raises, never logs keys. Callers must handle None with a
    rule-based fallback.
    """
    if not enabled():
        return None
    try:
        p = provider()
        if p == "gemini":
            text = _gemini_complete(prompt, max_tokens)
        elif p == "openai_compat":
            text = _openai_compat_complete(prompt, max_tokens)
        else:
            return None
        return text or None
    except Exception as e:
        log.warning("llm call failed (%s); using rule-based fallback",
                    type(e).__name__)
        return None


def chunk_transcript(segments, max_chars=6000):
    """Split [{start,end,text}] into text chunks that fit a prompt.

    Splits on segment boundaries so timestamps stay intact.
    """
    chunks, cur, cur_len = [], [], 0
    for s in segments:
        line = f"[{s['start']:.0f}s] {s['text']}\n"
        if cur and cur_len + len(line) > max_chars:
            chunks.append("".join(cur))
            cur, cur_len = [], 0
        cur.append(line)
        cur_len += len(line)
    if cur:
        chunks.append("".join(cur))
    return chunks


def rank_moments(candidates, max_tokens=400):
    """Ask the LLM to rank candidate moments by viral potential.

    candidates: [{start, end, text}] (text = transcript excerpt).
    Returns [indices in best-first order], or None on any failure.
    """
    if not enabled() or not candidates:
        return None
    listing = "\n\n".join(
        f"MOMENT {i} ({c['start']:.0f}s-{c['end']:.0f}s):\n{c['text'][:800]}"
        for i, c in enumerate(candidates))
    prompt = (
        "You rank short-video moments by viral potential (curiosity gap, "
        "strong opinion, story payoff, rewatchability). Best first.\n\n"
        f"{listing}\n\n"
        "Reply with ONLY the moment numbers in ranked order, comma-separated "
        "(e.g. 2,0,1). No other text.")
    text = complete(prompt, max_tokens=max_tokens)
    if not text:
        return None
    order = []
    for tok in text.replace("\n", ",").split(","):
        tok = tok.strip()
        if tok.isdigit() and int(tok) < len(candidates) and int(tok) not in order:
            order.append(int(tok))
    return order or None
