"""Tests for remora.safety.ast_guard — AST-based command validation."""
from __future__ import annotations

import pytest

from remora.safety.ast_guard import (
    bashlex_available,
    parse_and_validate,
    sqlglot_available,
)


class TestParseAndValidateSafeCommands:
    def test_empty_string_is_safe(self) -> None:
        assert parse_and_validate("") is True

    def test_whitespace_is_safe(self) -> None:
        assert parse_and_validate("   ") is True

    def test_simple_read_is_safe(self) -> None:
        assert parse_and_validate("cat /etc/hosts") is True

    def test_ls_is_safe(self) -> None:
        assert parse_and_validate("ls -la /tmp") is True

    def test_echo_is_safe(self) -> None:
        assert parse_and_validate("echo hello world") is True

    def test_python_script_is_safe(self) -> None:
        assert parse_and_validate("python main.py --config prod.yaml") is True

    def test_grep_is_safe(self) -> None:
        assert parse_and_validate("grep -r pattern /var/log") is True


class TestParseAndValidateDestructiveShell:
    def test_rm_rf_blocked(self) -> None:
        assert parse_and_validate("rm -rf /") is False

    def test_rm_rf_home_blocked(self) -> None:
        assert parse_and_validate("rm -rf ~") is False

    def test_rm_force_recursive_blocked(self) -> None:
        assert parse_and_validate("rm --force --recursive /data") is False

    def test_rm_r_blocked(self) -> None:
        assert parse_and_validate("rm -r /some/path") is False

    def test_rm_f_blocked(self) -> None:
        assert parse_and_validate("rm -f /important/file") is False

    def test_git_force_push_blocked(self) -> None:
        assert parse_and_validate("git push --force origin main") is False

    def test_git_hard_reset_blocked(self) -> None:
        assert parse_and_validate("git reset --hard HEAD~5") is False


class TestParseAndValidatePrivilegeEscalation:
    def test_sudo_blocked(self) -> None:
        assert parse_and_validate("sudo rm -rf /") is False

    def test_sudo_standalone_blocked(self) -> None:
        assert parse_and_validate("sudo apt-get install vim") is False


class TestParseAndValidateSQLIfAvailable:
    def test_select_is_safe(self) -> None:
        assert parse_and_validate("SELECT id, name FROM users WHERE active = 1") is True

    @pytest.mark.skipif(not sqlglot_available(), reason="sqlglot not installed")
    def test_drop_table_blocked(self) -> None:
        assert parse_and_validate("DROP TABLE users") is False

    @pytest.mark.skipif(not sqlglot_available(), reason="sqlglot not installed")
    def test_truncate_blocked(self) -> None:
        assert parse_and_validate("TRUNCATE TABLE audit_log") is False

    @pytest.mark.skipif(not sqlglot_available(), reason="sqlglot not installed")
    def test_delete_without_where_blocked(self) -> None:
        assert parse_and_validate("DELETE FROM sessions") is False


class TestAvailabilityFlags:
    def test_bashlex_available_returns_bool(self) -> None:
        result = bashlex_available()
        assert isinstance(result, bool)

    def test_sqlglot_available_returns_bool(self) -> None:
        result = sqlglot_available()
        assert isinstance(result, bool)
