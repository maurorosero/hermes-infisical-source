"""El bootstrap del scope administrado, que el loader aplica demasiado tarde.

`load_hermes_dotenv` resuelve las fuentes externas ANTES de cargar `/etc/hermes/.env`,
así que el bootstrap que vive ahí no está en el entorno cuando el source se autentica.
Medido en un perfil real: tenía `INFISICAL_CLIENT_SECRET` y el source ya había fallado.
Estos tests fijan las dos mitades: leerlo del scope, y no pisar lo que ya venga del entorno.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]


def _cargar_plugin():
    """Importa el plugin como módulo suelto (no está instalado en el camino de tests)."""
    nombre = "infisical_plugin_bajo_test"
    if nombre in sys.modules:
        return sys.modules[nombre]
    spec = importlib.util.spec_from_file_location(nombre, REPO / "__init__.py")
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[nombre] = modulo
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture
def managed(tmp_path, monkeypatch):
    """Un scope administrado de mentira, con el bootstrap adentro."""
    scope = tmp_path / "etc-hermes"
    scope.mkdir()
    (scope / ".env").write_text(
        "INFISICAL_CLIENT_ID=id-de-prueba\nINFISICAL_CLIENT_SECRET=secreto-de-prueba\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_MANAGED_DIR", str(scope))
    from hermes_cli import managed_scope

    managed_scope.invalidate_managed_cache()
    yield scope
    monkeypatch.delenv("HERMES_MANAGED_DIR", raising=False)
    managed_scope.invalidate_managed_cache()


def test_managed_env_lee_el_scope(managed):
    plugin = _cargar_plugin()

    valores = plugin._managed_env()

    assert valores.get("INFISICAL_CLIENT_ID") == "id-de-prueba"
    assert valores.get("INFISICAL_CLIENT_SECRET") == "secreto-de-prueba"


def test_managed_env_sin_scope_devuelve_vacio(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_MANAGED_DIR", str(tmp_path / "no-existe"))
    from hermes_cli import managed_scope

    managed_scope.invalidate_managed_cache()
    plugin = _cargar_plugin()

    assert plugin._managed_env() == {}


def test_fetch_usa_el_scope_cuando_el_entorno_no_tiene_el_bootstrap(
    managed, tmp_path, monkeypatch
):
    """Sin bootstrap en el entorno, el source igual pasa el chequeo de credenciales."""
    monkeypatch.delenv("INFISICAL_CLIENT_ID", raising=False)
    monkeypatch.delenv("INFISICAL_CLIENT_SECRET", raising=False)
    plugin = _cargar_plugin()

    resultado = plugin.InfisicalSource().fetch(
        {"project_id": "e9db622a-8557-4c07-9ebe-d24b759429e0"}, tmp_path / "home"
    )

    # No hay binario `infisical` en el entorno de test: el error esperado es ese, no
    # NOT_CONFIGURED. Es decir, las credenciales se encontraron en el scope.
    assert resultado.error_kind != plugin.ErrorKind.NOT_CONFIGURED, resultado.error


def test_fetch_no_toca_el_scope_si_config_y_entorno_ya_resuelven(
    managed, tmp_path, monkeypatch
):
    """Si la config trae el proyecto y el entorno el bootstrap, el scope no se consulta."""
    monkeypatch.setenv("INFISICAL_CLIENT_ID", "del-entorno")
    monkeypatch.setenv("INFISICAL_CLIENT_SECRET", "secreto-del-entorno")
    plugin = _cargar_plugin()

    llamados = []
    original = plugin._managed_env
    monkeypatch.setattr(
        plugin, "_managed_env", lambda: llamados.append(1) or original()
    )

    plugin.InfisicalSource().fetch(
        {
            "project_id": "e9db622a-8557-4c07-9ebe-d24b759429e0",
            "env": "prod",
            "path": "/",
        },
        tmp_path / "home",
    )

    assert llamados == [], (
        "no debe leer el scope si la config y el entorno ya resolvieron todo"
    )


def test_fetch_sin_bootstrap_en_ningun_lado_sigue_fallando(tmp_path, monkeypatch):
    """Sin scope y sin entorno, el error tiene que seguir siendo explícito."""
    monkeypatch.setenv("HERMES_MANAGED_DIR", str(tmp_path / "no-existe"))
    monkeypatch.delenv("INFISICAL_CLIENT_ID", raising=False)
    monkeypatch.delenv("INFISICAL_CLIENT_SECRET", raising=False)
    from hermes_cli import managed_scope

    managed_scope.invalidate_managed_cache()
    plugin = _cargar_plugin()

    resultado = plugin.InfisicalSource().fetch(
        {"project_id": "e9db622a-8557-4c07-9ebe-d24b759429e0"}, tmp_path / "home"
    )

    assert resultado.error_kind == plugin.ErrorKind.NOT_CONFIGURED
    assert "INFISICAL_CLIENT_SECRET" in (resultado.error or "")


# --- el proyecto, el entorno y la ruta también pueden vivir en el scope ------------------
#
# Así un perfil sólo declara `secrets.infisical.enabled: true` y no replica ni una
# credencial ni un identificador: todo lo demás se resuelve en /etc/hermes.


@pytest.fixture
def scope_con_proyecto(tmp_path, monkeypatch):
    """Un scope que declara el proyecto, el entorno y la ruta."""
    scope = tmp_path / "etc-hermes-proyecto"
    scope.mkdir()
    (scope / ".env").write_text(
        "INFISICAL_CLIENT_ID=id-de-prueba\n"
        "INFISICAL_CLIENT_SECRET=secreto-de-prueba\n"
        "INFISICAL_PROJECT_ID=proyecto-del-scope\n"
        "INFISICAL_ENV=staging\n"
        "INFISICAL_PATH=/DESDE-EL-SCOPE\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_MANAGED_DIR", str(scope))
    from hermes_cli import managed_scope

    managed_scope.invalidate_managed_cache()
    yield scope
    monkeypatch.delenv("HERMES_MANAGED_DIR", raising=False)
    managed_scope.invalidate_managed_cache()


def test_fetch_toma_el_project_id_del_scope(scope_con_proyecto, tmp_path, monkeypatch):
    """Con sólo `enabled: true` en el perfil, el proyecto sale del scope."""
    monkeypatch.delenv("INFISICAL_CLIENT_ID", raising=False)
    monkeypatch.delenv("INFISICAL_CLIENT_SECRET", raising=False)
    plugin = _cargar_plugin()

    resultado = plugin.InfisicalSource().fetch({"enabled": True}, tmp_path / "home")

    assert resultado.error_kind != plugin.ErrorKind.NOT_CONFIGURED, resultado.error


def test_sin_project_id_en_ningun_lado_el_error_nombra_la_variable(
    tmp_path, monkeypatch
):
    """Si el scope tampoco lo declara, el error dice exactamente qué falta y dónde."""
    monkeypatch.setenv("HERMES_MANAGED_DIR", str(tmp_path / "no-existe"))
    monkeypatch.delenv("INFISICAL_CLIENT_ID", raising=False)
    monkeypatch.delenv("INFISICAL_CLIENT_SECRET", raising=False)
    from hermes_cli import managed_scope

    managed_scope.invalidate_managed_cache()
    plugin = _cargar_plugin()

    resultado = plugin.InfisicalSource().fetch({"enabled": True}, tmp_path / "home")

    assert resultado.error_kind == plugin.ErrorKind.NOT_CONFIGURED
    assert "INFISICAL_PROJECT_ID" in (resultado.error or "")
