"""统一 HTTP 访问：User-Agent、超时、重试、限速。

所有网络请求都从这里发出，便于统一审计与限速。解析器不直接联网。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlparse

import httpx

USER_AGENT = "citygdp/0.1 (academic data collection; 8-city GDP panel)"
DEFAULT_TIMEOUT = 60.0
DEFAULT_RETRIES = 3
# 同一主机两次请求的最小间隔（秒），避免给统计站点造成压力
DEFAULT_MIN_INTERVAL = 1.0


class FetchError(RuntimeError):
    """网络请求最终失败。"""


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass(frozen=True)
class Response:
    url: str
    status: int
    content: bytes
    headers: dict[str, str] = field(default_factory=dict)
    fetched_at: str = ""


class HttpClient:
    def __init__(
        self,
        min_interval: float = DEFAULT_MIN_INTERVAL,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
    ) -> None:
        self.min_interval = min_interval
        self.retries = retries
        try:
            self._client = httpx.Client(
                headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
                timeout=timeout,
                follow_redirects=True,
            )
        except (ImportError, httpx.InvalidURL) as exc:
            raise FetchError(
                "创建 HTTP 客户端失败，通常是代理环境变量导致：SOCKS 代理需安装 httpx[socks]；"
                "NO_PROXY 中含 [::1] 会触发 httpx 解析错误，可临时去掉该条目。"
                f"原始错误：{exc}"
            ) from exc
        self._last_request: dict[str, float] = {}

    # -- 生命周期 -------------------------------------------------------
    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- 内部 -----------------------------------------------------------
    def _throttle(self, host: str) -> None:
        elapsed = time.monotonic() - self._last_request.get(host, 0.0)
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_request[host] = time.monotonic()

    # -- 对外 -----------------------------------------------------------
    def get(self, url: str) -> Response:
        host = urlparse(url).netloc
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            self._throttle(host)
            try:
                raw = self._client.get(url)
            except httpx.HTTPError as exc:  # 连接失败、超时等
                last_error = exc
            else:
                if raw.status_code >= 500 or raw.status_code == 429:
                    last_error = FetchError(f"GET {url} 返回 {raw.status_code}")
                elif raw.status_code >= 400:
                    raise FetchError(f"GET {url} 返回 {raw.status_code}")
                else:
                    return Response(
                        url=str(raw.url),
                        status=raw.status_code,
                        content=raw.content,
                        headers={k.lower(): v for k, v in raw.headers.items()},
                        fetched_at=now_iso(),
                    )
            if attempt < self.retries:
                time.sleep(2**attempt)
        raise FetchError(f"GET {url} 失败（重试 {self.retries} 次）：{last_error}")
