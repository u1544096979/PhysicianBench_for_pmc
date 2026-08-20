import urllib3
urllib3.disable_warnings()
import json, urllib.request, ssl

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

key = "sk-180f716366e99b203bd670819a0d6a6502041afadebc4da4060e098bc1234d40"
req = urllib.request.Request(
    "https://43.138.203.19:12849/v1/chat/completions",
    data=json.dumps({
        "model": "qwen3.8",
        "messages": [{"role": "user", "content": "回复两个字：连通"}],
        "max_tokens": 2000,
    }).encode(),
    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
)
resp = urllib.request.urlopen(req, context=ctx, timeout=60)
data = json.loads(resp.read())
print("OK:", data["choices"][0]["message"]["content"][:200])
print("model:", data.get("model"))
