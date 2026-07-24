"""auth/manager.py 覆盖率补齐测试。

覆盖 get_token 缓存、AuthRequired、_verify_cookie、force_refresh 所有分支、check_status、logout。
"""

from unittest.mock import MagicMock, patch

import pytest

from boss_agent_cli.auth.manager import AuthManager, AuthRequired, TokenRefreshFailed
from boss_agent_cli.safety.risk_lock import AccountRiskLocked, write_risk_lock


def _make_store(token: dict | None = None) -> MagicMock:
	store = MagicMock()
	store.load.return_value = token
	lock = MagicMock()
	lock.__enter__.return_value = None
	lock.__exit__.return_value = None
	store.refresh_lock.return_value = lock
	return store


# ── get_token ─────────────────────────────────────────────


@patch("boss_agent_cli.auth.manager.TokenStore")
def test_get_token_raises_auth_required_when_no_session(mock_store_cls, tmp_path):
	store = _make_store(token=None)
	mock_store_cls.return_value = store
	manager = AuthManager(tmp_path)

	with pytest.raises(AuthRequired, match="未登录"):
		manager.get_token()


@patch("boss_agent_cli.auth.manager.TokenStore")
def test_get_token_raises_platform_specific_auth_required_for_zhilian(mock_store_cls, tmp_path):
	store = _make_store(token=None)
	mock_store_cls.return_value = store
	manager = AuthManager(tmp_path, platform="zhilian")

	with pytest.raises(AuthRequired, match="boss --platform zhilian login"):
		manager.get_token()


@patch("boss_agent_cli.auth.manager.TokenStore")
def test_auth_manager_uses_default_zhipin_store_path(mock_store_cls, tmp_path):
	AuthManager(tmp_path)
	mock_store_cls.assert_called_once_with(tmp_path / "auth")


@patch("boss_agent_cli.auth.manager.TokenStore")
def test_auth_manager_uses_platform_scoped_store_path_for_zhilian(mock_store_cls, tmp_path):
	AuthManager(tmp_path, platform="zhilian")
	mock_store_cls.assert_called_once_with(tmp_path / "auth" / "zhilian")


@patch("boss_agent_cli.auth.manager.TokenStore")
@patch("boss_agent_cli.auth.manager.extract_cookies")
def test_login_is_blocked_when_risk_lock_exists(mock_extract, mock_store_cls, tmp_path):
	mock_store_cls.return_value = _make_store()
	write_risk_lock(tmp_path, "zhipin", message="locked by test", source="test")
	manager = AuthManager(tmp_path)

	with pytest.raises(AccountRiskLocked):
		manager.login(timeout=1)

	mock_extract.assert_not_called()


@patch("boss_agent_cli.auth.manager.TokenStore")
def test_get_token_loads_from_store_and_caches(mock_store_cls, tmp_path):
	token = {"cookies": {"wt2": "c1"}, "stoken": "s1"}
	store = _make_store(token=token)
	mock_store_cls.return_value = store
	manager = AuthManager(tmp_path)

	first = manager.get_token()
	second = manager.get_token()

	assert first == token
	assert second == token
	# load 应只被调用 1 次（缓存生效）
	assert store.load.call_count == 1


# ── login 降级链路 ─────────────────────────────────────────


@patch("boss_agent_cli.auth.manager.TokenStore")
@patch("boss_agent_cli.auth.manager.login_via_browser")
@patch("boss_agent_cli.auth.manager.login_via_cdp")
@patch("boss_agent_cli.auth.manager.probe_cdp")
@patch("boss_agent_cli.auth.manager.extract_cookies")
def test_zhipin_login_does_not_fallback_when_cdp_login_raises(
	mock_extract,
	mock_probe_cdp,
	mock_login_via_cdp,
	mock_login_via_browser,
	mock_store_cls,
	tmp_path,
):
	store = _make_store()
	mock_store_cls.return_value = store
	mock_extract.return_value = None
	mock_probe_cdp.return_value = True
	mock_login_via_cdp.side_effect = RuntimeError("cdp dead")

	manager = AuthManager(tmp_path)
	with pytest.raises(RuntimeError, match="cdp dead"):
		manager.login(timeout=30)

	mock_extract.assert_not_called()
	mock_login_via_cdp.assert_called_once_with(cdp_url=None, timeout=30, platform="zhipin", require_fresh=False)
	mock_login_via_browser.assert_not_called()
	store.save.assert_not_called()


@patch("boss_agent_cli.auth.manager.TokenStore")
@patch("boss_agent_cli.auth.manager.login_via_browser")
@patch("boss_agent_cli.auth.manager.login_via_cdp")
@patch("boss_agent_cli.auth.manager.probe_cdp")
@patch("boss_agent_cli.auth.manager.extract_cookies")
def test_zhipin_login_rejects_cdp_session_without_primary_cookie(
	mock_extract,
	mock_probe_cdp,
	mock_login_via_cdp,
	mock_login_via_browser,
	mock_store_cls,
	tmp_path,
):
	store = _make_store()
	mock_store_cls.return_value = store
	mock_extract.return_value = None
	mock_probe_cdp.return_value = True
	mock_login_via_cdp.return_value = {"cookies": {}, "stoken": "stale-token"}

	manager = AuthManager(tmp_path)
	with pytest.raises(AuthRequired, match="no valid BOSS login cookie"):
		manager.login(timeout=30)

	mock_login_via_cdp.assert_called_once()
	mock_login_via_browser.assert_not_called()
	store.save.assert_not_called()


@patch("boss_agent_cli.auth.manager.TokenStore")
@patch("boss_agent_cli.auth.manager.login_via_browser")
@patch("boss_agent_cli.auth.manager.probe_cdp")
@patch("boss_agent_cli.auth.manager.extract_cookies")
def test_zhipin_login_requires_cdp_instead_of_patchright_when_cdp_down(
	mock_extract,
	mock_probe_cdp,
	mock_login_via_browser,
	mock_store_cls,
	tmp_path,
):
	"""CDP 不可用时不降级到 patchright，避免新浏览器环境导致登录态错位。"""
	store = _make_store()
	mock_store_cls.return_value = store
	mock_extract.return_value = None
	mock_probe_cdp.return_value = False

	manager = AuthManager(tmp_path)
	with pytest.raises(AuthRequired, match="BROWSER_SESSION_REQUIRED"):
		manager.login(timeout=20)

	mock_extract.assert_not_called()
	mock_login_via_browser.assert_not_called()
	store.save.assert_not_called()


@patch("boss_agent_cli.auth.manager.TokenStore")
@patch("boss_agent_cli.auth.manager.login_via_browser")
@patch("boss_agent_cli.auth.manager.probe_cdp")
@patch("boss_agent_cli.auth.manager.extract_cookies")
def test_zhipin_login_ignores_cookie_extract_when_cdp_down(
	mock_extract,
	mock_probe_cdp,
	mock_login_via_browser,
	mock_store_cls,
	tmp_path,
):
	"""zhipin CDP-only mode should not try cookie/httpx/patchright fallbacks."""
	store = _make_store()
	mock_store_cls.return_value = store
	mock_extract.return_value = {"cookies": {"wt2": "stale"}, "stoken": ""}
	mock_probe_cdp.return_value = False

	manager = AuthManager(tmp_path)
	with pytest.raises(AuthRequired, match="BROWSER_SESSION_REQUIRED"):
		manager.login(timeout=10)

	mock_extract.assert_not_called()
	mock_login_via_browser.assert_not_called()
	store.save.assert_not_called()


# ── _verify_cookie 三个分支 ───────────────────────────────


@patch("boss_agent_cli.auth.manager.TokenStore")
@patch("httpx.get")
def test_verify_cookie_returns_true_when_code_zero(mock_get, mock_store_cls, tmp_path):
	mock_store_cls.return_value = _make_store()
	mock_resp = MagicMock()
	mock_resp.json.return_value = {"code": 0, "zpData": {"name": "tester"}}
	mock_get.return_value = mock_resp

	manager = AuthManager(tmp_path)
	result = manager._verify_cookie({"cookies": {"wt2": "abc"}, "user_agent": "UA"})
	assert result is True
	# 应使用 Cookie + UA
	call = mock_get.call_args
	assert call.kwargs["cookies"] == {"wt2": "abc"}
	assert "UA" in call.kwargs["headers"]["User-Agent"]


@patch("boss_agent_cli.auth.manager.TokenStore")
@patch("httpx.get")
def test_verify_cookie_returns_false_when_code_nonzero(mock_get, mock_store_cls, tmp_path):
	mock_store_cls.return_value = _make_store()
	mock_resp = MagicMock()
	mock_resp.json.return_value = {"code": 1001, "message": "need login"}
	mock_get.return_value = mock_resp

	manager = AuthManager(tmp_path)
	result = manager._verify_cookie({"cookies": {"wt2": "stale"}})
	assert result is False


@patch("boss_agent_cli.auth.manager.TokenStore")
@patch("httpx.get")
def test_verify_cookie_returns_false_on_http_error(mock_get, mock_store_cls, tmp_path):
	import httpx
	mock_store_cls.return_value = _make_store()
	mock_get.side_effect = httpx.ConnectError("no network")

	manager = AuthManager(tmp_path)
	result = manager._verify_cookie({"cookies": {"wt2": "x"}})
	assert result is False


@patch("boss_agent_cli.auth.manager.TokenStore")
@patch("httpx.get")
def test_verify_cookie_returns_false_on_value_error(mock_get, mock_store_cls, tmp_path):
	"""JSON 解析失败也要优雅返回 False。"""
	mock_store_cls.return_value = _make_store()
	mock_resp = MagicMock()
	mock_resp.json.side_effect = ValueError("not json")
	mock_get.return_value = mock_resp

	manager = AuthManager(tmp_path)
	assert manager._verify_cookie({"cookies": {"wt2": "x"}}) is False


@patch("boss_agent_cli.auth.manager.TokenStore")
@patch("httpx.get")
def test_verify_cookie_supports_zhilian_http_style_code(mock_get, mock_store_cls, tmp_path):
	mock_store_cls.return_value = _make_store()
	mock_resp = MagicMock()
	mock_resp.json.return_value = {"code": 200, "data": {"name": "tester"}}
	mock_get.return_value = mock_resp

	manager = AuthManager(tmp_path, platform="zhilian")
	result = manager._verify_cookie({"cookies": {"zp_token": "abc"}, "user_agent": "UA", "x_zp_client_id": "cid"})
	assert result is True
	call = mock_get.call_args
	assert call.kwargs["cookies"] == {"zp_token": "abc"}
	assert call.kwargs["headers"]["x-zp-client-id"] == "cid"


# ── force_refresh 剩余分支 ────────────────────────────────


@patch("boss_agent_cli.auth.manager.TokenStore")
@patch("boss_agent_cli.auth.manager.probe_cdp")
def test_force_refresh_requires_cdp_when_cdp_unavailable(
	mock_probe_cdp,
	mock_store_cls,
	tmp_path,
):
	"""CDP 不可用时不降级到 headless，避免混用浏览器环境。"""
	current = {"cookies": {"wt2": "c"}, "stoken": "old", "user_agent": "UA"}
	store = _make_store(token=current.copy())
	mock_store_cls.return_value = store
	mock_probe_cdp.return_value = False

	manager = AuthManager(tmp_path)
	with pytest.raises(TokenRefreshFailed, match="BROWSER_SESSION_REQUIRED"):
		manager.force_refresh()

	store.save.assert_not_called()
	assert manager._token is None


@patch("boss_agent_cli.auth.manager.TokenStore")
@patch("boss_agent_cli.auth.manager.login_via_cdp")
@patch("boss_agent_cli.auth.manager.probe_cdp")
def test_force_refresh_wraps_exception_in_tokenrefreshfailed(
	mock_probe_cdp,
	mock_login_via_cdp,
	mock_store_cls,
	tmp_path,
):
	current = {"cookies": {"wt2": "c"}, "stoken": "old", "user_agent": "UA"}
	store = _make_store(token=current.copy())
	mock_store_cls.return_value = store
	mock_probe_cdp.return_value = True
	mock_login_via_cdp.side_effect = RuntimeError("upstream 500")

	manager = AuthManager(tmp_path)
	with pytest.raises(TokenRefreshFailed, match="upstream 500"):
		manager.force_refresh()


# ── check_status / logout ─────────────────────────────────


@patch("boss_agent_cli.auth.manager.TokenStore")
def test_check_status_returns_loaded_token(mock_store_cls, tmp_path):
	token = {"cookies": {"wt2": "x"}, "stoken": "y"}
	store = _make_store(token=token)
	mock_store_cls.return_value = store

	manager = AuthManager(tmp_path)
	assert manager.check_status() == token


@patch("boss_agent_cli.auth.manager.TokenStore")
def test_check_status_returns_none_when_no_token(mock_store_cls, tmp_path):
	store = _make_store(token=None)
	mock_store_cls.return_value = store

	manager = AuthManager(tmp_path)
	assert manager.check_status() is None


@patch("boss_agent_cli.auth.manager.TokenStore")
def test_logout_clears_store_and_cached_token(mock_store_cls, tmp_path):
	token = {"cookies": {"wt2": "x"}, "stoken": "y"}
	store = _make_store(token=token)
	mock_store_cls.return_value = store

	manager = AuthManager(tmp_path)
	manager.get_token()  # populate cache
	assert manager._token is not None

	manager.logout()

	store.clear.assert_called_once()
	assert manager._token is None
