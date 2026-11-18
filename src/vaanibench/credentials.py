"""Explicit local credential loading; no shell expansion or secret output."""
import os
from pathlib import Path
from .costs import ExecutionDenied


def load_api_key_file(path: Path) -> None:
    found: dict[str, list[str]] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line.startswith("export "):
            line = line[7:].lstrip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name, value = name.strip(), value.strip()
        if name not in {"OPENAI_API_KEY", "GROQ_API_KEY"}:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        found.setdefault(name, []).append(value)
    if any(len(values) != 1 or any(c.isspace() for c in values[0]) for values in found.values()):
        raise ExecutionDenied("env_file_invalid_api_key_entries")
    updates = {name: values[0] for name, values in found.items() if values[0]}
    if not updates:
        raise ExecutionDenied("env_file_requires_nonempty_api_key")
    os.environ.update(updates)
