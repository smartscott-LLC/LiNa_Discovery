"""Standing-grant settings tests (the PWA autonomy layer).

Pure logic only — no live database. grant_allows is the whole enforcement
contract: grants are opt-in per action type; unknown types are never granted.
"""
import sys

sys.path.insert(0, "/home/server/LiNa_Discovery/backend/lina")


from lina_service import GRANTABLE_ACTION_TYPES, grant_allows  # noqa: E402


class TestGrantAllows:
    def test_no_grants_grants_nothing(self):
        assert grant_allows(None, "file_read") is False
        assert grant_allows({}, "file_read") is False

    def test_explicit_grant(self):
        grants = {"file_read": True, "command": False}
        assert grant_allows(grants, "file_read") is True
        assert grant_allows(grants, "command") is False

    def test_unknown_type_never_granted(self):
        grants = {"file_read": True}
        assert grant_allows(grants, "totally_unknown") is False

    def test_grantable_types_are_the_ledger_types(self):
        # Every grantable kind is a real ledger type — the old "tool"
        # placeholder is gone; the concrete hands and eyes replaced it.
        assert "file_read" in GRANTABLE_ACTION_TYPES
        assert "file_write" in GRANTABLE_ACTION_TYPES
        assert "file_list" in GRANTABLE_ACTION_TYPES
        assert "file_search" in GRANTABLE_ACTION_TYPES
        assert "command" in GRANTABLE_ACTION_TYPES
        assert "browser" in GRANTABLE_ACTION_TYPES
        assert "tool" not in GRANTABLE_ACTION_TYPES
