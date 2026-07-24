import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from boss_agent_cli.api import endpoints
from boss_agent_cli.api.client import AccountRiskError, AuthError, BossClient
from boss_agent_cli.safety.risk_lock import AccountRiskLocked, risk_lock_path


class FakeCookieJar:
	def __init__(self, initial: dict[str, str] | None = None):
		self._data = dict(initial or {})

	def items(self):
		return self._data.items()

	def set(self, name: str, value: str):
		self._data[name] = value

	def get(self, name: str):
		return self._data.get(name)


class FakeResponse:
	def __init__(self, *, status_code: int = 200, payload: dict | None = None, text: str = "", cookies: dict | None = None):
		self.status_code = status_code
		self._payload = payload or {"code": 0}
		self.text = text
		self.cookies = FakeCookieJar(cookies)

	def json(self):
		return self._payload

	def raise_for_status(self):
		if self.status_code >= 400:
			raise RuntimeError(f"HTTP {self.status_code}")


class FakeHttpxClient:
	def __init__(self, responses: list[FakeResponse]):
		self.responses = list(responses)
		self.calls: list[dict] = []
		self.cookies = FakeCookieJar()

	def request(self, method: str, url: str, headers: dict | None = None, **kwargs):
		self.calls.append({"method": method, "url": url, "headers": headers, "kwargs": kwargs})
		return self.responses.pop(0)

	def close(self):
		pass


class FakeAuthManager:
	def __init__(self, data_dir: Path | None = None):
		self.token = {"cookies": {"wt2": "cookie"}, "stoken": "initial-stoken", "user_agent": "agent-ua"}
		self.refresh_calls: list[str | None] = []
		self.data_dir = data_dir or Path(tempfile.mkdtemp())
		self.platform = "zhipin"

	def get_token(self):
		return self.token

	def force_refresh(self, cdp_url: str | None = None):
		self.refresh_calls.append(cdp_url)
		self.token = {**self.token, "stoken": f"refreshed-{len(self.refresh_calls)}"}


def test_request_get_adds_stoken_and_merges_cookies():
	auth = FakeAuthManager()
	client = BossClient(auth)
	http_client = FakeHttpxClient([FakeResponse(payload={"code": 0}, cookies={"bst": "cookie-from-resp"})])
	client._client = http_client
	client._throttle.wait = lambda: None
	client._throttle.mark = lambda: None

	data = client._request("GET", endpoints.USER_INFO_URL, params={"page": 1})

	assert data["code"] == 0
	assert http_client.calls[0]["kwargs"]["params"]["__zp_stoken__"] == "initial-stoken"
	assert http_client.cookies.get("bst") == "cookie-from-resp"


@patch("boss_agent_cli.api.client.httpx.Client")
def test_request_writes_risk_lock_and_stops_after_403(mock_http_client_cls, tmp_path):
	auth = FakeAuthManager(tmp_path)
	first = FakeHttpxClient([FakeResponse(status_code=403, text="forbidden")])
	mock_http_client_cls.return_value = first

	client = BossClient(auth, cdp_url="http://127.0.0.1:9222")
	client._throttle.wait = lambda: None
	client._throttle.mark = lambda: None

	with pytest.raises(AccountRiskError):
		client._request("GET", endpoints.USER_INFO_URL)

	assert auth.refresh_calls == []
	assert risk_lock_path(tmp_path, "zhipin").exists()


def test_request_treats_environment_abnormal_as_account_risk(tmp_path):
	auth = FakeAuthManager(tmp_path)
	http_client = FakeHttpxClient([
		FakeResponse(payload={"code": endpoints.CODE_STOKEN_EXPIRED, "message": "您的环境存在异常."})
	])
	client = BossClient(auth)
	client._client = http_client
	client._throttle.wait = lambda: None
	client._throttle.mark = lambda: None

	with pytest.raises(AccountRiskError):
		client._request("GET", endpoints.USER_INFO_URL)

	assert auth.refresh_calls == []
	assert risk_lock_path(tmp_path, "zhipin").exists()


def test_browser_request_treats_environment_abnormal_as_account_risk(tmp_path):
	auth = FakeAuthManager(tmp_path)
	client = BossClient(auth)

	class FakeBrowser:
		_is_cdp = False
		_is_bridge = False

		def request(self, method, url, *, params=None, data=None):
			return {"code": endpoints.CODE_STOKEN_EXPIRED, "message": "您的环境存在异常."}

	client._get_browser = lambda: FakeBrowser()

	with patch("boss_agent_cli.api.browser_client.raw_cdp_fetch_json", side_effect=RuntimeError("no cdp")):
		with pytest.raises(AccountRiskError):
			client._browser_request("GET", endpoints.SEARCH_URL, params={"query": "AI产品经理"})

	assert risk_lock_path(tmp_path, "zhipin").exists()


def test_raw_cdp_request_uses_client_throttle(tmp_path):
	auth = FakeAuthManager(tmp_path)
	client = BossClient(auth)
	client._throttle = MagicMock()

	with patch(
		"boss_agent_cli.api.browser_client.raw_cdp_fetch_json",
		return_value={"code": 0, "zpData": {"jobList": []}},
	) as mock_fetch:
		result = client._browser_request("GET", endpoints.SEARCH_URL, params={"query": "AI product manager"})

	assert result["code"] == 0
	client._throttle.wait.assert_called_once_with()
	client._throttle.mark.assert_called_once_with()
	mock_fetch.assert_called_once()


def test_raw_cdp_request_marks_throttle_when_fetch_fails(tmp_path):
	auth = FakeAuthManager(tmp_path)
	client = BossClient(auth)
	client._throttle = MagicMock()

	class FakeBrowser:
		def request(self, method, url, *, params=None, data=None):
			return {"code": 0, "zpData": {}}

	client._get_browser = lambda: FakeBrowser()
	with patch("boss_agent_cli.api.browser_client.raw_cdp_fetch_json", side_effect=RuntimeError("cdp failed")):
		result = client._browser_request("GET", endpoints.SEARCH_URL)

	assert result["code"] == 0
	client._throttle.wait.assert_called_once_with()
	client._throttle.mark.assert_called_once_with()


def test_request_is_blocked_before_http_when_risk_lock_exists(tmp_path):
	auth = FakeAuthManager(tmp_path)
	risk_lock_path(tmp_path, "zhipin").parent.mkdir(parents=True, exist_ok=True)
	risk_lock_path(tmp_path, "zhipin").write_text(
		'{"platform":"zhipin","code":"ACCOUNT_RISK","message":"locked","source":"test","created_at":"now","user_clear_required":true}',
		encoding="utf-8",
	)

	client = BossClient(auth)

	with pytest.raises(AccountRiskLocked):
		client._request("GET", endpoints.USER_INFO_URL)


@patch("boss_agent_cli.api.client.random.uniform", return_value=0)
@patch("boss_agent_cli.api.client.time.sleep")
@patch("boss_agent_cli.api.client.httpx.Client")
def test_request_retries_after_stoken_expired_code(mock_http_client_cls, mock_sleep, mock_uniform):
	auth = FakeAuthManager()
	first = FakeHttpxClient([FakeResponse(payload={"code": endpoints.CODE_STOKEN_EXPIRED})])
	second = FakeHttpxClient([FakeResponse(payload={"code": 0, "zpData": {"ok": True}})])
	mock_http_client_cls.side_effect = [first, second]

	client = BossClient(auth)
	client._throttle.wait = lambda: None
	client._throttle.mark = lambda: None

	data = client._request("GET", endpoints.USER_INFO_URL)

	assert data["zpData"]["ok"] is True
	assert auth.refresh_calls == [None]
	assert mock_sleep.call_args_list[0].args[0] == 1
	assert second.calls[0]["kwargs"]["params"]["__zp_stoken__"] == "refreshed-1"


@patch("boss_agent_cli.api.client.time.sleep")
@patch("boss_agent_cli.api.client.httpx.Client")
def test_request_retries_after_rate_limited_code(mock_http_client_cls, mock_sleep):
	auth = FakeAuthManager()
	client_with_retry = FakeHttpxClient(
		[
			FakeResponse(payload={"code": endpoints.CODE_RATE_LIMITED}),
			FakeResponse(payload={"code": 0, "zpData": {"ok": True}}),
		],
	)
	mock_http_client_cls.return_value = client_with_retry

	client = BossClient(auth)
	client._throttle.wait = lambda: None
	client._throttle.mark = lambda: None

	data = client._request("GET", endpoints.USER_INFO_URL)

	assert data["zpData"]["ok"] is True
	assert auth.refresh_calls == []
	assert mock_sleep.call_args_list[0].args[0] == 10


@patch("boss_agent_cli.api.client.random.uniform", return_value=0)
@patch("boss_agent_cli.api.client.time.sleep")
@patch("boss_agent_cli.api.client.httpx.Client")
@pytest.mark.xfail(reason="403 is now treated as an account-risk hard stop instead of a token-refresh retry")
def test_request_raises_auth_error_after_max_403_retries(mock_http_client_cls, mock_sleep, mock_uniform):
	auth = FakeAuthManager()
	mock_http_client_cls.side_effect = [
		FakeHttpxClient([FakeResponse(status_code=403, text="forbidden")]),
		FakeHttpxClient([FakeResponse(status_code=403, text="forbidden")]),
		FakeHttpxClient([FakeResponse(status_code=403, text="forbidden")]),
		FakeHttpxClient([FakeResponse(status_code=403, text="forbidden")]),
	]

	client = BossClient(auth)
	client._throttle.wait = lambda: None
	client._throttle.mark = lambda: None

	with pytest.raises(AuthError, match="Token 刷新后仍被拒绝，请重新登录"):
		client._request("GET", endpoints.USER_INFO_URL)

	assert auth.refresh_calls == [None, None, None]
