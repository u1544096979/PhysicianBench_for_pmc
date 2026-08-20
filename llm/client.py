"""统一 LLM 客户端（v2 流水线专用）.

从项目根目录 .env 读取配置；自签证书端点自动禁用证书校验；
流式调用避免慢服务器长生成触发读超时；支持 json_object 模式
与软重试；429 显式退避；trace 落盘便于审计成本。
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from openai import OpenAI


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv(Path(__file__).resolve().parents[1] / ".env")


@dataclass
class TraceEntry:
    node: str
    prompt_chars: int
    completion_chars: int
    latency_s: float
    ok: bool
    error: str = ""


@dataclass
class LLMClient:
    base_url: str = field(default_factory=lambda: os.environ.get("GEN_LLM_BASE_URL", ""))
    api_key: str = field(default_factory=lambda: os.environ.get("GEN_LLM_API_KEY", ""))
    model: str = field(default_factory=lambda: os.environ.get("GEN_LLM_MODEL", ""))
    max_tokens: int = field(default_factory=lambda: int(os.environ.get("GEN_LLM_MAX_TOKENS", "16384")))
    timeout: float = field(default_factory=lambda: float(os.environ.get("GEN_LLM_TIMEOUT", "300")))
    concurrency: int = field(default_factory=lambda: int(os.environ.get("GEN_LLM_CONCURRENCY", "2")))
    trace_path: Path | None = None
    _semaphore: threading.Semaphore | None = None
    _client: OpenAI | None = None

    def __post_init__(self) -> None:
        self._semaphore = threading.Semaphore(max(1, self.concurrency))
        insecure = os.environ.get("GEN_LLM_INSECURE", "1") == "1"
        # 流式模式下 read 超时作用于相邻 chunk 间隔，60s 足够
        http_client = httpx.Client(
            verify=False if insecure else True,
            timeout=httpx.Timeout(connect=30, read=60, write=60, pool=self.timeout),
        )
        self._client = OpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
            http_client=http_client,
            max_retries=2,  # SDK层仅重试连接类错误
        )

    # ------------------------------------------------------------------
    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        node: str = "unknown",
        json_mode: bool = True,
        max_tokens: int | None = None,
        soft_retry: int = 1,
    ) -> str:
        """一次对话调用；json_mode 下若解析失败自动带纠错提示软重试.

        - 流式调用累积输出（防慢服务器读超时）
        - 429/并发限制：显式指数退避，最多额外5次
        """
        attempt = 0
        payload = list(messages)
        while True:
            attempt += 1
            started = time.time()
            try:
                with self._semaphore:
                    kwargs: dict[str, Any] = dict(
                        model=self.model,
                        messages=payload,
                        max_tokens=max_tokens or self.max_tokens,
                        temperature=0.2,
                    )
                    if json_mode:
                        kwargs["response_format"] = {"type": "json_object"}
                    # 关闭qwen3思考链：防止输出失控（1.5MB思考文本）
                    kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
                    # 流式调用：token边生成边传
                    kwargs["stream"] = True
                    chunks: list[str] = []
                    with self._client.chat.completions.create(**kwargs) as stream:
                        for event in stream:
                            delta = None
                            if getattr(event, "choices", None):
                                delta = event.choices[0].delta
                            if delta and delta.content:
                                chunks.append(delta.content)
                    content = "".join(chunks)
                content = content.strip()
                if json_mode:
                    content = self._strip_code_fence(content)
                    json.loads(content)  # 仅验证
                self._log_trace(node, payload, content, time.time() - started, ok=True)
                return content
            except Exception as exc:  # noqa: BLE001
                self._log_trace(node, payload, str(exc), time.time() - started, ok=False, error=str(exc)[:300])
                err_text = str(exc)
                is_rate_limit = "429" in err_text or "Concurrency" in err_text
                if is_rate_limit and attempt <= 5:
                    time.sleep(min(30 * attempt, 120))
                    continue
                if attempt <= soft_retry:
                    payload = payload + [
                        {"role": "user", "content": "上次调用失败或输出不是合法JSON。请重新输出，只输出一个合法的JSON对象，不要包含markdown代码块或任何多余文本。"},
                    ]
                    continue
                raise

    def chat_json(
        self,
        messages: list[dict[str, str]],
        *,
        node: str = "unknown",
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        raw = self.chat(messages, node=node, json_mode=True, max_tokens=max_tokens)
        return json.loads(raw)

    # ------------------------------------------------------------------
    @staticmethod
    def _strip_code_fence(text: str) -> str:
        if text.startswith("```"):
            first_newline = text.find("\n")
            if first_newline != -1:
                text = text[first_newline + 1:]
            if text.rstrip().endswith("```"):
                text = text.rstrip()[:-3]
        return text.strip()

    def _log_trace(
        self,
        node: str,
        prompt: list[dict[str, str]],
        completion: str,
        latency: float,
        *,
        ok: bool,
        error: str = "",
    ) -> None:
        if self.trace_path is None:
            return
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "node": node,
            "prompt_chars": sum(len(m.get("content", "")) for m in prompt),
            "completion_chars": len(completion),
            "latency_s": round(latency, 2),
            "ok": ok,
            "error": error,
        }
        self.trace_path.parent.mkdir(parents=True, exist_ok=True)
        with self.trace_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


_default_client: LLMClient | None = None


def get_default_client(trace_dir: Path | None = None) -> LLMClient:
    global _default_client
    if _default_client is None:
        trace_path = (trace_dir / "llm_trace.jsonl") if trace_dir else None
        _default_client = LLMClient(trace_path=trace_path)
    return _default_client
