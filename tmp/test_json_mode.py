from openai import OpenAI
import httpx, json
client = OpenAI(
    base_url="https://43.138.203.19:12849/v1",
    api_key="sk-180f716366e99b203bd670819a0d6a6502041afadebc4da4060e098bc1234d40",
    http_client=httpx.Client(verify=False, timeout=300),
)
# 测试1: response_format json_object
try:
    resp = client.chat.completions.create(
        model="qwen3.8",
        messages=[{"role": "user", "content": "输出一个JSON对象，字段task_type，值为T1_staging"}],
        response_format={"type": "json_object"},
        max_tokens=200,
    )
    print("json_object mode:", resp.choices[0].message.content[:100])
except Exception as e:
    print("json_object mode FAILS:", str(e)[:150])

# 测试2: 思考模式检测（qwen3可能默认输出<think>）
resp2 = client.chat.completions.create(
    model="qwen3.8",
    messages=[{"role": "user", "content": "用JSON输出：{\"answer\": \"1+1=?\"}"}],
    max_tokens=500,
)
content = resp2.choices[0].message.content
print("raw contains <think>:", "<think>" in content)
print("content preview:", content[:200])
