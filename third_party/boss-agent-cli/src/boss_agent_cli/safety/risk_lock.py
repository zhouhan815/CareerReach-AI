from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RISK_LOCK_FILENAME = "account_risk_lock.json"


class AccountRiskLocked(Exception):
	"""Raised when local safety state blocks platform automation."""


@dataclass(frozen=True)
class RiskLock:
	platform: str
	code: str
	message: str
	source: str
	created_at: str
	user_clear_required: bool = True

	def to_dict(self) -> dict[str, Any]:
		return {
			"platform": self.platform,
			"code": self.code,
			"message": self.message,
			"source": self.source,
			"created_at": self.created_at,
			"user_clear_required": self.user_clear_required,
		}


def risk_lock_path(data_dir: Path, platform: str = "zhipin") -> Path:
	suffix = platform or "zhipin"
	return data_dir / "safety" / suffix / RISK_LOCK_FILENAME


def read_risk_lock(data_dir: Path, platform: str = "zhipin") -> RiskLock | None:
	path = risk_lock_path(data_dir, platform)
	if not path.exists():
		return None
	try:
		raw = json.loads(path.read_text(encoding="utf-8"))
	except (OSError, ValueError, TypeError):
		return RiskLock(
			platform=platform,
			code="ACCOUNT_RISK",
			message=f"Risk lock exists but could not be parsed: {path}",
			source="risk_lock",
			created_at=datetime.now(timezone.utc).isoformat(),
		)
	if not isinstance(raw, dict):
		return None
	return RiskLock(
		platform=str(raw.get("platform") or platform),
		code=str(raw.get("code") or "ACCOUNT_RISK"),
		message=str(raw.get("message") or "Platform account risk lock is active"),
		source=str(raw.get("source") or "unknown"),
		created_at=str(raw.get("created_at") or ""),
		user_clear_required=bool(raw.get("user_clear_required", True)),
	)


def write_risk_lock(
	data_dir: Path,
	platform: str = "zhipin",
	*,
	code: str = "ACCOUNT_RISK",
	message: str = "Platform reported account risk; automation is stopped.",
	source: str = "platform",
) -> RiskLock:
	lock = RiskLock(
		platform=platform or "zhipin",
		code=code,
		message=message,
		source=source,
		created_at=datetime.now(timezone.utc).isoformat(),
	)
	path = risk_lock_path(data_dir, platform)
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(lock.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
	return lock


def clear_risk_lock(data_dir: Path, platform: str = "zhipin") -> bool:
	path = risk_lock_path(data_dir, platform)
	if not path.exists():
		return False
	path.unlink()
	return True


def assert_no_risk_lock(data_dir: Path, platform: str = "zhipin") -> None:
	lock = read_risk_lock(data_dir, platform)
	if lock is None:
		return
	raise AccountRiskLocked(
		f"{lock.code}: {lock.message}. Automation is blocked until the user manually verifies the official platform account and clears {risk_lock_path(data_dir, platform)}."
	)
