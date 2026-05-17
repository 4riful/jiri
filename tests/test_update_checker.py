from __future__ import annotations

import subprocess

from jiri import update_checker


def completed(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=(), returncode=returncode, stdout=stdout, stderr="")


def test_update_checker_reports_up_to_date(monkeypatch, tmp_path):
    sha = "a" * 40

    def fake_run(args, cwd, timeout_seconds):
        if args[:3] == ("git", "rev-parse", "--is-inside-work-tree"):
            return completed("true\n")
        if args == ("git", "rev-parse", "HEAD"):
            return completed(f"{sha}\n")
        if args == ("git", "rev-parse", "--abbrev-ref", "HEAD"):
            return completed("main\n")
        if args == ("git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"):
            return completed("origin/main\n")
        if args == ("git", "remote", "get-url", "origin"):
            return completed("https://example.com/repo.git\n")
        if args[:2] == ("git", "ls-remote"):
            return completed(f"{sha}\trefs/heads/main\n")
        raise AssertionError(args)

    monkeypatch.setattr(update_checker, "_run", fake_run)

    result = update_checker.check_updates(repo_path=str(tmp_path))

    assert result["status"] == "up_to_date"
    assert result["local_sha"] == sha[:12]
    assert result["remote_sha"] == sha[:12]


def test_update_checker_reports_update_available(monkeypatch, tmp_path):
    local_sha = "a" * 40
    remote_sha = "b" * 40

    def fake_run(args, cwd, timeout_seconds):
        if args[:3] == ("git", "rev-parse", "--is-inside-work-tree"):
            return completed("true\n")
        if args == ("git", "rev-parse", "HEAD"):
            return completed(f"{local_sha}\n")
        if args == ("git", "rev-parse", "--abbrev-ref", "HEAD"):
            return completed("main\n")
        if args == ("git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"):
            return completed("origin/main\n")
        if args == ("git", "remote", "get-url", "origin"):
            return completed("https://example.com/repo.git\n")
        if args[:2] == ("git", "ls-remote"):
            return completed(f"{remote_sha}\trefs/heads/main\n")
        raise AssertionError(args)

    monkeypatch.setattr(update_checker, "_run", fake_run)

    result = update_checker.check_updates(repo_path=str(tmp_path))

    assert result["status"] == "update_available"
    assert result["local_sha"] == local_sha[:12]
    assert result["remote_sha"] == remote_sha[:12]


def test_update_checker_handles_non_git_repo(monkeypatch, tmp_path):
    def fake_run(args, cwd, timeout_seconds):
        return completed("false\n", returncode=1)

    monkeypatch.setattr(update_checker, "_run", fake_run)

    result = update_checker.check_updates(repo_path=str(tmp_path))

    assert result["status"] == "unavailable"
