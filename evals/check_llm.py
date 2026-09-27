"""One raw LLM call, no retries, so the real error is visible.

    python -m evals.check_llm
"""
from openai import OpenAI

from app.core.config import get_settings

s = get_settings()
key = s.LLM_API_KEY or ""
print("base_url :", s.LLM_BASE_URL)
print("model    :", s.LLM_MODEL)
print("api key  :", (key[:6] + "..." + key[-4:]) if len(key) > 10 else f"MISSING or short ({len(key)} chars)")

client = OpenAI(api_key=key or "none", base_url=s.LLM_BASE_URL)

print("\n0) models this key can use ...")
try:
    ids = sorted(m.id for m in client.models.list().data)
    for i in ids:
        print("   -", i)
except Exception as e:
    print("   FAILED ->", type(e).__name__, str(e)[:300])

print("\n1) plain call ...")
try:
    r = client.chat.completions.create(
        model=s.LLM_MODEL,
        messages=[{"role": "user", "content": "Say OK"}],
        max_tokens=10,
    )
    print("   OK ->", r.choices[0].message.content)
except Exception as e:
    print("   FAILED ->", type(e).__name__, str(e)[:500])

print("\n2) JSON-mode call (what the re-ranker uses) ...")
try:
    r = client.chat.completions.create(
        model=s.LLM_MODEL,
        messages=[{"role": "user", "content": 'Return JSON: {"ok": true}'}],
        response_format={"type": "json_object"},
        temperature=0,
        max_tokens=50,
    )
    print("   OK ->", r.choices[0].message.content)
except Exception as e:
    print("   FAILED ->", type(e).__name__, str(e)[:500])
