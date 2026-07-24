from __future__ import annotations

import json
import time
import urllib.request

import websockets.sync.client as ws_client


def main() -> None:
	with urllib.request.urlopen("http://127.0.0.1:9222/json", timeout=3) as response:
		tabs = json.load(response)
	target = next(
		tab for tab in tabs
		if tab.get("type") == "page"
		and "zhipin.com" in tab.get("url", "")
		and tab.get("webSocketDebuggerUrl")
	)
	arg = {
		"url": "https://www.zhipin.com/wapi/zpgeek/search/joblist.json",
		"params": {
			"query": "AI产品经理",
			"page": "1",
			"city": "101020100",
			"scale": "301,302,303,304",
		},
	}
	script = """
async (arg) => {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 12000);
  try {
    const sp = new URLSearchParams(arg.params);
    const resp = await fetch(arg.url + "?" + sp.toString(), {
      credentials: "include",
      signal: controller.signal,
      headers: {
        Accept: "application/json, text/plain, */*",
        Referer: "https://www.zhipin.com/web/geek/job",
        "X-Requested-With": "XMLHttpRequest",
      },
    });
    return await resp.json();
  } catch (e) {
    return { code: -1, message: e.name + ": " + e.message, zpData: {} };
  } finally {
    clearTimeout(timer);
  }
}
"""
	expression = f"({script})({json.dumps(arg, ensure_ascii=False)})"
	with ws_client.connect(target["webSocketDebuggerUrl"], max_size=8 * 1024 * 1024) as ws:
		ws.send(json.dumps({
			"id": 1,
			"method": "Runtime.evaluate",
			"params": {
				"expression": expression,
				"returnByValue": True,
				"awaitPromise": True,
			},
		}))
		deadline = time.time() + 20
		while time.time() < deadline:
			raw = ws.recv(timeout=max(0.1, deadline - time.time()))
			message = json.loads(raw)
			if message.get("id") != 1:
				continue
			value = message.get("result", {}).get("result", {}).get("value", message)
			data = value.get("zpData", {}) if isinstance(value, dict) else {}
			jobs = data.get("jobList", []) if isinstance(data, dict) else []
			print(json.dumps({
				"code": value.get("code") if isinstance(value, dict) else None,
				"message": value.get("message") if isinstance(value, dict) else "invalid response",
				"job_count": len(jobs) if isinstance(jobs, list) else 0,
				"has_more": data.get("hasMore") if isinstance(data, dict) else None,
			}, ensure_ascii=True))
			return
	raise RuntimeError("probe timed out")


if __name__ == "__main__":
	main()
