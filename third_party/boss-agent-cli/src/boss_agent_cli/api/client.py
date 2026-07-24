import atexit
import random
import time
import weakref
from types import TracebackType
from typing import TYPE_CHECKING, Any, cast

import httpx

from boss_agent_cli.api import endpoints
from boss_agent_cli.api.httpx_helpers import (
	add_stoken_to_get_params,
	browser_headers,
	merge_response_cookies,
	referer_header,
)
from boss_agent_cli.api.throttle import RequestThrottle
from boss_agent_cli.safety.risk_lock import assert_no_risk_lock, write_risk_lock
from boss_agent_cli.search_filters import normalize_internship_job_type

if TYPE_CHECKING:
	from boss_agent_cli.api.browser_client import BrowserSession
	from boss_agent_cli.auth.manager import AuthManager

_MAX_RETRIES = 3
_PLATFORM_RISK_MESSAGE_MARKERS = (
	"环境存在异常",
	"安全验证",
	"验证码",
	"账号存在异常",
	"访问异常",
	"risk",
	"security verification",
)

# atexit safeguard: close any BossClient instances not explicitly closed
_OPEN_CLIENTS: weakref.WeakSet["BossClient"] = weakref.WeakSet()


def _close_open_clients() -> None:
	for client in list(_OPEN_CLIENTS):
		try:
			client.close()
		except Exception:
			pass


atexit.register(_close_open_clients)


def _looks_like_platform_risk(message: str) -> bool:
	message_l = message.lower()
	return any(marker.lower() in message_l for marker in _PLATFORM_RISK_MESSAGE_MARKERS)


class AuthError(Exception):
	pass


class AccountRiskError(Exception):
	"""BOSS 直聘风控拦截（code 36）：检测到异常行为。"""

	def __init__(self, message: str = "", is_cdp: bool = False):
		self.is_cdp = is_cdp
		super().__init__(message)


class BossClient:
	"""BOSS API client.

	BOSS live routes use one visible CDP browser session by default. This keeps
	cookies, stoken, user agent, TLS/browser runtime, and page storage in the
	same platform-visible environment instead of mixing httpx/headless channels.
	"""

	def __init__(
		self,
		auth_manager: "AuthManager",
		*,
		delay: tuple[float, float] = (1.5, 3.0),
		cdp_url: str | None = None,
		live_mode: str = "cdp_only",
	) -> None:
		self._auth = auth_manager
		self._delay = delay
		self._client: httpx.Client | None = None
		self._browser_session: "BrowserSession | None" = None
		self._throttle = RequestThrottle(delay)
		self._cdp_url = cdp_url
		self._live_mode = live_mode
		self._closed = False
		_OPEN_CLIENTS.add(self)

	def _get_client(self) -> httpx.Client:
		assert_no_risk_lock(self._auth.data_dir, self._auth.platform)
		if self._client is None:
			token = self._auth.get_token()
			headers = browser_headers(endpoints.DEFAULT_HEADERS, token)
			self._client = httpx.Client(
				base_url=endpoints.BASE_URL,
				cookies=token.get("cookies", {}),
				headers=headers,
				follow_redirects=True,
				timeout=30,
			)
		return self._client

	def _get_browser(self) -> "BrowserSession":
		assert_no_risk_lock(self._auth.data_dir, self._auth.platform)
		if self._browser_session is None:
			from boss_agent_cli.api.browser_client import BrowserSession
			token = self._auth.get_token()
			self._browser_session = BrowserSession(
				cookies=token.get("cookies", {}),
				user_agent=token.get("user_agent", ""),
				delay=self._delay,
				cdp_url=self._cdp_url,
				logger=getattr(self._auth, '_logger', None),
				prefer_cdp=True,
				require_cdp=self._live_mode == "cdp_only",
			)
		return self._browser_session

	# ── Anti-detection delays (httpx channel) ────────────────────────

	def _headers_for(self, url: str) -> dict[str, str]:
		return referer_header(url, endpoints.REFERER_MAP, f"{endpoints.BASE_URL}/")

	def _merge_cookies(self, resp: httpx.Response) -> None:
		merge_response_cookies(self._get_client(), resp)

	# ── httpx request (low-risk ops) ─────────────────────────────────

	def _request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
		"""httpx 请求，循环重试（最多 _MAX_RETRIES 次），替代递归调用。"""
		assert_no_risk_lock(self._auth.data_dir, self._auth.platform)
		allow_refresh = bool(kwargs.pop("allow_refresh", True))
		max_retries = int(kwargs.pop("max_retries", _MAX_RETRIES))
		for attempt in range(max_retries + 1):
			client = self._get_client()
			token = self._auth.get_token()
			stoken = token.get("stoken", "")

			add_stoken_to_get_params(method, kwargs, stoken)

			self._throttle.wait()

			extra_headers = self._headers_for(url)
			resp = client.request(method, url, headers=extra_headers, **kwargs)
			self._throttle.mark()
			self._merge_cookies(resp)

			# 403 或安全验证 → 刷新 token 重试
			if resp.status_code == 403 or "安全验证" in resp.text:
				write_risk_lock(
					self._auth.data_dir,
					self._auth.platform,
					code="ACCOUNT_RISK",
					message=resp.text[:200] or "HTTP 403 or security verification returned by platform",
					source="httpx_status",
				)
				raise AccountRiskError("HTTP 403 or security verification returned by platform")
				if not allow_refresh:
					try:
						return cast("dict[str, Any]", resp.json())
					except ValueError:
						return {"code": resp.status_code, "status_code": resp.status_code, "message": resp.text[:200]}
				if attempt >= max_retries:
					raise AuthError("Token 刷新后仍被拒绝，请重新登录")
				backoff = (2 ** attempt) + random.uniform(0.5, 1.5)
				time.sleep(backoff)
				self._auth.force_refresh(cdp_url=self._cdp_url)
				self._client = None
				continue

			resp.raise_for_status()
			data = resp.json()
			code = data.get("code")
			message = str(data.get("message") or data.get("msg") or "")
			if code == endpoints.CODE_ACCOUNT_RISK or (
				code == endpoints.CODE_STOKEN_EXPIRED and _looks_like_platform_risk(message)
			):
				message = message or "BOSS reported account risk"
				write_risk_lock(
					self._auth.data_dir,
					self._auth.platform,
					code="ACCOUNT_RISK",
					message=message,
					source="httpx_response",
				)
				raise AccountRiskError(message)

			# stoken 过期 → 刷新重试
			if code == endpoints.CODE_STOKEN_EXPIRED and not allow_refresh:
				return cast("dict[str, Any]", data)
			if code == endpoints.CODE_STOKEN_EXPIRED and attempt < max_retries:
				backoff = (2 ** attempt) + random.uniform(0.5, 1.5)
				time.sleep(backoff)
				self._auth.force_refresh(cdp_url=self._cdp_url)
				self._client = None
				continue

			# 频率限制 → 冷却重试
			if code == endpoints.CODE_RATE_LIMITED and attempt < max_retries:
				cooldown = min(60, 10 * (2 ** attempt))
				time.sleep(cooldown)
				continue

			return cast("dict[str, Any]", data)

		raise AuthError("请求失败，已达最大重试次数")

	# ── Browser request (high-risk ops) ──────────────────────────────

	def _browser_request(self, method: str, url: str, *, params: dict[str, Any] | None = None, data: dict[str, Any] | None = None) -> dict[str, Any]:
		assert_no_risk_lock(self._auth.data_dir, self._auth.platform)
		if method.upper() == "GET":
			try:
				from boss_agent_cli.api.browser_client import raw_cdp_fetch_json

				# The raw CDP fast path bypasses BrowserSession, so it must use the
				# client-level throttle itself. Without this, opportunity detail
				# expansion can issue a burst of requests in a fraction of a second.
				self._throttle.wait()
				try:
					result = raw_cdp_fetch_json(
						self._cdp_url or "http://127.0.0.1:9222",
						method,
						url,
						params=params,
						data=data,
						referer=self._headers_for(url).get("Referer", f"{endpoints.BASE_URL}/"),
					)
				finally:
					self._throttle.mark()
				code = result.get("code")
				message = str(result.get("message") or result.get("msg") or "")
				if code == endpoints.CODE_ACCOUNT_RISK or (
					code == endpoints.CODE_STOKEN_EXPIRED and _looks_like_platform_risk(message)
				):
					msg = str(result.get("message") or "BOSS reported account risk")
					write_risk_lock(
						self._auth.data_dir,
						self._auth.platform,
						code="ACCOUNT_RISK",
						message=msg,
						source="raw_cdp_response",
					)
					raise AccountRiskError(msg, is_cdp=True)
				return result
			except AccountRiskError:
				raise
			except Exception as exc:
				logger = getattr(self._auth, "_logger", None)
				if logger:
					logger.info(f"[boss] raw CDP fetch 不可用: {exc}")
				pass
		result = self._get_browser().request(method, url, params=params, data=data)
		code = result.get("code")
		message = str(result.get("message") or result.get("msg") or "")
		if code == endpoints.CODE_ACCOUNT_RISK or (
			code == endpoints.CODE_STOKEN_EXPIRED and _looks_like_platform_risk(message)
		):
			msg = result.get("message", "账户存在异常行为")
			browser = self._browser_session
			is_cdp = getattr(browser, "_is_cdp", False) if browser is not None else False
			mode = "CDP" if is_cdp else ("Bridge" if browser is not None and getattr(browser, "_is_bridge", False) else "browser")
			write_risk_lock(
				self._auth.data_dir,
				self._auth.platform,
				code="ACCOUNT_RISK",
				message=str(msg),
				source="browser_response",
			)
			raise AccountRiskError(
				f"BOSS 直聘风控拦截 (code {code}): {msg}。"
				f"当前浏览器模式: {mode}。"
				f"建议：停止自动化访问并回到 BOSS 直聘官方页面手动处理。",
				is_cdp=is_cdp,
			)
		return result

	@staticmethod
	def _needs_browser_search_fallback(result: dict[str, Any]) -> bool:
		"""Whether list search should retry inside the logged-in browser runtime."""
		code = result.get("code")
		message = str(result.get("message") or "")
		if code == endpoints.CODE_STOKEN_EXPIRED:
			return True
		if code in (401, 403):
			return True
		if _looks_like_platform_risk(message):
			return False
		return any(marker in message for marker in ("stoken", "登录态"))

	# ── Public API ───────────────────────────────────────────────────
	# High-risk: search, recommend, greet, job_card → browser channel
	# Low-risk: status, me, cities, schema, detail → httpx channel

	def search_jobs(self, query: str, **filters: Any) -> dict[str, Any]:
		query, normalized_job_type, _ = normalize_internship_job_type(query, filters.get("job_type"))
		if normalized_job_type != filters.get("job_type"):
			filters = {**filters, "job_type": normalized_job_type}
		params: dict[str, Any] = {"query": query, "page": filters.get("page", 1)}
		if raw_params := filters.get("raw_params"):
			params.update(raw_params)
		if city := filters.get("city"):
			code = endpoints.CITY_CODES.get(city)
			if code is None:
				raise ValueError(f"未知城市: {city}")
			params["city"] = code
		if salary := filters.get("salary"):
			code = filters.get("salary_code") or endpoints.SALARY_CODES.get(salary)
			if code:
				params["salary"] = code
		if exp := filters.get("experience"):
			code = filters.get("experience_code") or endpoints.EXPERIENCE_CODES.get(exp)
			if code:
				params["experience"] = code
		if edu := filters.get("education"):
			code = filters.get("education_code") or endpoints.EDUCATION_CODES.get(edu)
			if code:
				params["degree"] = code
		if scale := filters.get("scale"):
			code = filters.get("scale_code") or endpoints.SCALE_CODES.get(scale)
			if code:
				params["scale"] = code
		if industry := filters.get("industry"):
			code = filters.get("industry_code") or endpoints.INDUSTRY_CODES.get(industry)
			if code:
				params["industry"] = code
		if stage := filters.get("stage"):
			code = filters.get("stage_code") or endpoints.STAGE_CODES.get(stage)
			if code:
				params["stage"] = code
		if job_type := filters.get("job_type"):
			code = filters.get("job_type_code") or endpoints.JOB_TYPE_CODES.get(job_type)
			if code:
				params["jobType"] = code
		return self._browser_request("GET", endpoints.SEARCH_URL, params=params)

	def recommend_jobs(self, page: int = 1) -> dict[str, Any]:
		params = {"page": page}
		return self._browser_request("GET", endpoints.RECOMMEND_URL, params=params)

	def greet(self, security_id: str, job_id: str, message: str = "") -> dict[str, Any]:
		data = {
			"securityId": security_id,
			"jobId": job_id,
			"greeting": message or "您好，我对该岗位很感兴趣，希望能和您聊一聊。",
		}
		return self._browser_request("POST", endpoints.GREET_URL, data=data)

	def apply(self, security_id: str, job_id: str, lid: str = "") -> dict[str, Any]:
		"""Current minimal apply path - reuses the immediate-chat browser endpoint."""
		data = {
			"securityId": security_id,
			"jobId": job_id,
		}
		if lid:
			data["lid"] = lid
		return self._browser_request("POST", endpoints.GREET_URL, data=data)

	def job_card(self, security_id: str, lid: str = "") -> dict[str, Any]:
		"""httpx 优先 + 浏览器降级获取职位卡片信息。"""
		params = {"securityId": security_id, "lid": lid}
		return self._browser_request("GET", endpoints.JOB_CARD_URL, params=params)

	def job_card_httpx(self, security_id: str, lid: str = "") -> dict[str, Any]:
		"""Legacy direct HTTP route; blocked by default in CDP-only live mode."""
		if self._live_mode == "cdp_only":
			from boss_agent_cli.api.browser_client import BrowserSessionRequired

			raise BrowserSessionRequired("BOSS live routes are configured for CDP-only browser access.")
		params = {"securityId": security_id, "lid": lid}
		return self._request("GET", endpoints.JOB_CARD_URL, params=params)

	# ── Low-risk: httpx channel ──────────────────────────────────────

	def job_detail(self, job_id: str) -> dict[str, Any]:
		params = {"encryptJobId": job_id}
		return self._browser_request("GET", endpoints.DETAIL_URL, params=params)

	def user_info(self) -> dict[str, Any]:
		return self._browser_request("GET", endpoints.USER_INFO_URL)

	def resume_baseinfo(self) -> dict[str, Any]:
		return self._browser_request("GET", endpoints.RESUME_BASEINFO_URL)

	def resume_expect(self) -> dict[str, Any]:
		return self._browser_request("GET", endpoints.RESUME_EXPECT_URL)

	def deliver_list(self, page: int = 1) -> dict[str, Any]:
		params = {"page": page}
		return self._browser_request("GET", endpoints.DELIVER_LIST_URL, params=params)

	def friend_list(self, page: int = 1) -> dict[str, Any]:
		params = {"page": page}
		return self._browser_request("GET", endpoints.FRIEND_LIST_URL, params=params)

	def interview_data(self) -> dict[str, Any]:
		return self._browser_request("GET", endpoints.INTERVIEW_DATA_URL)

	def job_history(self, page: int = 1) -> dict[str, Any]:
		params = {"page": page}
		return self._browser_request("GET", endpoints.JOB_HISTORY_URL, params=params)

	def chat_history(self, gid: str, security_id: str, *, page: int = 1, count: int = 20) -> dict[str, Any]:
		"""获取与指定好友的聊天消息历史。"""
		params = {"gid": gid, "securityId": security_id, "page": page, "c": count, "src": 0}
		return self._browser_request("GET", endpoints.CHAT_HISTORY_URL, params=params)

	def friend_label(self, friend_id: str, label_id: int, friend_source: int = 0, *, remove: bool = False) -> dict[str, Any]:
		"""添加或移除好友标签。"""
		url = endpoints.FRIEND_LABEL_DELETE_URL if remove else endpoints.FRIEND_LABEL_ADD_URL
		params = {"friendId": friend_id, "friendSource": friend_source, "labelId": label_id}
		return self._browser_request("GET", url, params=params)

	def exchange_contact(self, security_id: str, uid: str, name: str, exchange_type: int = 1) -> dict[str, Any]:
		"""请求交换联系方式（1=手机, 2=微信）。"""
		data = {"type": exchange_type, "securityId": security_id, "uniqueId": uid, "name": name}
		return self._browser_request("POST", endpoints.EXCHANGE_REQUEST_URL, data=data)

	def resume_status(self) -> dict[str, Any]:
		"""查询简历完整度和在线状态。"""
		return self._browser_request("GET", endpoints.RESUME_STATUS_URL)

	def geek_get_job(self, security_id: str) -> dict[str, Any]:
		"""查询与某招聘者的互动关系（是否已打招呼等）。"""
		params = {"securityId": security_id}
		return self._browser_request("GET", endpoints.GEEK_GET_JOB_URL, params=params)

	# ── Lifecycle ────────────────────────────────────────────────────

	def close(self) -> None:
		"""Release httpx client and browser session. Idempotent."""
		if self._closed:
			return
		self._closed = True
		if self._browser_session:
			self._browser_session.close()
			self._browser_session = None
		if self._client:
			self._client.close()
			self._client = None
		_OPEN_CLIENTS.discard(self)

	def __enter__(self) -> "BossClient":
		return self

	def __exit__(
		self,
		exc_type: type[BaseException] | None,
		exc_val: BaseException | None,
		exc_tb: TracebackType | None,
	) -> None:
		self.close()
