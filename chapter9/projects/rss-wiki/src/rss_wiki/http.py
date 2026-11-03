"""httpx 기반 HTTP GET 래퍼: 조건부 요청과 지수 백오프 재시도."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version

import httpx

logger = logging.getLogger(__name__)


def _user_agent() -> str:
    try:
        return f"rss-wiki/{version('rss-wiki')}"
    except PackageNotFoundError:
        return "rss-wiki/unknown"


@dataclass
class HttpResponse:
    status: int
    content: bytes
    url: str
    etag: str | None = None
    last_modified: str | None = None
    not_modified: bool = False


class HttpError(Exception):
    """최종 실패. 메시지에 URL과 원인(상태 코드 또는 예외)을 포함한다."""

    def __init__(self, message: str, *, status: int | None = None, transient: bool = False):
        super().__init__(message)
        self.status = status
        self.transient = transient


class HttpClient:
    def __init__(
        self,
        timeout: float = 15,
        max_retries: int = 3,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        backoff_base: float = 1.0,
    ) -> None:
        if max_retries < 0:
            raise ValueError(f"max_retries는 0 이상이어야 합니다: {max_retries}")
        self._max_retries = max_retries
        self._sleep = sleep
        self._backoff_base = backoff_base
        self._client = httpx.Client(
            timeout=timeout,
            transport=transport,
            follow_redirects=True,
            headers={"User-Agent": _user_agent()},
        )

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def get(
        self,
        url: str,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> HttpResponse:
        """GET 요청. 2xx·304 응답을 반환하거나 HttpError만 던진다(httpx 예외는 새지 않음).

        일시적 오류(TransportError, 5xx, 429)는 지수 백오프로 최대 max_retries회 재시도하고
        끝내 실패하면 HttpError(transient=True). 잘못된 스킴(UnsupportedProtocol), 리다이렉트
        초과 등 그 밖의 RequestError와 4xx는 재시도 없이 HttpError(transient=False).
        """
        headers: dict[str, str] = {}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified

        attempt = 0
        while True:
            try:
                resp = self._client.get(url, headers=headers)
            except httpx.UnsupportedProtocol as exc:
                raise HttpError(
                    f"{url} 요청 실패: {type(exc).__name__}: {exc}", transient=False
                ) from exc
            except httpx.TransportError as exc:
                error = HttpError(f"{url} 요청 실패: {type(exc).__name__}: {exc}", transient=True)
                error.__cause__ = exc
            except httpx.RequestError as exc:
                raise HttpError(
                    f"{url} 요청 실패: {type(exc).__name__}: {exc}", transient=False
                ) from exc
            else:
                status = resp.status_code
                if status == 304 or 200 <= status < 300:
                    return HttpResponse(
                        status=status,
                        content=resp.content,
                        url=str(resp.url),
                        etag=resp.headers.get("ETag"),
                        last_modified=resp.headers.get("Last-Modified"),
                        not_modified=status == 304,
                    )
                if status != 429 and status < 500:
                    raise HttpError(
                        f"{url} 요청 실패: HTTP {status}", status=status, transient=False
                    )
                error = HttpError(f"{url} 요청 실패: HTTP {status}", status=status, transient=True)

            if attempt >= self._max_retries:
                raise error
            logger.debug("재시도 대상 오류 (%d회째): %s", attempt + 1, error)
            self._sleep(self._backoff_base * 2**attempt)
            attempt += 1
