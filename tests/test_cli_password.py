from __future__ import annotations

import pytest
from werkzeug.security import check_password_hash

from scheduler.cli import main
from scheduler.standalone import main as standalone_main


@pytest.mark.parametrize(
    "arguments",
    [
        ["SyntheticOnly-NoSecret-123!"],
        ["--password=SyntheticOnly-NoSecret-123!"],
        ["--", "SyntheticOnly-NoSecret-123!"],
        ["--not-a-real-option", "SyntheticOnly-NoSecret-123!"],
    ],
)
def test_hash_password_rejects_command_line_password_without_echo(arguments, capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["hash-password", *arguments])

    captured = capsys.readouterr()
    assert exc_info.value.code == 2
    assert "does not accept password arguments" in captured.err
    assert "SyntheticOnly-NoSecret-123!" not in captured.err
    assert captured.out == ""


def test_hash_password_prompts_and_prints_only_the_hash(monkeypatch, capsys):
    supplied_password = "SyntheticOnly-NoSecret-123!"
    prompts: list[str] = []
    monkeypatch.setattr(
        "getpass.getpass",
        lambda prompt: prompts.append(prompt) or supplied_password,
    )

    assert main(["hash-password"]) == 0

    captured = capsys.readouterr()
    password_hash = captured.out.strip()
    assert prompts == ["Operator password: "]
    assert check_password_hash(password_hash, supplied_password)
    assert supplied_password not in captured.out
    assert captured.err == ""


def test_hash_password_rejects_short_interactive_password(monkeypatch, capsys):
    monkeypatch.setattr("getpass.getpass", lambda _prompt: "short")

    assert main(["hash-password"]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "at least 12 characters" in captured.err


def test_hash_password_help_still_works(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["hash-password", "--help"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert "usage: agenda-relay hash-password" in captured.out
    assert captured.err == ""


def test_other_commands_keep_argparse_unknown_option_error(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["doctor", "--not-a-real-option"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 2
    assert "unrecognized arguments: --not-a-real-option" in captured.err


def test_windows_standalone_entry_point_also_rejects_password_argument(capsys):
    with pytest.raises(SystemExit) as exc_info:
        standalone_main(["hash-password", "SyntheticOnly-NoSecret-123!"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 2
    assert "does not accept password arguments" in captured.err
    assert "SyntheticOnly-NoSecret-123!" not in captured.err
