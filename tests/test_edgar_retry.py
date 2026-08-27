import httpx
from tenacity import wait_none

from financial_doc_ai.ingestion.edgar import EdgarClient, RetryableError


def test_retries_on_429_then_succeeds():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429)  # first call: rate limited
        return httpx.Response(200, text="ok")  # retry: success

    client = EdgarClient(
        user_agent="test-agent test@example.com",
        transport=httpx.MockTransport(handler),
    )
    client._get.retry.wait = wait_none()  # no real backoff sleep

    r = client._get("https://example.com/x")
    assert r.status_code == 200
    assert calls["n"] == 2  # proved it retried once


def test_gives_up_after_max_attempts():
  def handler(request):
      return httpx.Response(500)  # always fails

  client = EdgarClient(
      user_agent="test-agent test@example.com",
      transport=httpx.MockTransport(handler),
  )
  client._get.retry.wait = wait_none()

  try:
      client._get("https://example.com/x")
      assert False, "should have raised"
  except RetryableError:
      pass  # gave up after 5 tries, reraised
