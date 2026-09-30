"""Configuration file loader for AgentContract environment and settings."""

import os
import re
from pathlib import Path
from typing import Mapping


def _expand_value(val: str, current_env: Mapping[str, str]) -> str:
    """Expand environment variables in a configuration value.

    Supports:
    - $env:VAR_NAME (PowerShell syntax)
    - ${VAR_NAME} (Standard shell syntax)
    - $VAR_NAME (Simple shell syntax)
    """
    def replace_ps_env(match: re.Match[str]) -> str:
        var_name = match.group(1)
        return current_env.get(var_name, os.environ.get(var_name, ""))

    val = re.sub(r"\$env:([A-Za-z_][A-Za-z0-9_]*)", replace_ps_env, val)

    def replace_braced_env(match: re.Match[str]) -> str:
        var_name = match.group(1)
        return current_env.get(var_name, os.environ.get(var_name, ""))

    val = re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", replace_braced_env, val)

    def replace_simple_env(match: re.Match[str]) -> str:
        var_name = match.group(1)
        return current_env.get(var_name, os.environ.get(var_name, ""))

    val = re.sub(r"\$([A-Za-z_][A-Za-z0-9_]*)", replace_simple_env, val)

    return val


def parse_config_content(content: str, current_env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Parse configuration file content into a dictionary of key-value pairs."""
    env = dict(current_env or {})
    result: dict[str, str] = {}

    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # Strip optional leading "export "
        if line.startswith("export "):
            line = line[7:].strip()

        # Support lines starting with "$env:" like "$env:KEY = VALUE"
        if line.startswith("$env:"):
            line = line[5:].strip()

        if "=" not in line:
            continue

        key, raw_val = line.split("=", 1)
        key = key.strip()
        if key.startswith("$env:"):
            key = key[5:].strip()

        raw_val = raw_val.strip()

        # Strip outer matching quotes
        if (raw_val.startswith('"') and raw_val.endswith('"')) or (
            raw_val.startswith("'") and raw_val.endswith("'")
        ):
            raw_val = raw_val[1:-1]

        # Expand variables
        expanded_val = _expand_value(raw_val, {**os.environ, **env, **result})
        result[key] = expanded_val

    return result


def load_config(
    path: str | Path | None = None,
    *,
    override: bool = False,
    search_parents: bool = True,
) -> dict[str, str]:
    """Load configuration from a file (.env or specified path) into os.environ.

    Args:
        path: Path to the configuration file. If None, searches for .env or .agentcontract.env.
        override: If True, overwrite existing non-empty environment variables. Defaults to False.
        search_parents: If True, search parent directories if path is not specified.

    Returns:
        Dictionary of loaded key-value pairs.
    """
    if path is None and os.environ.get("AGENTCONTRACT_DISABLE_ENV_FILE") == "1":
        return {}

    config_path: Path | None = None

    if path is not None:
        target = Path(path)
        if target.is_file():
            config_path = target
        else:
            return {}
    else:
        env_config = os.environ.get("AGENTCONTRACT_CONFIG")
        if env_config:
            p = Path(env_config)
            if p.is_file():
                config_path = p

        if config_path is None:
            cwd = Path.cwd().resolve()
            candidates = [cwd]
            if search_parents:
                candidates.extend(cwd.parents)

            for directory in candidates:
                for filename in (".env", ".agentcontract.env", "agentcontract.env"):
                    p = directory / filename
                    if p.is_file():
                        config_path = p
                        break
                if config_path is not None:
                    break

    if config_path is None or not config_path.is_file():
        return {}

    try:
        content = config_path.read_text(encoding="utf-8")
    except Exception:
        return {}

    parsed = parse_config_content(content)

    for k, v in parsed.items():
        if override:
            os.environ[k] = v
        else:
            curr = os.environ.get(k)
            if curr is None or curr == "":
                if v != "":
                    os.environ[k] = v

    return parsed
