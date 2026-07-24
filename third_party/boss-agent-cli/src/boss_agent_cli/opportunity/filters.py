from __future__ import annotations

import re
from typing import Any

_INTERNSHIP_TITLE_TOKENS = ("实习", "实习生", "intern", "internship", "校招实习")
_INTERNSHIP_TEXT_TOKENS = ("每周实习", "实习期", "转正机会", "日薪", "元/天", "/天", "每天")
_DAY_RATE_RE = re.compile(r"(?<!\d)(?:[1-9]\d{1,3})\s*[-~—至]\s*(?:[1-9]\d{1,3})\s*(?:元)?\s*/?\s*天")
_MONTHLY_K_RE = re.compile(r"(?<!\d)(?:[1-9]\d?)\s*[-~—至]\s*(?:[1-9]\d?)\s*[kK](?:·?\d{1,2}薪)?")
_CHINESE_DIGITS = {
	"一": 1,
	"二": 2,
	"两": 2,
	"三": 3,
	"四": 4,
	"五": 5,
	"六": 6,
	"七": 7,
	"八": 8,
	"九": 9,
	"十": 10,
}
_WEEKLY_DAYS_RE = re.compile(
	r"(?:每周|一周|每星期|周|到岗|出勤|实习)[^\n，。,；;]{0,12}?([1-7一二两三四五六七])\s*(?:天|日)"
	r"|([1-7一二两三四五六七])\s*(?:天|日)\s*/\s*(?:周|星期)"
)
_MONTH_DURATION_RE = re.compile(
	r"(?:至少|不少于|不低于|连续|实习期|实习周期|周期|时长|实习)[^\n，。,；;]{0,12}?([1-9一二两三四五六七八九十])\s*(?:个)?月(?:以上|起)?"
	r"|([1-9一二两三四五六七八九十])\s*(?:个)?月(?:以上|起)?"
)
_WORK_ARRANGEMENT_CONTEXT_TOKENS = (
	"实习期",
	"实习周期",
	"实习时长",
	"实习时间",
	"到岗",
	"出勤",
	"每周",
	"一周",
	"每星期",
	"天/周",
	"天每周",
	"不少于",
	"不低于",
	"至少",
	"连续",
)
_WORK_DURATION_CONTEXT_TOKENS = (
	"实习",
	"实习期",
	"实习周期",
	"实习时长",
	"实习时间",
	"不少于",
	"不低于",
	"至少",
	"连续",
	"个月以上",
	"个月起",
)


def normalize_text(value: Any) -> str:
	if value is None:
		return ""
	if isinstance(value, list):
		return " ".join(normalize_text(item) for item in value)
	return str(value).strip()


def is_formal_monthly_salary(salary: str) -> bool:
	text = normalize_text(salary)
	return bool(_MONTHLY_K_RE.search(text)) or "K" in text or "k" in text


def is_day_rate_salary(salary: str) -> bool:
	text = normalize_text(salary)
	return bool(_DAY_RATE_RE.search(text)) or "/天" in text or "元/天" in text


def detect_internship_like(item: dict[str, Any]) -> tuple[bool, list[str]]:
	"""Detect roles that are already internships and should be excluded."""
	title = normalize_text(item.get("title") or item.get("jobName")).lower()
	salary = normalize_text(item.get("salary") or item.get("salaryDesc"))
	description = normalize_text(item.get("description") or item.get("postDescription"))
	reasons: list[str] = []

	if any(token in title for token in _INTERNSHIP_TITLE_TOKENS):
		reasons.append("岗位名包含实习/Intern")
	if is_day_rate_salary(salary):
		reasons.append("薪资是按天结算，疑似实习岗")
	if any(token in description for token in _INTERNSHIP_TEXT_TOKENS):
		reasons.append("岗位描述出现实习相关表述")

	if reasons and not is_formal_monthly_salary(salary):
		return True, reasons
	if any(token in title for token in _INTERNSHIP_TITLE_TOKENS):
		return True, reasons or ["岗位名包含实习"]
	return False, reasons


def detect_company_too_large(item: dict[str, Any]) -> tuple[bool, list[str]]:
	"""Exclude companies unlikely to open an ad-hoc internship slot for a formal role."""
	scale = normalize_text(item.get("company_scale") or item.get("scale") or item.get("brandScaleName"))
	min_scale, max_scale = parse_company_scale(scale)
	if min_scale is not None and min_scale >= 1000:
		return True, [f"公司规模为 {scale}，正式岗流程通常不适合临时沟通实习机会"]
	if max_scale is not None and max_scale >= 1000:
		return True, [f"公司规模为 {scale}，正式岗流程通常不适合临时沟通实习机会"]
	return False, []


_ANONYMOUS_COMPANY_RE = re.compile(
	r"^(?:(?:北京|上海|深圳|广州|杭州)?某.*公司|保密公司|匿名公司)$",
	re.IGNORECASE,
)
_HEADHUNTER_TOKENS = ("猎头", "猎头顾问", "人才顾问", "招聘顾问", "寻访顾问")
_CLOSED_TOKENS = ("职位已关闭", "该职位已关闭", "停止招聘", "已停止招聘", "职位不存在", "岗位已关闭", "job closed")
_WORK_LOCATION_RE = re.compile(
	r"(?:工作地点|办公地点|上班地点|实际工作地点|工作地址|办公地址|base\s*(?:地|城市)?)[：:\s]*([^\n。；;，,]{1,28})",
	re.IGNORECASE,
)
_CITY_ALIASES = {
	"上海": ("上海", "浦东", "徐汇", "黄浦", "静安", "长宁", "普陀", "虹口", "杨浦", "闵行", "宝山", "嘉定", "松江", "青浦", "奉贤", "金山", "崇明"),
	"深圳": ("深圳", "南山", "福田", "罗湖", "宝安", "龙岗", "龙华", "坪山", "光明", "盐田", "大鹏"),
}
_KNOWN_CITY_TOKENS = (
	"北京", "上海", "深圳", "广州", "杭州", "义乌", "金华", "苏州", "南京", "成都", "武汉", "西安", "重庆",
	"宁波", "无锡", "合肥", "天津", "厦门", "福州", "长沙", "青岛", "郑州", "东莞", "佛山", "珠海",
)


def detect_anonymous_or_headhunter(item: dict[str, Any]) -> tuple[bool, list[str]]:
	"""Exclude anonymous/headhunter listings that cannot directly open an internship slot."""
	company = normalize_text(item.get("company") or item.get("brandName"))
	boss_title = normalize_text(item.get("boss_title") or item.get("bossTitle"))
	if _ANONYMOUS_COMPANY_RE.match(company):
		return True, [f"公司名称为匿名/代招形式（{company}），无法确认用人团队是否能增设实习岗"]
	if any(token in boss_title for token in _HEADHUNTER_TOKENS):
		return True, [f"发布者职位为{boss_title}，属于猎头/第三方招聘，无法主导用人团队增设实习岗"]
	return False, []


def detect_job_closed(item: dict[str, Any], detail_error: str = "") -> tuple[bool, list[str]]:
	"""Detect closed roles from API status fields, page text, or detail errors."""
	payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
	status_values = [
		item.get("job_status"), item.get("status_desc"), payload.get("job_status"), payload.get("status_desc"),
	]
	for value in status_values:
		text = normalize_text(value).lower()
		if text in {"closed", "offline", "invalid", "expired", "已关闭", "已下线", "停止招聘"}:
			return True, [f"职位状态为 {normalize_text(value)}，岗位已关闭或下线"]
	combined = normalize_text([item.get("description"), detail_error, payload]).lower()
	if any(token.lower() in combined for token in _CLOSED_TOKENS):
		return True, ["职位详情明确显示已关闭/停止招聘"]
	return False, []


def detect_actual_location_mismatch(item: dict[str, Any]) -> tuple[bool, list[str]]:
	"""Reject listings whose JD explicitly names an actual city outside the advertised city."""
	target_city = normalize_text(item.get("city"))
	description = normalize_text([item.get("title"), item.get("description")])
	if not target_city or not description:
		return False, []
	aliases = _CITY_ALIASES.get(target_city, (target_city,))
	for match in _WORK_LOCATION_RE.finditer(description):
		location_clause = match.group(1).strip()
		if any(alias in location_clause for alias in aliases):
			continue
		other_cities = [city for city in _KNOWN_CITY_TOKENS if city != target_city and city in location_clause]
		if other_cities:
			return True, [f"平台标注城市为{target_city}，但 JD 明确写明实际工作地点为{location_clause}"]
	return False, []


def parse_company_scale(scale: str) -> tuple[int | None, int | None]:
	text = normalize_text(scale)
	numbers = [int(num) for num in re.findall(r"\d+", text)]
	if not numbers:
		return None, None
	if len(numbers) == 1:
		if any(token in text for token in ("以上", "+")):
			return numbers[0], None
		if any(token in text for token in ("少于", "以内", "以下")):
			return None, numbers[0]
		return numbers[0], numbers[0]
	return min(numbers[0], numbers[1]), max(numbers[0], numbers[1])


def _number_from_text(value: str) -> int | None:
	value = value.strip()
	if value.isdigit():
		return int(value)
	return _CHINESE_DIGITS.get(value)


def parse_work_arrangement(text: str) -> tuple[str, str]:
	"""Extract weekly attendance and internship duration from JD free text."""
	normalized = normalize_text(text)
	weekly_days = ""
	duration = ""
	week_match = _WEEKLY_DAYS_RE.search(normalized)
	if week_match:
		raw = next(group for group in week_match.groups() if group)
		days = _number_from_text(raw)
		if days:
			weekly_days = f"每周{days}天"
	month_match = _MONTH_DURATION_RE.search(normalized)
	if month_match:
		raw = next(group for group in month_match.groups() if group)
		months = _number_from_text(raw)
		if months:
			duration = f"{months}个月以上" if "以上" in month_match.group(0) or "至少" in month_match.group(0) or "不少于" in month_match.group(0) else f"{months}个月"
	return weekly_days, duration


def _work_arrangement_texts(values: list[str]) -> list[str]:
	candidates: list[str] = []
	for text in values:
		if len(text) <= 20:
			candidates.append(text)
			continue
		if len(text) <= 80 and any(token in text for token in _WORK_ARRANGEMENT_CONTEXT_TOKENS):
			candidates.append(text)
			continue
		clauses = [clause.strip() for clause in re.split(r"[\n。；;，,]", text) if clause.strip()]
		for clause in clauses:
			if len(clause) <= 80 and any(token in clause for token in _WORK_ARRANGEMENT_CONTEXT_TOKENS):
				candidates.append(clause)
	return candidates


def resolve_work_arrangement(*values: Any) -> tuple[str, str]:
	"""Prefer structured BOSS fields, then fall back to JD parsing."""
	texts = [normalize_text(value) for value in values if normalize_text(value)]
	weekly_days = ""
	duration = ""
	candidate_texts = _work_arrangement_texts(texts)
	for text in candidate_texts:
		if any(token in text for token in ("周", "星期", "到岗", "出勤", "天/周")):
			parsed_weekly, _ = parse_work_arrangement(text)
			weekly_days = weekly_days or parsed_weekly or (text if len(text) <= 20 else "")
		if "月" in text and (len(text) <= 20 or any(token in text for token in _WORK_DURATION_CONTEXT_TOKENS)):
			_, parsed_duration = parse_work_arrangement(text)
			duration = duration or parsed_duration or (text if len(text) <= 20 else "")
	weekly_text = "\n".join(candidate_texts)
	duration_text = "\n".join(
		text for text in candidate_texts if len(text) <= 20 or any(token in text for token in _WORK_DURATION_CONTEXT_TOKENS)
	)
	parsed_weekly, _ = parse_work_arrangement(weekly_text)
	_, parsed_duration = parse_work_arrangement(duration_text)
	return weekly_days or parsed_weekly or "待沟通", duration or parsed_duration or "待沟通"


def parse_salary_k_range(salary: str) -> tuple[int | None, int | None]:
	text = normalize_text(salary)
	match = _MONTHLY_K_RE.search(text)
	if not match:
		return None, None
	numbers = [int(num) for num in re.findall(r"\d+", match.group(0))[:2]]
	if len(numbers) < 2:
		return None, None
	return min(numbers[0], numbers[1]), max(numbers[0], numbers[1])
