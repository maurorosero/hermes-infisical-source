"""Infisical secret source plugin for Hermes Agent.

Pulls provider credentials from an Infisical project folder at process
startup using Universal Auth (Client ID + Client Secret). This is a
**bulk** source: it injects the whole configured folder (e.g. ``/ALAN-AI``)
implicitly, like Bitwarden BSM.

Design
------
* The bootstrap credential is the Client Secret, held in ``~/.hermes/.env``
  as ``INFISICAL_CLIENT_SECRET`` (never in this file). The Client ID is
  non-sensitive and can live in config or env.
* ``fetch()`` performs a Universal Auth login against the Infisical API to
  obtain a short-lived access token, then shells out to the ``infisical``
  CLI (via the shared ``run_secret_cli`` helper) to export the folder as
  dotenv, and parses it into a ``{ENV_VAR: value}`` map.
* The orchestrator owns precedence, conflict handling, ``override_existing``,
  timeouts, provenance labels, and the actual ``os.environ`` writes. This
  source only *fetches* — it never touches the environment directly.
* Failures NEVER block startup: any error is returned as a ``FetchResult``
  with ``error`` + ``error_kind`` set.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import time
import urllib.error
import urllib.request
from pathlib import Path

from agent.secret_sources._cache import (
    CachedFetch,
    DiskCache,
)

# Imports compatibles con la migración post-2026-09-14:
# - base expone la superficie pública (FetchResult, is_valid_env_name, ErrorKind,
#   SecretSource, run_secret_cli, get_source_environment) — en el core actual y
#   en el migrado. Importar de base NO genera hits de compat (base no es facade).
# - CachedFetch/DiskCache viven en _cache (su hogar histórico; no figuran en el
#   manifest de migración, así que importarlos de ahí NO marca deprecación).
from agent.secret_sources.base import (
    ErrorKind,
    FetchResult,
    SecretSource,
    get_source_environment,
    is_valid_env_name,
    run_secret_cli,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------

# Infisical Cloud API base. Self-hosted instances use their own host.
_DEFAULT_API_URL = "https://app.infisical.com"

# Default env vars holding the Universal Auth bootstrap credentials.
_DEFAULT_CLIENT_ID_ENV = "INFISICAL_CLIENT_ID"
_DEFAULT_CLIENT_SECRET_ENV = "INFISICAL_CLIENT_SECRET"

# El proyecto, el entorno y la ruta pueden vivir en el .env del scope administrado:
# así cada perfil sólo declara `enabled: true` y todo lo demás se resuelve en un
# único lugar (/etc/hermes), sin replicar identificadores en cada config.yaml.
_SCOPE_PROJECT_ID_ENV = "INFISICAL_PROJECT_ID"
_SCOPE_ENV_ENV = "INFISICAL_ENV"
_SCOPE_PATH_ENV = "INFISICAL_PATH"


def _managed_env() -> dict[str, str]:
    """El ``.env`` del scope administrado (``/etc/hermes/.env``), o ``{}`` si no hay.

    Por qué se lee acá en vez de esperar al loader: ``load_hermes_dotenv`` resuelve las
    fuentes externas **antes** de cargar el ``.env`` gestionado, así que el bootstrap que
    vive ahí —la única copia en la máquina— todavía no está en el entorno cuando este
    source se autentica. Medido: el proceso del perfil tenía
    ``INFISICAL_CLIENT_SECRET`` pero el source ya había fallado. Sin esto, un perfil cuyo
    ``.env`` no lleva el bootstrap queda sin secretos aunque el scope exista y se lea.
    """
    try:
        from hermes_cli.managed_scope import load_managed_env

        return dict(load_managed_env() or {})
    except Exception:  # noqa: BLE001 - fail-open, igual que el propio loader
        return {}


# How long to wait for a single `infisical export` call.
_EXPORT_TIMEOUT = 30

# Env vars the `infisical` child process needs. Minimal allowlist — never
# the full post-dotenv os.environ (which holds every credential Hermes knows).
_INFISICAL_ENV_ALLOWLIST = (
    "PATH",
    "HOME",
    "USERPROFILE",
    "SYSTEMROOT",
    "TMPDIR",
    "TEMP",
    "LANG",
    "LC_ALL",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
)

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

# In-process cache keyed by (auth_fp, project, env, path, refs_fp).
_CacheKey = tuple[str, str, str, str, str]
_CACHE: dict[_CacheKey, CachedFetch] = {}

_DISK_CACHE_BASENAME = "infisical_cache.json"


def _disk_key_str(cache_key: _CacheKey) -> str:
    auth_fp, project, env, path, refs_fp = cache_key
    return f"{auth_fp}|{project}|{env}|{path}|{refs_fp}"


_DISK_CACHE: DiskCache = DiskCache(_DISK_CACHE_BASENAME, key_serializer=_disk_key_str)


def _auth_fingerprint(client_id: str, client_secret: str) -> str:
    """SHA-256 prefix over the auth material, so a rotated secret never
    serves values cached under the old credential."""
    material = f"id={client_id}\nsecret={client_secret}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Universal Auth login (HTTP)
# ---------------------------------------------------------------------------


def _universal_auth_login(
    client_id: str,
    client_secret: str,
    api_url: str = _DEFAULT_API_URL,
    timeout: float = 30,
) -> str:
    """Exchange Client ID + Client Secret for a short-lived access token.

    Raises RuntimeError on any failure (network, bad credentials, malformed
    response). The token is returned as a string.
    """
    url = f"{api_url.rstrip('/')}/api/v1/auth/universal-auth/login"
    body = json.dumps({"clientId": client_id, "clientSecret": client_secret}).encode(
        "utf-8"
    )
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"Infisical login failed (HTTP {exc.code}): {exc.reason}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Infisical login network error: {exc.reason}") from exc
    except (TimeoutError, OSError) as exc:
        raise RuntimeError(f"Infisical login failed: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("Infisical login returned malformed JSON") from exc

    token = payload.get("accessToken") if isinstance(payload, dict) else None
    if not isinstance(token, str) or not token:
        raise RuntimeError("Infisical login returned no accessToken")
    return token


# ---------------------------------------------------------------------------
# Export via CLI
# ---------------------------------------------------------------------------


def _find_infisical(binary_path: str = "") -> Path | None:
    """Resolve a usable ``infisical`` binary, or None."""
    if binary_path:
        pinned = Path(binary_path)
        if pinned.exists() and os.access(pinned, os.X_OK):
            return pinned
        return None
    found = shutil.which("infisical")
    return Path(found) if found else None


def _export_folder(
    infisical: Path,
    access_token: str,
    *,
    project_id: str,
    env: str,
    path: str,
    api_url: str = _DEFAULT_API_URL,
) -> str:
    """Run ``infisical export`` for the folder and return raw dotenv text.

    Raises RuntimeError on any failure.
    """
    cmd: list[str] = [
        str(infisical),
        "export",
        "--projectId",
        project_id,
        "--env",
        env,
        "--format",
        "dotenv",
        "--token",
        access_token,
    ]
    if path:
        cmd += ["--path", path]

    # Minimal allowlisted child env; the token is passed as an argv flag by
    # the CLI itself, not via the environment.
    child_env: dict[str, str] = {}
    source_env = get_source_environment()
    for key in _INFISICAL_ENV_ALLOWLIST:
        val = source_env.get(key)
        if val is not None:
            child_env[key] = val
    child_env["NO_COLOR"] = "1"

    try:
        proc = run_secret_cli(
            cmd,
            extra_env=child_env,
            timeout=_EXPORT_TIMEOUT,
        )
    except RuntimeError as exc:
        raise RuntimeError(f"infisical export failed: {exc}") from exc

    if proc.returncode != 0:
        err = (proc.stderr or "").strip()[:300]
        raise RuntimeError(f"infisical export exited {proc.returncode}: {err}")
    return proc.stdout or ""


def _parse_dotenv(text: str) -> dict[str, str]:
    """Parse a dotenv blob into a {ENV_VAR: value} map.

    Handles ``KEY=value`` lines, optional surrounding quotes, and skips
    comments/blank lines. Values that are empty or whitespace-only are
    dropped (applying them would clobber a good credential with nothing).
    """
    secrets: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if not is_valid_env_name(key):
            continue
        # Strip matching surrounding quotes.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if not value.strip():
            continue
        secrets[key] = value
    return secrets


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------


def fetch_infisical_secrets(
    *,
    client_id: str,
    client_secret: str,
    project_id: str,
    env: str,
    path: str,
    api_url: str = _DEFAULT_API_URL,
    binary: Path | None = None,
    binary_path: str = "",
    use_cache: bool = True,
    cache_ttl_seconds: float = 300,
    home_path: Path | None = None,
) -> tuple[dict[str, str], list[str]]:
    """Resolve the folder's secrets to ``(secrets, warnings)``.

    Raises RuntimeError only when no ``infisical`` binary is available (a
    fatal "can't fetch anything" condition). Other failures are collected as
    warnings and the fetch returns empty.
    """
    warnings: list[str] = []
    cache_key: _CacheKey = (
        _auth_fingerprint(client_id, client_secret),
        project_id,
        env,
        path,
        "folder",
    )

    if use_cache:
        cached = _CACHE.get(cache_key)
        if cached and cached.is_fresh(cache_ttl_seconds):
            return dict(cached.secrets), warnings
        disk_cached = _DISK_CACHE.read(cache_key, cache_ttl_seconds, home_path)
        if disk_cached is not None:
            _CACHE[cache_key] = disk_cached
            return dict(disk_cached.secrets), warnings

    infisical = binary or _find_infisical(binary_path)
    if infisical is None:
        raise RuntimeError(
            "infisical CLI not found. Install it "
            "(https://infisical.com/docs/cli/overview) or set "
            "secrets.infisical.binary_path to its absolute location."
        )

    try:
        access_token = _universal_auth_login(client_id, client_secret, api_url=api_url)
    except RuntimeError as exc:
        warnings.append(str(exc))
        return {}, warnings

    try:
        dotenv_text = _export_folder(
            infisical,
            access_token,
            project_id=project_id,
            env=env,
            path=path,
            api_url=api_url,
        )
    except RuntimeError as exc:
        warnings.append(str(exc))
        return {}, warnings

    secrets = _parse_dotenv(dotenv_text)

    if use_cache and secrets:
        entry = CachedFetch(secrets=dict(secrets), fetched_at=time.time())
        _CACHE[cache_key] = entry
        _DISK_CACHE.write(cache_key, entry, cache_ttl_seconds, home_path)

    return secrets, warnings


# ---------------------------------------------------------------------------
# SecretSource adapter
# ---------------------------------------------------------------------------


class InfisicalSource(SecretSource):
    """Infisical as a registered secret source (bulk folder injection)."""

    name = "infisical"
    label = "Infisical"
    shape = "bulk"
    # Declarados para quedar igual que los sources oficiales (1Password, Bitwarden) y
    # que el core pueda leerlos sin ejecutar código: `scheme` es lo que usa el registry
    # para detectar que dos fuentes no reclamen el mismo esquema, y `token_env_key` /
    # `default_token_env` dicen cuál es el token de la propia bóveda. La protección ya
    # la hace `protected_env_vars()` más abajo; esto la hace visible al registro.
    scheme = "infisical"
    token_env_key = "client_secret_env"
    default_token_env = _DEFAULT_CLIENT_SECRET_ENV

    def override_existing(self, cfg: dict) -> bool:
        # Default True: a central vault is the rotation authority, so its
        # values should win over stale .env lines (same rationale as
        # Bitwarden/1Password).
        return bool(isinstance(cfg, dict) and cfg.get("override_existing", True))

    def protected_env_vars(self, cfg: dict):
        client_secret_env = _DEFAULT_CLIENT_SECRET_ENV
        if isinstance(cfg, dict):
            client_secret_env = str(cfg.get("client_secret_env") or client_secret_env)
        return frozenset({client_secret_env})

    def config_schema(self) -> dict:
        return {
            "enabled": {"description": "Master switch", "default": False},
            "project_id": {
                "description": "Infisical project ID",
                "default": "",
            },
            "env": {
                "description": "Environment to export (prod, dev, ...)",
                "default": "prod",
            },
            "path": {
                "description": "Folder path to export (e.g. /ALAN-AI)",
                "default": "/",
            },
            "api_url": {
                "description": "Infisical API base URL",
                "default": _DEFAULT_API_URL,
            },
            "client_id_env": {
                "description": "Env var holding the Client ID",
                "default": _DEFAULT_CLIENT_ID_ENV,
            },
            "client_secret_env": {
                "description": "Env var holding the Client Secret (bootstrap)",
                "default": _DEFAULT_CLIENT_SECRET_ENV,
            },
            "binary_path": {
                "description": "Pin the infisical binary (empty = resolve via PATH)",
                "default": "",
            },
            "cache_ttl_seconds": {
                "description": "Disk+memory cache TTL; 0 disables",
                "default": 300,
            },
            "override_existing": {
                "description": "Resolved values overwrite .env/shell values",
                "default": True,
            },
        }

    def fetch(self, cfg: dict, home_path: Path) -> FetchResult:
        cfg = cfg if isinstance(cfg, dict) else {}
        result = FetchResult()

        # El scope administrado es la fuente única: un perfil puede declarar sólo
        # `enabled: true` y el proyecto, el entorno y la ruta se leen de /etc/hermes.
        managed: dict[str, str] | None = None

        def _scoped(*keys: str) -> str:
            nonlocal managed
            if managed is None:
                managed = _managed_env()
            for key in keys:
                value = str(managed.get(key, "") or "").strip()
                if value:
                    return value
            return ""

        project_id = str(cfg.get("project_id") or "").strip() or _scoped(
            _SCOPE_PROJECT_ID_ENV
        )
        if not project_id:
            result.error = (
                "secrets.infisical.enabled is true but project_id is not set. "
                "Set secrets.infisical.project_id in config.yaml or "
                f"{_SCOPE_PROJECT_ID_ENV} in the managed .env."
            )
            result.error_kind = ErrorKind.NOT_CONFIGURED
            return result

        env = str(cfg.get("env") or "").strip() or _scoped(_SCOPE_ENV_ENV) or "prod"
        path = str(cfg.get("path") or "").strip() or _scoped(_SCOPE_PATH_ENV) or "/"
        api_url = str(cfg.get("api_url") or _DEFAULT_API_URL).strip()

        client_id_env = str(cfg.get("client_id_env") or _DEFAULT_CLIENT_ID_ENV)
        client_secret_env = str(
            cfg.get("client_secret_env") or _DEFAULT_CLIENT_SECRET_ENV
        )

        source_env = get_source_environment()
        client_id = source_env.get(client_id_env, "").strip()
        client_secret = source_env.get(client_secret_env, "").strip()

        # El bootstrap puede vivir sólo en el .env del scope administrado, que el loader
        # carga DESPUÉS de resolver este source. Se lee directo de ahí: es la única copia
        # en la máquina y evita repetirla en el .env de cada perfil.
        if not client_id or not client_secret:
            managed = _managed_env()
            client_id = client_id or managed.get(client_id_env, "").strip()
            client_secret = client_secret or managed.get(client_secret_env, "").strip()

        if not client_id or not client_secret:
            result.error = (
                f"secrets.infisical.enabled is true but {client_id_env} and/or "
                f"{client_secret_env} are not set in the environment."
            )
            result.error_kind = ErrorKind.NOT_CONFIGURED
            return result

        binary_path = str(cfg.get("binary_path") or "")
        binary = _find_infisical(binary_path)
        result.binary_path = binary
        if binary is None:
            if binary_path:
                result.error = (
                    f"secrets.infisical.binary_path ({binary_path!r}) is not "
                    "an executable infisical binary."
                )
            else:
                result.error = (
                    "secrets.infisical.enabled is true but the infisical CLI "
                    "was not found on PATH. Install it "
                    "(https://infisical.com/docs/cli/overview) or set "
                    "secrets.infisical.binary_path."
                )
            result.error_kind = ErrorKind.BINARY_MISSING
            return result

        try:
            ttl = float(cfg.get("cache_ttl_seconds", 300))
        except (TypeError, ValueError):
            ttl = 300.0

        try:
            secrets, fetch_warnings = fetch_infisical_secrets(
                client_id=client_id,
                client_secret=client_secret,
                project_id=project_id,
                env=env,
                path=path,
                api_url=api_url,
                binary=binary,
                cache_ttl_seconds=ttl,
                home_path=home_path,
            )
        except RuntimeError as exc:
            result.error = str(exc)
            result.error_kind = _classify_error(str(exc))
            return result

        result.secrets = secrets
        result.warnings.extend(fetch_warnings)
        return result

    def remediation(self, kind, cfg: dict) -> str:
        if kind in (ErrorKind.AUTH_FAILED, ErrorKind.AUTH_EXPIRED):
            return (
                "Infisical credentials rejected — run `hermes secrets "
                "infisical setup` to re-authenticate, or refresh the Client "
                "Secret in the Infisical console."
            )
        if kind == ErrorKind.BINARY_MISSING:
            return (
                "Install the Infisical CLI "
                "(https://infisical.com/docs/cli/overview) or set "
                "secrets.infisical.binary_path."
            )
        return super().remediation(kind, cfg)


def _classify_error(message: str) -> ErrorKind:
    """Best-effort mapping of failure text onto the shared taxonomy."""
    lowered = message.lower()
    if "timed out" in lowered:
        return ErrorKind.TIMEOUT
    if (
        "not found on path" in lowered
        or "not an executable" in lowered
        or "failed to invoke" in lowered
    ):
        return ErrorKind.BINARY_MISSING
    if any(
        tok in lowered
        for tok in (
            "unauthorized",
            "not signed in",
            "session expired",
            "authentication",
            "401",
            "403",
            "invalid client",
        )
    ):
        return ErrorKind.AUTH_FAILED
    if "empty value" in lowered:
        return ErrorKind.EMPTY_VALUE
    if any(
        tok in lowered
        for tok in ("network", "connection", "resolve host", "dns", "urlopen")
    ):
        return ErrorKind.NETWORK
    return ErrorKind.INTERNAL


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(ctx):
    # El registro del SECRET SOURCE no vive acá: lo hace el core. Este repo se instala
    # junto con un patch que agrega `InfisicalSource` a `_BUILTIN_SOURCES`, porque un
    # plugin se carga DESPUÉS de que Hermes valida credenciales (el doctor mira en la
    # sección 7, los plugins cargan en la 18) y sus secretos no llegarían a tiempo.
    # Acá queda sólo lo que el patch no puede dar: los comandos del CLI.
    #
    # CLI helpers (hermes infisical setup|status). Import local: cli.py importa
    # símbolos de este módulo; diferir evita el ciclo de import en el loader.
    from .cli import infisical_command, register_cli

    ctx.register_cli_command(
        name="infisical",
        help="Infisical secret-source setup & diagnostics",
        setup_fn=register_cli,
        handler_fn=infisical_command,
        description=(
            "Setup and diagnostics for the Infisical secret source: "
            "validate credentials (Universal Auth), write secrets.infisical "
            "to config.yaml, and probe the configured login."
        ),
    )
