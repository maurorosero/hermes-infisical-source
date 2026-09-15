"""CLI commands for the hermes-infisical-source plugin.

Exposes ``hermes infisical setup`` (interactive wizard) and
``hermes infisical status`` (diagnostics). Registered via ``register(ctx)`` →
``ctx.register_cli_command`` (same mechanism as the bundled teams_pipeline
plugin). The wizard validates credentials against the Universal Auth login
endpoint BEFORE writing anything to config.yaml, so a bad Client Secret is
caught immediately instead of on the next gateway restart.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional, Tuple

import yaml

from . import (
    _DEFAULT_API_URL,
    _DEFAULT_CLIENT_ID_ENV,
    _DEFAULT_CLIENT_SECRET_ENV,
    _universal_auth_login,
)

DEFAULT_HOME = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")
CONFIG_PATH = DEFAULT_HOME / "config.yaml"


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------


def _read_config(config_path: Path = CONFIG_PATH) -> dict:
    if not config_path.exists():
        return {}
    try:
        with config_path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_config(config: dict, config_path: Path = CONFIG_PATH) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with config_path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(config, fh, sort_keys=False, allow_unicode=True)


def _current_section(config: dict) -> Optional[dict]:
    return config.get("secrets", {}).get("infisical") if isinstance(config.get("secrets"), dict) else None


def _locate_env(source: dict, key: str) -> str:
    """Resolve an env var against the source env view, or a .env file."""
    val = source.get(key, "")
    if val:
        return str(val).strip()
    # Fallback: read ~/.hermes/.env directly (bootstrap stage).
    env_file = DEFAULT_HOME / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            if k.strip() == key:
                return v.strip().strip("\"'")
    return ""


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def _test_login(client_id: str, client_secret: str, api_url: str) -> Tuple[bool, str]:
    """Probe Universal Auth. Returns (ok, detail). Never raises."""
    if not client_id or not client_secret:
        return False, "missing INFISICAL_CLIENT_ID / INFISICAL_CLIENT_SECRET in environment"
    try:
        _universal_auth_login(client_id, client_secret, api_url)
        return True, "Universal Auth login OK"
    except RuntimeError as exc:
        return False, str(exc)


def cmd_setup(args: argparse.Namespace) -> int:
    source = dict(os.environ)
    client_id_env = args.client_id_env or _DEFAULT_CLIENT_ID_ENV
    client_secret_env = args.client_secret_env or _DEFAULT_CLIENT_SECRET_ENV

    client_id = _locate_env(source, client_id_env)
    client_secret = _locate_env(source, client_secret_env)

    if not client_id or not client_secret:
        print(
            f"[infisical] {client_id_env} and/or {client_secret_env} are not set.\n"
            f"Add them to {DEFAULT_HOME / '.env'} first, then re-run this wizard."
        )
        return 1

    project_id = (args.project_id or "").strip()
    if not project_id:
        print("Missing --project-id (the Infisical project ID).")
        return 1

    env = (args.env or "prod").strip() or "prod"
    path = (args.path or "/").strip() or "/"
    api_url = (args.api_url or _DEFAULT_API_URL).strip()

    ok, detail = _test_login(client_id, client_secret, api_url)
    if not ok:
        print(f"[infisical] credentials rejected: {detail}")
        return 1

    if args.dry_run:
        print("[infisical] dry-run: config would be:")
        print(f"  secrets.infisical.enabled: true")
        print(f"  secrets.infisical.project_id: {project_id}")
        print(f"  secrets.infisical.env: {env}")
        print(f"  secrets.infisical.path: {path}")
        print(f"  secrets.infisical.client_id_env: {client_id_env}")
        print(f"  secrets.infisical.client_secret_env: {client_secret_env}")
        print("[infisical] login OK — nothing written (--dry-run)")
        return 0

    config = _read_config()
    config.setdefault("secrets", {})["infisical"] = {
        "enabled": True,
        "project_id": project_id,
        "env": env,
        "path": path,
        "client_id_env": client_id_env,
        "client_secret_env": client_secret_env,
    }
    _write_config(config)
    print(f"[infisical] wrote secrets.infisical to {CONFIG_PATH}")
    print("[infisical] done — restart the gateway to load the new secret source.")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    config = _read_config()
    section = _current_section(config)
    source = dict(os.environ)

    if not section or not section.get("enabled"):
        print("[infisical] status: NOT CONFIGURED (secrets.infisical.enabled is false or missing).")
        print("  Run: hermes infisical setup")

        return 1

    client_id_env = str(section.get("client_id_env") or _DEFAULT_CLIENT_ID_ENV)
    client_secret_env = str(section.get("client_secret_env") or _DEFAULT_CLIENT_SECRET_ENV)
    client_id = _locate_env(source, client_id_env)
    client_secret = _locate_env(source, client_secret_env)

    print("[infisical] status: CONFIGURED")
    print(f"  enabled:      {section.get('enabled')}")
    print(f"  project_id:   {section.get('project_id')}")
    print(f"  env:          {section.get('env')}")
    print(f"  path:         {section.get('path')}")
    print(f"  client_id_env: {client_id_env} -> {'set' if client_id else 'MISSING'}")
    print(f"  client_secret_env: {client_secret_env} -> {'set' if client_secret else 'MISSING'}")

    ok, detail = _test_login(client_id, client_secret, str(section.get("api_url") or _DEFAULT_API_URL))
    print(f"  login:        {'OK' if ok else 'FAILED — ' + detail}")
    return 0 if (ok and client_id and client_secret) else 1


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_cli(subparser: argparse.ArgumentParser) -> None:
    subs = subparser.add_subparsers(dest="infisical_action")

    p_setup = subs.add_parser("setup", help="Configure secrets.infisical and test the Universal Auth login")
    p_setup.add_argument("--project-id", help="Infisical project ID (hex string)")
    p_setup.add_argument("--env", default=None, help="Environment (prod/dev/...); default prod")
    p_setup.add_argument("--path", default=None, help="Folder to export (e.g. /ALAN-AI); default /")
    p_setup.add_argument("--api-url", default=None, help="Infisical API base URL (default https://app.infisical.com)")
    p_setup.add_argument("--client-id-env", default=None, help="Env var holding the Client ID")
    p_setup.add_argument("--client-secret-env", default=None, help="Env var holding the Client Secret")
    p_setup.add_argument("--dry-run", action="store_true", help="Validate and print the config without writing")

    subs.add_parser("status", help="Show configured state and probe the login")

    subparser.set_defaults(func=infisical_command)


def infisical_command(args: argparse.Namespace) -> int:
    action = getattr(args, "infisical_action", None)
    if not action:
        print("Usage: hermes infisical {setup|status}")
        return 2
    if action == "setup":
        return cmd_setup(args)
    if action == "status":
        return cmd_status(args)
    print(f"Unknown action: {action}")
    return 2


if __name__ == "__main__":  # pragma: no cover — local smoke-test entry
    parser = argparse.ArgumentParser(prog="hermes infisical")
    register_cli(parser)
    sys.exit(infisical_command(parser.parse_args()))
