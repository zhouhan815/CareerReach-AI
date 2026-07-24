from pathlib import Path
from typing import Any

from boss_agent_cli.auth.browser import login_via_browser, login_via_cdp, probe_cdp
from boss_agent_cli.auth.cookie_extract import extract_cookies
from boss_agent_cli.auth.token_store import TokenStore
from boss_agent_cli.output import Logger
from boss_agent_cli.safety.risk_lock import assert_no_risk_lock


class AuthRequired(Exception):
	pass


class TokenRefreshFailed(Exception):
	pass


class AuthManager:
	def __init__(self, data_dir: Path, *, logger: Logger | None = None, platform: str = "zhipin") -> None:
		self._platform = platform or "zhipin"
		self._data_dir = data_dir
		auth_dir = data_dir / "auth" if self._platform == "zhipin" else data_dir / "auth" / self._platform
		self._store = TokenStore(auth_dir)
		self._token: dict[str, Any] | None = None
		self._logger = logger or Logger()

	@property
	def data_dir(self) -> Path:
		return self._data_dir

	@property
	def platform(self) -> str:
		return self._platform

	def _login_action(self) -> str:
		return "boss --platform zhilian login" if self._platform == "zhilian" else "boss login"

	def get_token(self) -> dict[str, Any]:
		if self._token is not None:
			return self._token
		self._token = self._store.load()
		if self._token is None:
			raise AuthRequired(f"未登录，请先执行 {self._login_action()}")
		return self._token

	def login(
		self,
		*,
		timeout: int = 120,
		cookie_source: str | None = None,
		cdp_url: str | None = None,
		force_cdp: bool = False,
	) -> dict[str, Any]:
		"""Login for the current platform.

		zhipin uses CDP-only session capture by default to keep the official
		browser session, cookies, stoken, and runtime fingerprint together.
		Other platforms keep the existing fallback chain.
		"""
		method = "未知"
		token: dict[str, Any] | None = None
		assert_no_risk_lock(self._data_dir, self._platform)

		if self._platform == "zhipin":
			if not probe_cdp(cdp_url):
				raise AuthRequired(
					"BROWSER_SESSION_REQUIRED: start the fixed Edge/Chrome CDP window, "
					"open zhipin.com, complete the official login there, then run boss login --cdp."
				)
			self._logger.info("使用 CDP-only 模式同步当前 BOSS 官方浏览器会话")
			token = login_via_cdp(cdp_url=cdp_url, timeout=timeout, platform=self._platform, require_fresh=False)
			if not self._has_primary_cookie(token):
				raise AuthRequired(
					"BROWSER_SESSION_REQUIRED: no valid BOSS login cookie was found in the CDP browser. "
					"Please complete the official login in that browser window first."
				)
			method = "CDP 会话同步"
			self._store.save(token)
			self._token = token
			return {**token, "_method": method}

		if force_cdp:
			# --cdp 强制模式：跳过 Cookie，CDP 不可用直接抛异常
			self._logger.info("强制 CDP 模式，跳过 Cookie 提取")
			token = login_via_cdp(cdp_url=cdp_url, timeout=timeout, platform=self._platform, require_fresh=False)
			if not self._verify_cookie(token):
				raise AuthRequired("CDP login returned credentials that the platform rejected; please complete a fresh login")
			method = "CDP 扫码"
			self._store.save(token)
			self._token = token
			return {**token, "_method": method}

		# 第一步：尝试从本地浏览器提取 Cookie
		self._logger.info("尝试从本地浏览器提取 Cookie...")
		token = extract_cookies(cookie_source, platform=self._platform)
		if token and self._has_primary_cookie(token):
			if self._verify_cookie(token):
				self._store.save(token)
				self._token = token
				self._logger.info("Cookie 提取成功，已保存")
				return {**token, "_method": "Cookie 提取"}
			self._logger.info("提取的 Cookie 已失效，降级到 CDP")
		else:
			self._logger.info("未能从浏览器提取 Cookie，降级到 CDP")

		# 第二步：CDP 自动探测
		if probe_cdp(cdp_url):
			self._logger.info("检测到 CDP 可用，尝试 CDP 登录...")
			try:
				token = login_via_cdp(cdp_url=cdp_url, timeout=timeout, platform=self._platform, require_fresh=False)
				if not self._verify_cookie(token):
					raise AuthRequired("CDP login returned credentials that the platform rejected; please complete a fresh login")
				method = "CDP 扫码"
				self._store.save(token)
				self._token = token
				return {**token, "_method": method}
			except Exception as e:
				self._logger.info(f"CDP 登录失败（{e}），降级到 patchright")
		else:
			self._logger.info("CDP 不可用，降级到 patchright")

		# patchright 扫码（非 zhipin 兜底）
		token = login_via_browser(timeout=timeout, platform=self._platform)
		method = "扫码登录"
		self._store.save(token)
		self._token = token
		return {**token, "_method": method}

	def _has_primary_cookie(self, token: dict[str, Any]) -> bool:
		cookies = token.get("cookies", {})
		if self._platform == "zhilian":
			return bool(cookies.get("at") or cookies.get("zp_token"))
		primary_cookie = "wt2"
		return bool(cookies.get(primary_cookie))

	def _verify_cookie(self, token: dict[str, Any]) -> bool:
		"""验证 Cookie 是否有效。"""
		try:
			import httpx
			if self._platform == "zhilian":
				from boss_agent_cli.api.zhilian_client import USER_INFO_URL
				headers = {
					"User-Agent": token.get("user_agent") or "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
					"Referer": "https://i.zhaopin.com/",
				}
				if client_id := token.get("x_zp_client_id") or token.get("client_id"):
					headers["x-zp-client-id"] = str(client_id)
				resp = httpx.get(
					USER_INFO_URL,
					cookies=token.get("cookies", {}),
					headers=headers,
					timeout=10,
				)
				data = resp.json()
				return bool(data.get("code") == 200)

			from boss_agent_cli.api import endpoints
			resp = httpx.get(
				endpoints.USER_INFO_URL,
				cookies=token.get("cookies", {}),
				headers={
					"User-Agent": token.get("user_agent") or "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
					"Referer": "https://www.zhipin.com/",
				},
				timeout=10,
			)
			data = resp.json()
			return bool(data.get("code") == 0)
		except (httpx.HTTPError, ValueError, KeyError):
			return False

	def force_refresh(self, cdp_url: str | None = None) -> None:
		assert_no_risk_lock(self._data_dir, self._platform)
		with self._store.refresh_lock():
			current = self._store.load()
			if current is None:
				raise TokenRefreshFailed("无法刷新 Token，请重新登录")
			self._logger.info("Token 过期，正在静默刷新...")
			try:
				if self._platform == "zhilian":
					refreshed = extract_cookies(None, platform=self._platform)
					if not refreshed or not self._verify_cookie(refreshed):
						refreshed = login_via_cdp(cdp_url=cdp_url, timeout=30, platform=self._platform)
					if not refreshed or not self._verify_cookie(refreshed):
						raise TokenRefreshFailed("智联登录态刷新失败，请重新登录")
					self._store.save(refreshed)
					self._token = refreshed
					return

				if not probe_cdp(cdp_url):
					raise TokenRefreshFailed(
						"BROWSER_SESSION_REQUIRED: CDP browser is required to refresh BOSS login state."
					)
				self._logger.info("检测到 CDP，重新同步完整 BOSS 浏览器会话")
				refreshed = login_via_cdp(cdp_url=cdp_url, timeout=30, platform=self._platform, require_fresh=False)
				if not self._has_primary_cookie(refreshed):
					raise TokenRefreshFailed("CDP browser does not contain a valid BOSS login cookie")
				self._store.save(refreshed)
				self._token = refreshed
			except Exception as e:
				raise TokenRefreshFailed(f"Token 刷新失败: {e}") from e

	def check_status(self) -> dict[str, Any] | None:
		return self._store.load()

	def logout(self) -> None:
		"""清除本地登录态"""
		self._store.clear()
		self._token = None
