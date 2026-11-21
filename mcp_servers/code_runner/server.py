"""Code Runner MCP server.

Runs on its own port (default 8102) using MCP's Streamable HTTP transport at /mcp.
Its one tool, run_python, runs a Python snippet and returns stdout, stderr and the
exit code.

Safety (the code comes from a learner or a model, so treat it as untrusted):
- Runs in a separate process with Python's isolated mode (-I), in a fresh temporary
  folder that is deleted afterwards, with an almost empty environment.
- Wall-clock timeout (the whole process group is killed), CPU-time and file-size limits.
- On macOS it runs inside `sandbox-exec`: no network, no writes outside its temp
  folder, no reading your home folder, and no starting other programs.
  Without sandbox-exec (e.g. on Linux) the server refuses to run code.
"""

import asyncio
import logging
import os
import resource
import shutil
import signal
import sys
import tempfile
import time

from mcp.server import MCPServer

PORT = int(os.getenv("PORT", "8102"))
TIMEOUT_SECONDS = 10
CPU_SECONDS = 5
MAX_FILE_BYTES = 10 * 1024 * 1024  # largest file the code may write
MAX_MEMORY_BYTES = 512 * 1024 * 1024  # best effort: macOS does not always enforce it
MAX_OUTPUT_CHARS = 8000  # per stream, so a huge print doesn't flood the model

# Run code with the plain Python install behind this venv, not the venv itself,
# so the code cannot import the server's packages.
PYTHON_HOME = os.path.realpath(sys.base_prefix)
PYTHON_BIN = os.path.join(PYTHON_HOME, "bin", f"python{sys.version_info.major}.{sys.version_info.minor}")
HOME = os.path.realpath(os.path.expanduser("~"))
SANDBOX_EXEC = shutil.which("sandbox-exec")

logger = logging.getLogger("code_runner")
_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(logging.Formatter("%(asctime)s [code_runner] %(message)s", datefmt="%H:%M:%S"))
logger.addHandler(_handler)
logger.setLevel(logging.INFO)
logger.propagate = False
# Hide uvicorn's per-request "POST /mcp" lines; the tool log is more useful.
logging.getLogger("uvicorn.access").addFilter(lambda record: False)

mcp = MCPServer("code_runner", instructions="Runs Python code in a sandbox.")


def _sandbox_profile(workdir: str) -> str:
    """macOS sandbox rules. Later rules win over earlier ones."""
    return f"""
(version 1)
(allow default)
(deny network*)
(deny process-exec)
(allow process-exec (literal "{PYTHON_BIN}"))
(deny file-write*)
(allow file-write* (subpath "{workdir}") (literal "/dev/null") (regex #"^/dev/(fd/|tty)"))
(deny file-read* (subpath "{HOME}"))
(allow file-read* (subpath "{PYTHON_HOME}") (subpath "{workdir}"))
"""


def _set_limits() -> None:
    """Runs in the child process just before Python starts."""
    resource.setrlimit(resource.RLIMIT_CPU, (CPU_SECONDS, CPU_SECONDS))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_FILE_BYTES, MAX_FILE_BYTES))
    try:
        resource.setrlimit(resource.RLIMIT_AS, (MAX_MEMORY_BYTES, MAX_MEMORY_BYTES))
    except (ValueError, OSError):
        pass  # not supported on this OS


def _clip(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + f"\n... [output cut: {len(text) - MAX_OUTPUT_CHARS} more characters]"


def _repair_escaped_newlines(code: str) -> str:
    """Small models sometimes send "\\n" (backslash + n) instead of real line breaks.

    Only if the code does not compile as sent, but does once "\\n"/"\\t" become real
    line breaks/tabs, is the repaired version used. Valid code is never changed.
    """
    try:
        compile(code, "main.py", "exec")
        return code
    except SyntaxError:
        pass
    repaired = code.replace("\\n", "\n").replace("\\t", "\t")
    try:
        compile(repaired, "main.py", "exec")
    except SyntaxError:
        return code  # still broken: run as sent so the learner sees the real error
    logger.info("   repaired literal \\n in code before running")
    return repaired


def _block(text: str) -> str:
    """Full text on its own indented lines, for the log."""
    return "".join(f"\n      {line}" for line in text.splitlines() or [""])


@mcp.tool()
async def run_python(code: str, stdin: str | None = None) -> dict:
    """Run a Python 3.12 program and return what it printed.

    Use this to check that code actually works: run the learner's code to find
    the real error, or run your own example or fix before showing it.
    The program has no internet access and no access to the user's files,
    and is stopped after 10 seconds. Only the standard library is available.

    Args:
        code: The complete Python program to run. Use print() to show results.
        stdin: Optional text to feed to input() calls, one value per line.
    """
    stdin = stdin or ""
    logger.info("→ run_python (%d chars, stdin %d chars):%s", len(code), len(stdin), _block(code))
    code = _repair_escaped_newlines(code)

    if SANDBOX_EXEC is None:
        result = {"error": "Code execution is disabled: sandbox-exec is not available on this system."}
        logger.info("← %s", result)
        return result

    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="code_runner_") as tmp:
        workdir = os.path.realpath(tmp)
        script = os.path.join(workdir, "main.py")
        with open(script, "w", encoding="utf-8") as f:
            f.write(code)

        process = await asyncio.create_subprocess_exec(
            SANDBOX_EXEC, "-p", _sandbox_profile(workdir),
            PYTHON_BIN, "-I", "-B", script,
            cwd=workdir,
            env={"PATH": "/usr/bin:/bin", "HOME": workdir, "TMPDIR": workdir, "PYTHONIOENCODING": "utf-8"},
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            preexec_fn=_set_limits,
            start_new_session=True,  # own process group, so a timeout kills child processes too
        )
        timed_out = False
        try:
            out, err = await asyncio.wait_for(process.communicate(stdin.encode()), TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            timed_out = True
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            out, err = await process.communicate()

    stdout = out.decode("utf-8", errors="replace")
    stderr = err.decode("utf-8", errors="replace").replace(workdir + "/", "")
    result = {
        "exit_code": process.returncode,
        "timed_out": timed_out,
        "duration_seconds": round(time.perf_counter() - started, 2),
        "stdout": _clip(stdout),
        "stderr": _clip(stderr),
    }
    if timed_out:
        result["stderr"] += f"\n[Stopped: the program ran longer than {TIMEOUT_SECONDS} seconds]"
    elif process.returncode == -signal.SIGXCPU:
        result["stderr"] += f"\n[Stopped: the program used more than {CPU_SECONDS} seconds of CPU time]"

    logger.info(
        "← exit_code=%s timed_out=%s %.2fs\n   stdout:%s\n   stderr:%s",
        result["exit_code"], timed_out, result["duration_seconds"], _block(stdout), _block(result["stderr"]),
    )
    return result


if __name__ == "__main__":
    logger.info("Code Runner MCP server on http://localhost:%d/mcp (python: %s)", PORT, PYTHON_BIN)
    if SANDBOX_EXEC is None:
        logger.warning("sandbox-exec not found: run_python will refuse to run code")
    mcp.run(transport="streamable-http", host="127.0.0.1", port=PORT)
