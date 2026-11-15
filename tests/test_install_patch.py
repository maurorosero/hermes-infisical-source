"""El contrato de `install.sh`: aplica las dos piezas y correrlo dos veces no escribe un byte.

Se prueba contra un HERMES_HOME falso, no contra el árbol real: el script no se toca, y lo
que se comprueba es lo que hace —derivar el source, insertar la entrada y no repetirse—.
"""

from __future__ import annotations

import hashlib
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = REPO / "install.sh"

# Un registry mínimo que imita al del core en lo que el script mira: la tupla de fuentes
# incluidas y cómo se reporta su origen. No importa el source, así que basta para que el
# paso de verificación del script tenga algo real contra qué correr.
REGISTRY = """\
_BUILTIN_SOURCES = (
    ("agent.secret_sources.command", "CommandSource", "command"),
)
_SOURCE_ORIGINS: dict = {}


def list_sources():
    out = []
    for mod, _cls, _label in _BUILTIN_SOURCES:
        nombre = mod.rsplit(".", 1)[-1]
        _SOURCE_ORIGINS.setdefault(nombre, "builtin")
        out.append(type("S", (), {"name": nombre})())
    return out
"""


def _home(tmp_path: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    """Un HERMES_HOME con el árbol de Hermes, el plugin y su entrada en config.yaml."""
    home = tmp_path / "hermes"
    sources = home / "hermes-agent" / "agent" / "secret_sources"
    sources.mkdir(parents=True)
    (home / "hermes-agent" / "agent" / "__init__.py").write_text("")
    (sources / "__init__.py").write_text("")
    (sources / "registry.py").write_text(REGISTRY)
    (home / "plugins" / "infisical").mkdir(parents=True)
    (home / "plugins" / "infisical" / "plugin.yaml").write_text("name: infisical\n")
    # el paso 1 mira disco y config: así no intenta instalar nada por red
    (home / "config.yaml").write_text("plugins:\n  enabled:\n    - infisical\n")
    return home, sources


def _run(home: pathlib.Path, *args: str) -> subprocess.CompletedProcess:
    entorno = {
        "HOME": str(home),
        "HERMES_HOME": str(home),
        "PYTHON": sys.executable,
        "PATH": "/usr/local/bin:/usr/bin:/bin",
    }
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        env=entorno,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def _sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_check_con_el_arbol_vacio_sale_1(tmp_path):
    home, sources = _home(tmp_path)

    r = _run(home, "--check")

    assert r.returncode == 1, r.stdout + r.stderr
    assert not (sources / "infisical.py").exists(), "--check no debe escribir"
    assert "infisical" not in (sources / "registry.py").read_text(), (
        "--check no debe escribir"
    )


def test_aplicar_pone_las_dos_piezas_y_el_check_pasa(tmp_path):
    home, sources = _home(tmp_path)

    r = _run(home)
    assert r.returncode == 0, r.stdout + r.stderr

    source = sources / "infisical.py"
    assert source.is_file(), "el source tiene que quedar en el árbol"
    assert "class InfisicalSource" in source.read_text(), (
        "y ser el source, no otra cosa"
    )
    assert "def register(" not in source.read_text(), "sin el register del plugin"
    assert "agent.secret_sources.infisical" in (sources / "registry.py").read_text()

    r = _run(home, "--check")
    assert r.returncode == 0, r.stdout + r.stderr


def test_es_idempotente_dos_corridas_no_escriben(tmp_path):
    home, sources = _home(tmp_path)
    assert _run(home).returncode == 0

    antes = (_sha(sources / "infisical.py"), _sha(sources / "registry.py"))
    r = _run(home)

    assert r.returncode == 0, r.stdout + r.stderr
    assert (_sha(sources / "infisical.py"), _sha(sources / "registry.py")) == antes
    assert "escrito" not in r.stdout, "la segunda corrida no debe decir que escribió"


def test_no_duplica_la_entrada_si_ya_esta(tmp_path):
    home, sources = _home(tmp_path)
    assert _run(home).returncode == 0

    texto = (sources / "registry.py").read_text()

    assert texto.count("agent.secret_sources.infisical") == 1


def test_revert_saca_el_patch_y_deja_el_plugin(tmp_path):
    home, sources = _home(tmp_path)
    assert _run(home).returncode == 0

    r = _run(home, "--revert")

    assert r.returncode == 0, r.stdout + r.stderr
    assert not (sources / "infisical.py").exists()
    assert "agent.secret_sources.infisical" not in (sources / "registry.py").read_text()
    assert (home / "plugins" / "infisical" / "plugin.yaml").is_file(), (
        "el plugin no se toca"
    )
