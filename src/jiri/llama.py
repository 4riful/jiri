from __future__ import annotations

import os
import re
import signal
import subprocess
from pathlib import Path

import requests


def llama_status(port: int = 8080) -> dict[str, object]:
    pid = _find_pid_on_port(port)
    if pid is None:
        return {
            "running": False,
            "pid": None,
            "port": port,
            "model_name": None,
            "uptime": None,
        }
    model_name = _extract_model_name(pid)
    uptime = _process_uptime(pid)
    return {
        "running": True,
        "pid": pid,
        "port": port,
        "model_name": model_name,
        "uptime": uptime,
    }


def llama_start(
    model_path: str,
    port: int = 8080,
    context: int = 512,
    threads: int = 2,
    binary: str = "llama-server",
) -> dict[str, object]:
    if llama_status(port)["running"]:
        raise RuntimeError(f"Llama server already running on port {port}")
    if not Path(model_path).exists():
        raise FileNotFoundError(f"Model not found: {model_path}")
    env = os.environ.copy()
    env["LLAMA_CACHE"] = "/tmp/jiri-llama-cache"
    cmd = [
        binary,
        "--model", str(model_path),
        "--host", "127.0.0.1",
        "--port", str(port),
        "--ctx-size", str(context),
        "--threads", str(threads),
        "--no-webui",
    ]
    log_path = Path("/tmp/jiri-llama-server.log")
    with log_path.open("w") as log:
        proc = subprocess.Popen(
            cmd,
            stdout=log,
            stderr=subprocess.STDOUT,
            env=env,
            start_new_session=True,
        )
    return {"pid": proc.pid, "model_path": model_path, "port": port, "log": str(log_path)}


def llama_stop(pid: int | None = None, port: int = 8080) -> dict[str, object]:
    if pid is None:
        pid = _find_pid_on_port(port)
    if pid is None:
        return {"stopped": False, "reason": "not running"}
    try:
        os.kill(pid, signal.SIGTERM)
        os.kill(pid, signal.SIGCONT)
    except ProcessLookupError:
        pass
    try:
        os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        pass
    return {"stopped": True, "pid": pid}


def llama_test(port: int = 8080, timeout: int = 5) -> dict[str, object]:
    try:
        resp = requests.get(f"http://127.0.0.1:{port}/health", timeout=timeout)
        return {
            "ok": resp.status_code == 200,
            "status_code": resp.status_code,
            "response": resp.text[:500] if resp.status_code != 200 else None,
        }
    except requests.ConnectionError:
        return {"ok": False, "status_code": None, "response": "connection refused"}
    except requests.Timeout:
        return {"ok": False, "status_code": None, "response": "timeout"}


def llama_test_chat(port: int = 8080, prompt: str = "Hello", timeout: int = 15) -> dict[str, object]:
    url = f"http://127.0.0.1:{port}/v1/chat/completions"
    payload = {
        "model": "gemma-3-270m",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 20,
    }
    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            return {"ok": True, "status_code": 200, "response": content[:200]}
        else:
            comp_resp = requests.post(
                f"http://127.0.0.1:{port}/v1/completions",
                json={"model": "gemma-3-270m", "prompt": prompt, "max_tokens": 20},
                timeout=timeout,
            )
            if comp_resp.status_code == 200:
                c_data = comp_resp.json()
                c_text = c_data.get("choices", [{}])[0].get("text", "")
                return {"ok": True, "status_code": 200, "response": c_text[:200]}
            return {"ok": False, "status_code": resp.status_code, "response": resp.text[:300]}
    except requests.ConnectionError:
        return {"ok": False, "status_code": None, "response": "connection refused"}
    except requests.Timeout:
        return {"ok": False, "status_code": None, "response": "timeout"}


def llama_logs(tail: int = 50) -> str:
    log_path = Path("/tmp/jiri-llama-server.log")
    if not log_path.exists():
        return "No log file found."
    lines = log_path.read_text(errors="replace").splitlines()
    return "\n".join(lines[-tail:])


def _find_pid_on_port(port: int) -> int | None:
    try:
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            result = s.connect_ex(("127.0.0.1", port))
            if result != 0:
                return None
    except OSError:
        return None
    try:
        output = subprocess.check_output(
            ["ss", "-tlnp", f"sport = :{port}"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        # Regex to find pid=1234 anywhere in the line (e.g., inside users:(("llama-server",pid=123,fd=3)))
        match = re.search(r"pid=(\d+)", output)
        if match:
            return int(match.group(1))
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
        pass
    return None


def _extract_model_name(pid: int) -> str | None:
    try:
        cmd = Path(f"/proc/{pid}/cmdline").read_text(errors="replace")
        parts = cmd.split("\x00")
        for i, part in enumerate(parts):
            if part == "--model" and i + 1 < len(parts):
                return Path(parts[i + 1]).name
    except (OSError, IndexError):
        pass
    return None


def _process_uptime(pid: int) -> str | None:
    try:
        import time
        stat_path = Path(f"/proc/{pid}/stat")
        if not stat_path.exists():
            return None
        start_time = int(stat_path.read_text().split()[21])
        try:
            clk_tck_val = "SC_CLK_TCK"
            if hasattr(os, "SC_CLK_TCK"):
                clk_tck_val = os.SC_CLK_TCK
            clk_tck = os.sysconf(clk_tck_val)
        except (ValueError, OSError):
            clk_tck = 100
        start_sec = start_time / clk_tck
        uptime_sec = time.time() - start_sec
        minutes = int(uptime_sec // 60)
        seconds = int(uptime_sec % 60)
        return f"{minutes}m {seconds}s"
    except (OSError, ValueError, IndexError):
        return None
