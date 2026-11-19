# Changelog

Formato: [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/).
Versionado: [SemVer](https://semver.org/lang/es/).

La versión canónica es la de `plugin.yaml` (es la que lee Hermes); `pyproject.toml` la
repite para que el paquete y el plugin no se despeguen.

## [Unreleased]

## [1.0.0] — 2026-11-19

### Corregido

- **La documentación describía un plugin que inyecta secretos.** No es así: el `register()`
  sólo registra los comandos, y la fuente se instala en el árbol de Hermes porque el arranque
  valida credenciales antes de cargar plugins. Corregido en `README.md`, `plugin.yaml`,
  `pyproject.toml` y `AGENTS.md`.
- **«Sólo el plugin (sin el patch)» afirmaba que resuelve los secretos.** Sin patch no resuelve
  nada: da comandos y nada más. Un perfil con `enabled: true` y sin patch arranca sin
  credenciales.
- **La tabla de configuración documentaba tres claves que el source no acepta** (`folder`,
  `timeout`, `fail_open`) y omitía cinco de las diez reales. Ahora están las diez, con su
  default y de dónde sale cada valor.
- **`client_id_env` guarda el nombre de la variable, no el secreto.** Queda dicho en el README:
  el valor va en el `.env` del perfil o en el scope administrador.
- `__pycache__` no estaba en `.gitignore`.

### Cambiado

- Los ejemplos y la documentación usan marcadores (`<uuid-del-proyecto>`, `/<carpeta>`), no
  datos de una instalación concreta. Los tests usaban la carpeta real de un vault.
- `pyproject.toml` declara `1.0.0`, alineado con `plugin.yaml` (decía `0.1.1`).

### Añadido

- `CHANGELOG.md`.

## [0.1.x] — 2026-11-13 a 2026-11-15

Etapa previa a la 1.0.0, resumida del historial:

### Añadido

- Fuente de secretos `InfisicalSource` (bulk folder, Universal Auth, fail-open, cache con TTL).
- `hermes infisical setup` y `hermes infisical status`.
- `install.sh` con tres pasos idempotentes: instalar el plugin, derivar el source al árbol de
  Hermes, y registrar la entrada en `_BUILTIN_SOURCES`.
- Patch al core: un plugin se carga después de que Hermes valide credenciales, así que la
  fuente no llega a tiempo desde el plugin.
- Gate de secretos con `pre-commit` + `gitleaks` sobre el rango de commits.
- Shellcheck como linter de los scripts de shell.

### Corregido

- `install.sh --revert` no revertía nada; `--check` dependía del CLI y no encontraba `hermes`.
- `PyYAML` declarada como requisito, con el motivo: sin ella el plugin muere al cargar y el
  error que se ve habla de otra cosa.

### Nota

El patch **no sobrevive a `hermes update`**: el actualizador hace `stash push` y `reset --hard`
sobre el árbol. Hay que reaplicarlo después de cada actualización.
