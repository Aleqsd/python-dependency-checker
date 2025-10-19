import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Tuple

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

EMOJI = {
    "start": "🧭",
    "scan": "🔍",
    "ok": "✅",
    "missing": "❌",
    "unused": "🪶",
    "failure": "🚨",
    "info": "ℹ️",
}

console = Console()


def resolve_project_path(raw_path: str) -> Path:
    """Resolve and validate the project path."""
    path = Path(raw_path).expanduser().resolve()
    if not path.exists():
        console.print(
            f"{EMOJI['failure']} [bold red]Path '{path}' does not exist.[/bold red]"
        )
        sys.exit(2)
    if not path.is_dir():
        console.print(
            f"{EMOJI['failure']} [bold red]Path '{path}' is not a directory.[/bold red]"
        )
        sys.exit(2)
    return path


def run_command(command: List[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Execute a command returning the completed process."""
    result = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
    )
    return result


def parse_deptry_report(stdout: str) -> Tuple[List[str], List[str]]:
    """Parse deptry JSON output and return lists of missing and unused modules."""
    if not stdout.strip():
        return [], []

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        console.print(
            f"{EMOJI['failure']} [bold red]Unable to parse deptry output as JSON:[/bold red] {exc}"
        )
        console.print(stdout)
        sys.exit(2)

    missing = [
        item.get("module") or item.get("name") or str(item)
        for item in data.get("missing", [])
    ]
    unused = [
        item.get("module") or item.get("name") or str(item)
        for item in data.get("unused", [])
    ]
    return missing, unused


def parse_pip_check_output(stdout: str) -> List[str]:
    """Extract dependency names from pip-check-reqs output."""
    modules: List[str] = []
    for line in stdout.splitlines():
        clean = line.strip()
        if not clean:
            continue
        lowered = clean.lower()
        if lowered.startswith(("examining ", "missing requirements", "unused requirements", "extra requirements")):
            continue
        if lowered.startswith(("configuration", "results", "to fix", "hint:", "warning")):
            continue
        if clean.startswith(("#", "=", "---")):
            continue
        if clean[0].isdigit() and ":" in clean:
            continue
        if clean.startswith(("- ", "* ")):
            clean = clean[2:]
        candidate = clean.split()[0].strip(",")
        if not candidate:
            continue
        allowed_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")
        if all(char in allowed_chars for char in candidate):
            modules.append(candidate)
    return sorted(set(modules))


def run_deptry(path: Path) -> Tuple[List[str], List[str]]:
    console.print(
        f"{EMOJI['scan']} [bold cyan]Running deptry analysis...[/bold cyan]"
    )
    result = run_command(["deptry", str(path), "--json"], cwd=path)
    if result.returncode not in (0, 1):
        console.print(f"{EMOJI['failure']} [bold red]deptry failed to execute.[/bold red]")
        if result.stderr:
            console.print(Panel.fit(result.stderr, title="deptry stderr", border_style="red"))
        sys.exit(result.returncode or 2)

    missing, unused = parse_deptry_report(result.stdout)
    return missing, unused


def select_requirements_file(path: Path) -> Path | None:
    """Pick a requirements file when available."""
    candidates = [
        path / "requirements.txt",
        path / "requirements-dev.txt",
        path / "requirements.in",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def run_pip_check_reqs(path: Path) -> Tuple[List[str], List[str], Dict[str, str]]:
    console.print(
        f"{EMOJI['scan']} [bold cyan]Running pip-check-reqs analysis...[/bold cyan]"
    )
    requirements = select_requirements_file(path)
    command_suffix: List[str] = []
    if requirements:
        command_suffix = ["--requirements-file", str(requirements)]

    missing_cmd = ["pip-missing-reqs", str(path)]
    extra_cmd = ["pip-extra-reqs", str(path)]
    if command_suffix:
        missing_cmd.extend(command_suffix)
        extra_cmd.extend(command_suffix)

    missing_result = run_command(missing_cmd, cwd=path)
    extra_result = run_command(extra_cmd, cwd=path)

    diagnostics: Dict[str, str] = {}
    if missing_result.stderr:
        diagnostics["pip-missing-reqs"] = missing_result.stderr
    if extra_result.stderr:
        diagnostics["pip-extra-reqs"] = extra_result.stderr

    if missing_result.returncode not in (0, 1) or extra_result.returncode not in (0, 1):
        console.print(
            f"{EMOJI['failure']} [bold red]pip-check-reqs commands exited with an unexpected status.[/bold red]"
        )
        for title, stderr in diagnostics.items():
            console.print(Panel.fit(stderr, title=f"{title} stderr", border_style="red"))
        sys.exit(missing_result.returncode or extra_result.returncode or 2)

    if missing_result.stdout.strip():
        console.print(
            Panel.fit(
                missing_result.stdout.strip(),
                title="pip-missing-reqs",
                border_style="cyan",
            )
        )
    if extra_result.stdout.strip():
        console.print(
            Panel.fit(
                extra_result.stdout.strip(),
                title="pip-extra-reqs",
                border_style="cyan",
            )
        )

    missing = parse_pip_check_output(missing_result.stdout)
    unused = parse_pip_check_output(extra_result.stdout)
    return missing, unused, diagnostics


def render_table(missing: List[str], unused: List[str]) -> None:
    """Display a summary table using Rich."""
    table = Table(title=f"{EMOJI['info']} Dependency Report", header_style="bold magenta")
    table.add_column("Status", justify="center", style="bold")
    table.add_column("Packages", overflow="fold")

    if missing:
        table.add_row(
            f"{EMOJI['missing']} Missing",
            ", ".join(sorted(missing)),
            style="bold red",
        )
    if unused:
        table.add_row(
            f"{EMOJI['unused']} Unused",
            ", ".join(sorted(unused)),
            style="yellow",
        )
    if not missing and not unused:
        table.add_row(f"{EMOJI['ok']} All good!", "No issues detected.", style="green")

    console.print(table)


def write_summary(missing: List[str], unused: List[str], mode: str) -> None:
    """Append a markdown summary to GITHUB_STEP_SUMMARY when available."""
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return

    lines = [
        f"## {EMOJI['info']} Python Dependency Checker ({mode})",
        "",
    ]
    if missing:
        lines.append(f"- {EMOJI['missing']} **Missing dependencies**: {', '.join(sorted(missing))}")
    if unused:
        lines.append(f"- {EMOJI['unused']} **Unused dependencies**: {', '.join(sorted(unused))}")
    if not missing and not unused:
        lines.append(f"- {EMOJI['ok']} All dependencies look good!")

    with open(summary_path, "a", encoding="utf-8") as summary_file:
        summary_file.write("\n".join(lines) + "\n")


def main() -> None:
    raw_path = os.getenv("INPUT_PATH", ".")
    mode = os.getenv("INPUT_MODE", "deptry").strip().lower()
    fail_on_warn_raw = (
        os.getenv("INPUT_FAIL_ON_WARN")
        or os.getenv("INPUT_FAIL-ON-WARN")
        or "false"
    )
    fail_on_warn = fail_on_warn_raw.strip().lower() == "true"

    console.print(
        f"{EMOJI['start']} [bold blue]Python Dependency Checker[/bold blue] started."
    )
    console.print(
        f"{EMOJI['info']} Checking [bold]{raw_path}[/bold] using [bold]{mode}[/bold] (fail-on-warn={fail_on_warn})."
    )

    project_path = resolve_project_path(raw_path)

    missing: List[str] = []
    unused: List[str] = []
    diagnostics: Dict[str, str] = {}

    if mode == "deptry":
        missing, unused = run_deptry(project_path)
    elif mode == "pip-check-reqs":
        missing, unused, diagnostics = run_pip_check_reqs(project_path)
    else:
        console.print(
            f"{EMOJI['failure']} [bold red]Unsupported mode '{mode}'. Use 'deptry' or 'pip-check-reqs'.[/bold red]"
        )
        sys.exit(2)

    render_table(missing, unused)
    write_summary(missing, unused, mode)

    if diagnostics:
        for title, stderr in diagnostics.items():
            console.print(Panel.fit(stderr, title=f"{title} stderr", border_style="yellow"))

    has_missing = bool(missing)
    has_unused = bool(unused)

    if has_missing or (has_unused and fail_on_warn):
        console.print(
            f"{EMOJI['failure']} [bold red]Dependency issues detected.[/bold red]"
        )
        sys.exit(1)

    if has_unused and not fail_on_warn:
        console.print(
            f"{EMOJI['unused']} [yellow]Unused dependencies detected (warnings only).[/yellow]"
        )

    console.print(
        f"{EMOJI['ok']} [bold green]All checks completed successfully.[/bold green]"
    )


if __name__ == "__main__":
    main()
