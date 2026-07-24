import pytest

from boss_agent_cli.safety.risk_lock import (
	AccountRiskLocked,
	assert_no_risk_lock,
	read_risk_lock,
	risk_lock_path,
	write_risk_lock,
)


def test_write_and_read_risk_lock(tmp_path):
	lock = write_risk_lock(tmp_path, "zhipin", message="account banned", source="test")

	loaded = read_risk_lock(tmp_path, "zhipin")

	assert loaded is not None
	assert loaded.code == "ACCOUNT_RISK"
	assert loaded.message == "account banned"
	assert loaded.source == "test"
	assert risk_lock_path(tmp_path, "zhipin").exists()
	assert lock.created_at


def test_assert_no_risk_lock_blocks_when_lock_exists(tmp_path):
	write_risk_lock(tmp_path, "zhipin", message="locked", source="test")

	with pytest.raises(AccountRiskLocked, match="locked"):
		assert_no_risk_lock(tmp_path, "zhipin")


def test_malformed_risk_lock_fails_closed(tmp_path):
	path = risk_lock_path(tmp_path, "zhipin")
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text("{not json", encoding="utf-8")

	with pytest.raises(AccountRiskLocked, match="could not be parsed"):
		assert_no_risk_lock(tmp_path, "zhipin")
