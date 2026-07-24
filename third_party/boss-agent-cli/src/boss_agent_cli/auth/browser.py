import json
import os
import sys
import time
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

from patchright.sync_api import sync_playwright

LOGIN_PAGE_URL = "https://www.zhipin.com/web/user/"
HOME_URL = "https://www.zhipin.com/"
_DEFAULT_CDP_URL = "http://localhost:9222"

# 超时常量（秒/毫秒）
_CDP_PROBE_TIMEOUT = 3           # CDP 探测 HTTP 超时（秒）
_NAV_TIMEOUT_MS = 15000          # 页面导航超时（毫秒）
_NETWORKIDLE_GRACE_MS = 3000     # 首页进入 networkidle 的额外宽限（毫秒）
_POST_LOGIN_WAIT = 3             # 登录成功后等待 cookie 传播（秒）
_STOKEN_GENERATION_WAIT = 2      # stoken 生成等待（秒）

_PLATFORM_BROWSER_CONFIG: dict[str, dict[str, str]] = {
	"zhipin": {
		"login_page_url": LOGIN_PAGE_URL,
		"home_url": HOME_URL,
		"cookie_domain": "zhipin",
		"success_cookie": "wt2",
	},
	"zhilian": {
		"login_page_url": "https://rd6.zhaopin.com/app/im",
		"home_url": "https://rd6.zhaopin.com/app/im",
		"cookie_domain": "zhaopin",
		"success_cookie": "at",
	},
}
_ZHILIAN_HOST = "zhaopin.com"
_SYSTEM_CHROMIUM_CANDIDATES = [
	r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
	r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
	r"C:\Program Files\Google\Chrome\Application\chrome.exe",
	r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]


def _chromium_launch_options(*, headless: bool) -> dict[str, Any]:
	"""Use bundled Patchright Chromium when present, otherwise reuse system Edge/Chrome."""
	options: dict[str, Any] = {"headless": headless}
	env_path = os.environ.get("BOSS_AGENT_BROWSER_EXECUTABLE")
	for candidate in [env_path, *_SYSTEM_CHROMIUM_CANDIDATES]:
		if candidate and Path(candidate).exists():
			options["executable_path"] = candidate
			break
	return options


def _get_platform_config(platform: str) -> dict[str, str]:
	config = _PLATFORM_BROWSER_CONFIG.get(platform)
	if config is None:
		raise ValueError(f"unsupported platform: {platform}")
	return config


def _extract_zhilian_client_id(page: Any) -> str:
	try:
		return cast("str", page.evaluate("""
			() => {
				const keys = ["x-zp-client-id", "x_zp_client_id", "clientId"];
				for (const key of keys) {
					const value = window.localStorage.getItem(key) || window.sessionStorage.getItem(key);
					if (value) return value;
				}
				return '';
			}
		"""))
	except Exception:
		return ""


def _is_zhilian_url(url: str) -> bool:
	host = urlparse(url).hostname
	if host is None:
		return False
	host = host.rstrip(".").lower()
	return host == _ZHILIAN_HOST or host.endswith(f".{_ZHILIAN_HOST}")


def _find_zhilian_recruiter_page(pages: list[Any]) -> Any | None:
	for page in pages:
		url = getattr(page, "url", "")
		if _is_zhilian_url(url) and any(path in url for path in ("/app/im", "/app/recommend")):
			return page
	for page in pages:
		if _is_zhilian_url(getattr(page, "url", "")):
			return page
	return None


def _zhilian_client_id_from(cookies: dict[str, str], page: Any) -> str:
	return cookies.get("x-zp-client-id") or _extract_zhilian_client_id(page)


def _warm_home_for_runtime(page: Any, home_url: str, *, stage: str) -> None:
	"""预热首页运行时；networkidle 只尽力等待，不作为必须条件。"""
	try:
		page.goto(home_url, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT_MS)
	except Exception as e:
		print(f"[boss] {stage}：首页导航未在预期时间完成（{e}），继续尝试提取凭证", file=sys.stderr)
	try:
		page.wait_for_load_state("networkidle", timeout=_NETWORKIDLE_GRACE_MS)
	except Exception as e:
		print(f"[boss] {stage}：首页未进入 networkidle（{e}），继续提取凭证", file=sys.stderr)


def probe_cdp(cdp_url: str | None = None) -> str | None:
	"""探测 CDP 是否可用，返回 WebSocket URL 或 None。"""
	import httpx
	base = cdp_url or _DEFAULT_CDP_URL
	try:
		resp = httpx.get(f"{base}/json/version", timeout=_CDP_PROBE_TIMEOUT)
		return cast("str | None", resp.json().get("webSocketDebuggerUrl"))
	except (httpx.HTTPError, ValueError, KeyError):
		return None


def _list_cdp_targets(cdp_url: str | None = None) -> list[dict[str, Any]]:
	import httpx

	base = cdp_url or _DEFAULT_CDP_URL
	try:
		resp = httpx.get(f"{base}/json", timeout=_CDP_PROBE_TIMEOUT)
		resp.raise_for_status()
		data = resp.json()
	except (httpx.HTTPError, ValueError):
		return []
	return data if isinstance(data, list) else []


def _pick_cdp_page_ws(cdp_url: str | None, cookie_domain: str) -> str | None:
	targets = _list_cdp_targets(cdp_url)
	page_targets = [target for target in targets if target.get("type") == "page" and target.get("webSocketDebuggerUrl")]
	for target in page_targets:
		if cookie_domain in str(target.get("url", "")):
			return cast("str", target["webSocketDebuggerUrl"])
	return cast("str | None", page_targets[0].get("webSocketDebuggerUrl")) if page_targets else None


def _cdp_send(target_ws: str, method: str, params: dict[str, Any] | None = None, *, timeout: float = 5.0) -> dict[str, Any]:
	import websockets.sync.client as ws_client

	with ws_client.connect(target_ws, open_timeout=timeout, close_timeout=1, max_size=8 * 1024 * 1024) as ws:
		ws.send(json.dumps({"id": 1, "method": method, "params": params or {}}, ensure_ascii=False))
		deadline = time.time() + timeout
		while time.time() < deadline:
			raw = ws.recv(timeout=max(0.1, deadline - time.time()))
			msg = json.loads(raw)
			if msg.get("id") != 1:
				continue
			if "error" in msg:
				raise RuntimeError(str(msg["error"]))
			result = msg.get("result", {})
			return result if isinstance(result, dict) else {}
	raise TimeoutError(f"CDP command timed out: {method}")


def _raw_cdp_evaluate(target_ws: str, expression: str, *, timeout: float = 5.0) -> str:
	result = _cdp_send(
		target_ws,
		"Runtime.evaluate",
		{"expression": expression, "returnByValue": True, "awaitPromise": True},
		timeout=timeout,
	)
	value = result.get("result", {}).get("value")
	return str(value) if value is not None else ""


def _raw_cdp_cookies(target_ws: str, cookie_domain: str, *, timeout: float = 5.0) -> dict[str, str]:
	try:
		result = _cdp_send(target_ws, "Network.getAllCookies", timeout=timeout)
		cookies = result.get("cookies", [])
	except Exception:
		result = _cdp_send(target_ws, "Storage.getCookies", timeout=timeout)
		cookies = result.get("cookies", [])
	if not isinstance(cookies, list):
		return {}
	return {
		str(cookie.get("name")): str(cookie.get("value"))
		for cookie in cookies
		if cookie_domain in str(cookie.get("domain", ""))
	}


def _login_via_raw_cdp(*, cdp_url: str | None, timeout: int, platform: str, require_fresh: bool = False) -> dict[str, Any] | None:
	if platform != "zhipin":
		return None
	config = _get_platform_config(platform)
	target_ws = _pick_cdp_page_ws(cdp_url, config["cookie_domain"])
	if not target_ws:
		return None
	initial_cookies = _raw_cdp_cookies(target_ws, config["cookie_domain"], timeout=5) if require_fresh else {}
	initial_success = initial_cookies.get(config["success_cookie"], "")
	initial_stoken = initial_cookies.get("__zp_stoken__", "")
	if require_fresh:
		try:
			for name in initial_cookies:
				_cdp_send(target_ws, "Network.deleteCookies", {"name": name, "url": config["home_url"]}, timeout=5)
			_cdp_send(target_ws, "Page.navigate", {"url": config["login_page_url"]}, timeout=5)
		except Exception:
			pass
	deadline = time.time() + timeout
	last_cookies: dict[str, str] = {}
	while time.time() < deadline:
		last_cookies = _raw_cdp_cookies(target_ws, config["cookie_domain"], timeout=5)
		has_success = last_cookies.get(config["success_cookie"])
		token_changed = (
			has_success != initial_success
			or last_cookies.get("__zp_stoken__", "") != initial_stoken
		)
		if has_success and (not require_fresh or not initial_success or token_changed):
			ua = _raw_cdp_evaluate(target_ws, "navigator.userAgent", timeout=5)
			stoken = last_cookies.get("__zp_stoken__", "") or _raw_cdp_evaluate(
				target_ws,
				"document.cookie.match(/__zp_stoken__=([^;]+)/)?.[1] || window.__zp_stoken__ || ''",
				timeout=5,
			)
			return {"cookies": last_cookies, "stoken": stoken, "user_agent": ua}
		time.sleep(1)
	raise TimeoutError(f"CDP 扫码登录超时（{timeout}s）；last cookies={','.join(sorted(last_cookies))}")


def login_via_cdp(*, cdp_url: str | None = None, timeout: int = 120, platform: str = "zhipin", require_fresh: bool = False) -> dict[str, Any]:
	"""
	通过 CDP 连接用户 Chrome 扫码登录。
	返回 token dict，失败抛异常。
	"""
	config = _get_platform_config(platform)
	login_page_url = config["login_page_url"]
	home_url = config["home_url"]
	cookie_domain = config["cookie_domain"]
	success_cookie = config["success_cookie"]
	ws_url = probe_cdp(cdp_url)
	if not ws_url:
		raise ConnectionError("CDP 不可用，请先运行 boss-chrome 启动带调试端口的 Chrome")

	if require_fresh:
		print("[boss] 正在 CDP Chrome 中打开登录页...", file=sys.stderr)
	else:
		print("[boss] 正在从 CDP Chrome 同步当前登录会话...", file=sys.stderr)
	raw_result = _login_via_raw_cdp(cdp_url=cdp_url, timeout=timeout, platform=platform, require_fresh=require_fresh)
	if raw_result is not None:
		return raw_result

	pw = sync_playwright().start()
	browser = pw.chromium.connect_over_cdp(ws_url)
	ctx = browser.contexts[0] if browser.contexts else browser.new_context()
	page = _find_zhilian_recruiter_page(ctx.pages) if platform == "zhilian" else None
	created_page = page is None
	if page is None:
		page = ctx.new_page()

	try:
		initial_success = ""
		initial_stoken = ""
		if require_fresh:
			for cookie in ctx.cookies():
				if cookie["name"] == success_cookie and cookie_domain in cookie.get("domain", ""):
					initial_success = cookie.get("value", "")
				if cookie["name"] == "__zp_stoken__" and cookie_domain in cookie.get("domain", ""):
					initial_stoken = cookie.get("value", "")
		if require_fresh and (created_page or platform != "zhilian"):
			try:
				page.goto(
					login_page_url,
					wait_until="commit", timeout=_NAV_TIMEOUT_MS,
				)
			except Exception:
				pass

		if require_fresh:
			print(f"[boss] 请在 Chrome 中扫码登录，等待中...（超时 {timeout}s）", file=sys.stderr)
		else:
			print(f"[boss] 等待 CDP Chrome 中出现有效登录 Cookie...（超时 {timeout}s）", file=sys.stderr)

		for i in range(timeout):
			time.sleep(1)
			cookies = ctx.cookies()
			success = [c for c in cookies if c["name"] == success_cookie and cookie_domain in c.get("domain", "")]
			stokens = [c for c in cookies if c["name"] == "__zp_stoken__" and cookie_domain in c.get("domain", "")]
			token_changed = (
				(success and success[0].get("value", "") != initial_success)
				or (stokens and stokens[0].get("value", "") != initial_stoken)
			)
			if success and (not require_fresh or not initial_success or token_changed):
				print("[boss] 检测到登录成功！", file=sys.stderr)
				break
			if i > 0 and i % 15 == 0:
				print(f"[boss] 等待中... {i}s", file=sys.stderr)
		else:
			raise TimeoutError(f"CDP 扫码登录超时（{timeout}s）")

		time.sleep(_POST_LOGIN_WAIT)
		if created_page or platform != "zhilian":
			_warm_home_for_runtime(page, home_url, stage="CDP login post-home")
		all_cookies = {c["name"]: c["value"] for c in ctx.cookies() if cookie_domain in c.get("domain", "")}
		ua = page.evaluate("navigator.userAgent")
		stoken = ""
		if platform == "zhipin":
			stoken = all_cookies.get("__zp_stoken__", "") or _extract_stoken(page)
		x_zp_client_id = _zhilian_client_id_from(all_cookies, page) if platform == "zhilian" else ""

		result: dict[str, Any] = {"cookies": all_cookies, "stoken": stoken, "user_agent": ua}
		if x_zp_client_id:
			result["x_zp_client_id"] = x_zp_client_id
		return result
	finally:
		try:
			if created_page:
				page.close()
		finally:
			pw.stop()


def login_via_browser(*, timeout: int = 120, platform: str = "zhipin") -> dict[str, Any]:
	"""
	使用 patchright（Playwright 兼容 fork）打开登录页。
	双重检测登录成功：监听 API 响应 + 轮询 wt2 cookie。
	"""
	config = _get_platform_config(platform)
	login_page_url = config["login_page_url"]
	home_url = config["home_url"]
	cookie_domain = config["cookie_domain"]
	success_cookie = config["success_cookie"]
	with sync_playwright() as p:
		browser = p.chromium.launch(**_chromium_launch_options(headless=False))
		context = browser.new_context(
			viewport={"width": 1280, "height": 800},
			locale="zh-CN",
			timezone_id="Asia/Shanghai",
		)
		page = context.new_page()

		page.goto(login_page_url, wait_until="domcontentloaded")
		print("已打开 BOSS 直聘登录页。", file=sys.stderr)
		print(f"请扫码或手机号登录（超时 {timeout} 秒）...", file=sys.stderr)

		# 双重检测：API 响应 或 wt2 cookie 出现，任一触发即认为登录成功
		login_detected = False

		def _on_response(response: Any) -> None:
			nonlocal login_detected
			url = response.url
			if (url.startswith("https://www.zhipin.com/wapi/zppassport/qrcode/loginConfirm")
				or url.startswith("https://www.zhipin.com/wapi/zppassport/qrcode/dispatcher")
				or url.startswith("https://www.zhipin.com/wapi/zppassport/login/phoneV2")):
				login_detected = True

		page.on("response", _on_response)

		deadline = time.time() + timeout
		while time.time() < deadline and not login_detected:
			# 也通过 cookie 检测（覆盖 API 匹配不上的情况）
			try:
				cookies_list = context.cookies()
				if any(c["name"] == success_cookie and cookie_domain in c.get("domain", "") for c in cookies_list):
					login_detected = True
					break
			except Exception:
				pass
			time.sleep(1)

		if not login_detected:
			browser.close()
			raise TimeoutError(f"扫码登录超时（{timeout}秒）")

		print("检测到登录成功，正在提取凭证...", file=sys.stderr)
		time.sleep(_POST_LOGIN_WAIT)

		# 跳转主站提取完整 cookies 和 stoken
		_warm_home_for_runtime(page, home_url, stage="登录后回到首页")

		cookies_list = context.cookies()
		cookies = {c["name"]: c["value"] for c in cookies_list if cookie_domain in c.get("domain", "")}
		user_agent = page.evaluate("navigator.userAgent")
		stoken = _extract_stoken(page) if platform == "zhipin" else ""
		x_zp_client_id = _extract_zhilian_client_id(page) if platform == "zhilian" else ""

		browser.close()

	result: dict[str, Any] = {
		"cookies": cookies,
		"stoken": stoken,
		"user_agent": user_agent,
	}
	if x_zp_client_id:
		result["x_zp_client_id"] = x_zp_client_id
	return result


def refresh_stoken_via_cdp(cdp_url: str | None = None) -> str:
	"""通过 CDP Chrome 刷新 stoken（指纹一致，不会被拒）。"""
	ws_url = probe_cdp(cdp_url)
	if not ws_url:
		raise ConnectionError("CDP 不可用")

	pw = sync_playwright().start()
	browser = pw.chromium.connect_over_cdp(ws_url)
	ctx = browser.contexts[0] if browser.contexts else browser.new_context()
	page = ctx.new_page()

	try:
		page.goto(HOME_URL, wait_until="commit", timeout=15000)
	except Exception:
		pass
	time.sleep(_STOKEN_GENERATION_WAIT)

	stoken = _extract_stoken(page)
	page.close()
	pw.stop()

	if not stoken:
		raise RuntimeError("CDP 刷新 stoken 失败：页面未生成 stoken")
	return stoken


def refresh_stoken(cookies: dict[str, Any], user_agent: str) -> str:
	"""Deprecated: headless BOSS stoken refresh is disabled."""
	raise RuntimeError(
		"Headless stoken refresh is disabled for BOSS. "
		"Use the fixed CDP browser session and login_via_cdp(require_fresh=False)."
	)


def _extract_stoken(page: Any) -> str:
	try:
		stoken = page.evaluate("""
			() => {
				const match = document.cookie.match(/__zp_stoken__=([^;]+)/);
				return match ? match[1] : '';
			}
		""")
		if not stoken:
			stoken = page.evaluate("() => window.__zp_stoken__ || ''")
		return cast("str", stoken)
	except Exception:
		return ""
