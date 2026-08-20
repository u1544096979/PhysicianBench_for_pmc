from openai import OpenAI
import httpx
client = OpenAI(
    base_url="https://43.138.203.19:12849/v1",
    api_key="sk-180f716366e99b203bd670819a0d6a6502041afadebc4da4060e098bc1234d40",
    http_client=httpx.Client(verify=False, timeout=300),
)
resp = client.chat.completions.create(
    model="qwen3.8",
    messages=[{"role": "user", "content": "只输出JSON: {\"ok\": true}"}],
    max_tokens=200,
)
print("openai client ok:", resp.choices[0].message.content[:100])
