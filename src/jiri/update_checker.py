from __future__ import annotations

from pathlib import Path
import subprocess


def check_updates(repo_path: str | None = None, timeout_seconds: int = 5) -> dict[str, object]:
    root = Path(repo_path or ".").resolve()
    inside = _run(("git", "rev-parse", "--is-inside-work-tree"), root, timeout_seconds)
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return _result("unavailable", "Not running inside a Git repository.")

    head = _run(("git", "rev-parse", "HEAD"), root, timeout_seconds)
    branch = _run(("git", "rev-parse", "--abbrev-ref", "HEAD"), root, timeout_seconds)
    upstream = _run(("git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"), root, timeout_seconds)
    if head.returncode != 0 or branch.returncode != 0 or upstream.returncode != 0:
        return _result("unavailable", "No upstream branch configured for update checks.")

    upstream_name = upstream.stdout.strip()
    if "/" not in upstream_name:
        return _result("unavailable", "Upstream branch is invalid.")
    remote, remote_branch = upstream_name.split("/", 1)

    remote_url = _run(("git", "remote", "get-url", remote), root, timeout_seconds)
    if remote_url.returncode != 0:
        return _result("unavailable", "Git remote is not configured.")

    remote_head = _run(("git", "ls-remote", remote_url.stdout.strip(), f"refs/heads/{remote_branch}"), root, timeout_seconds)
    if remote_head.returncode != 0:
        return _result("unavailable", "Could not contact the update remote.")
    remote_sha = _first_sha(remote_head.stdout)
    if not remote_sha:
        return _result("unavailable", "Remote branch was not found.")

    local_sha = head.stdout.strip()
    status = "up_to_date" if local_sha == remote_sha else "update_available"
    message = "Already up to date." if status == "up_to_date" else "Update available on the configured Git remote."
    result = _result(status, message)
    result.update(
        {
            "branch": branch.stdout.strip(),
            "upstream": upstream_name,
            "local_sha": local_sha[:12],
            "remote_sha": remote_sha[:12],
        }
    )
    return result


def _first_sha(output: str) -> str:
    first_line = output.strip().splitlines()[0] if output.strip() else ""
    first_part = first_line.split(None, 1)[0] if first_line else ""
    return first_part if len(first_part) >= 7 else ""


def _result(status: str, message: str) -> dict[str, object]:
    return {"status": status, "message": message}


def _run(args: tuple[str, ...], cwd: Path, timeout_seconds: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=str(cwd), text=True, capture_output=True, timeout=timeout_seconds, check=False)
