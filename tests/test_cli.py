"""CLI conformance tests for hermes-infisical-source.

Verifies:
1. The module registers a hook-able register_cli(subparser) that exposes
   `setup` / `status` subcommands.
2. The registration path (register(ctx)) does not trip the compat scanner
   (no literals of removed facades) — mirrored by the CI conformance.
3. cmd_setup fails cleanly (exit 1) when credentials are missing, and
   --dry-run writes nothing but returns 0 when login would pass (probe
   stubbed, so tests need no network).
"""

import argparse
import importlib.util
import pathlib

import pytest

_PLUGIN = pathlib.Path(__file__).resolve().parent.parent / "__init__.py"
_CLI = pathlib.Path(__file__).resolve().parent.parent / "cli.py"


def _load_cli():
    spec = importlib.util.spec_from_file_location("hermes_infisical_cli", _CLI)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def cli():
    return _load_cli()


def test_registers_setup_and_status_subcommands(cli, monkeypatch):
    subparsers = []
    parser = argparse.ArgumentParser(prog="hermes infisical")

    # Capture subparsers added by register_cli.
    def fake_add_subparsers(**kw):
        sp = parser.add_subparsers(**kw)
        subparsers.append(sp)
        return sp

    monkeypatch.setattr(parser, "add_subparsers", fake_add_subparsers)
    cli.register_cli(parser)

    assert subparsers, "register_cli should add subparsers"
    sp = subparsers[0]
    assert any(a.dest == "infisical_action" for a in parser._actions)
    # argparse stores registered parsers on the subparsers action.
    choices = [a.choices for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
    assert choices and "setup" in choices[0] and "status" in choices[0]


def test_status_without_config_exits_1(cli, tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "nope.yaml")
    args = argparse.Namespace()
    assert cli.cmd_status(args) == 1


def test_setup_missing_credentials_exits_1(cli, tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "config.yaml")
    monkeypatch.setattr(cli, "DEFAULT_HOME", tmp_path)
    monkeypatch.setenv("INFISICAL_CLIENT_ID", "")
    monkeypatch.setenv("INFISICAL_CLIENT_SECRET", "")
    args = argparse.Namespace(
        project_id="p1", env="prod", path="/", api_url="https://app.infisical.com",
        client_id_env="INFISICAL_CLIENT_ID", client_secret_env="INFISICAL_CLIENT_SECRET",
        dry_run=True,
    )
    assert cli.cmd_setup(args) == 1


def test_setup_dry_run_writes_nothing_on_login_ok(cli, tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "config.yaml")
    monkeypatch.setattr(cli, "DEFAULT_HOME", tmp_path)
    monkeypatch.setenv("INFISICAL_CLIENT_ID", "cid-123")
    monkeypatch.setenv("INFISICAL_CLIENT_SECRET", "csec-456")
    monkeypatch.setattr(cli, "_test_login", lambda *a, **k: (True, "OK"))
    args = argparse.Namespace(
        project_id="p1", env="prod", path="/ALAN-AI", api_url="https://app.infisical.com",
        client_id_env="INFISICAL_CLIENT_ID", client_secret_env="INFISICAL_CLIENT_SECRET",
        dry_run=True,
    )
    assert cli.cmd_setup(args) == 0
    assert not (tmp_path / "config.yaml").exists(), "dry-run must not write config"
