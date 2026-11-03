import logging

import httpx
import pytest

from rss_wiki.http import HttpClient, HttpError, HttpResponse


def make_client(handler, **kwargs):
    sleeps: list[float] = []
    client = HttpClient(
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
        **kwargs,
    )
    return client, sleeps


def test_ok_returns_content_and_validators():
    def handler(request):
        return httpx.Response(
            200,
            content="안녕".encode(),
            headers={"ETag": '"abc"', "Last-Modified": "Wed, 21 Oct 2026 07:28:00 GMT"},
        )

    client, sleeps = make_client(handler)
    with client:
        resp = client.get("https://example.com/feed.xml")
    assert isinstance(resp, HttpResponse)
    assert resp.status == 200
    assert resp.content == "안녕".encode()
    assert resp.url == "https://example.com/feed.xml"
    assert resp.etag == '"abc"'
    assert resp.last_modified == "Wed, 21 Oct 2026 07:28:00 GMT"
    assert resp.not_modified is False
    assert sleeps == []


def test_user_agent_sent():
    seen = []

    def handler(request):
        seen.append(request.headers["user-agent"])
        return httpx.Response(200)

    client, _ = make_client(handler)
    client.get("https://example.com/")
    assert seen[0].startswith("rss-wiki/")


def test_conditional_headers_sent():
    seen = []

    def handler(request):
        seen.append(request.headers)
        return httpx.Response(200)

    client, _ = make_client(handler)
    client.get("https://example.com/", etag='"abc"', last_modified="Wed, 21 Oct 2026 07:28:00 GMT")
    client.get("https://example.com/")
    assert seen[0]["if-none-match"] == '"abc"'
    assert seen[0]["if-modified-since"] == "Wed, 21 Oct 2026 07:28:00 GMT"
    assert "if-none-match" not in seen[1]
    assert "if-modified-since" not in seen[1]


def test_304_not_modified():
    client, _ = make_client(lambda r: httpx.Response(304))
    resp = client.get("https://example.com/", etag='"abc"')
    assert resp.status == 304
    assert resp.not_modified is True


def test_retry_503_then_success_backoff():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503) if len(calls) <= 2 else httpx.Response(200, content=b"ok")

    client, sleeps = make_client(handler)
    resp = client.get("https://example.com/")
    assert resp.content == b"ok"
    assert len(calls) == 3
    assert sleeps == [1.0, 2.0]


def test_429_exhausts_retries():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(429)

    client, sleeps = make_client(handler)
    with pytest.raises(HttpError) as exc:
        client.get("https://example.com/")
    assert len(calls) == 4
    assert sleeps == [1.0, 2.0, 4.0]
    assert exc.value.transient is True
    assert exc.value.status == 429


def test_connect_error_transient():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("boom", request=request)

    client, sleeps = make_client(handler)
    with pytest.raises(HttpError) as exc:
        client.get("https://example.com/x")
    assert exc.value.transient is True
    assert exc.value.status is None
    assert len(sleeps) == 3
    assert calls == 4
    assert "https://example.com/x" in str(exc.value)


def test_timeout_transient():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    client, _ = make_client(handler, max_retries=1)
    with pytest.raises(HttpError) as exc:
        client.get("https://example.com/")
    assert exc.value.transient is True


def test_404_no_retry():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(404)

    client, sleeps = make_client(handler)
    with pytest.raises(HttpError) as exc:
        client.get("https://example.com/missing")
    assert len(calls) == 1
    assert sleeps == []
    assert exc.value.transient is False
    assert exc.value.status == 404
    assert "https://example.com/missing" in str(exc.value)
    assert "404" in str(exc.value)


def test_redirect_returns_final_url():
    def handler(request):
        if request.url.path == "/old":
            return httpx.Response(301, headers={"Location": "https://example.com/new"})
        return httpx.Response(200, content=b"new")

    client, _ = make_client(handler)
    resp = client.get("https://example.com/old")
    assert resp.url == "https://example.com/new"
    assert resp.content == b"new"


def test_backoff_base_custom():
    client, sleeps = make_client(lambda r: httpx.Response(500), max_retries=2, backoff_base=0.5)
    with pytest.raises(HttpError):
        client.get("https://example.com/")
    assert sleeps == [0.5, 1.0]


def test_self_redirect_is_non_transient_error():
    def handler(request):
        return httpx.Response(302, headers={"Location": str(request.url)})

    client, sleeps = make_client(handler)
    with pytest.raises(HttpError) as exc:
        client.get("https://example.com/loop")
    assert exc.value.transient is False
    assert "https://example.com/loop" in str(exc.value)
    assert "TooManyRedirects" in str(exc.value)
    assert isinstance(exc.value.__cause__, httpx.TooManyRedirects)
    assert sleeps == []


def test_unsupported_scheme_no_retry():
    sleeps: list[float] = []
    with HttpClient(sleep=sleeps.append) as client:
        with pytest.raises(HttpError) as exc:
            client.get("ftp://example.com/feed.xml")
    assert exc.value.transient is False
    assert "ftp://example.com/feed.xml" in str(exc.value)
    assert isinstance(exc.value.__cause__, httpx.UnsupportedProtocol)
    assert sleeps == []


def test_bad_gzip_body_is_non_transient_decoding_error():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(
            200, content=b"not gzip data", headers={"Content-Encoding": "gzip"}
        )

    client, sleeps = make_client(handler)
    with pytest.raises(HttpError) as exc:
        client.get("https://example.com/gz")
    assert exc.value.transient is False
    assert isinstance(exc.value.__cause__, httpx.DecodingError)
    assert "https://example.com/gz" in str(exc.value)
    assert len(calls) == 1
    assert sleeps == []


def test_negative_max_retries_rejected():
    with pytest.raises(ValueError):
        HttpClient(max_retries=-1)


def test_retry_logged_with_url(caplog):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503) if len(calls) == 1 else httpx.Response(200)

    client, _ = make_client(handler)
    with caplog.at_level(logging.DEBUG, logger="rss_wiki.http"):
        client.get("https://example.com/retry")
    assert any("https://example.com/retry" in r.getMessage() for r in caplog.records)


def test_304_without_validators():
    client, _ = make_client(lambda r: httpx.Response(304))
    resp = client.get("https://example.com/", etag='"abc"')
    assert resp.etag is None
    assert resp.last_modified is None
