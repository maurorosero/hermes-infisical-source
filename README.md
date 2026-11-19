# hermes-infisical-source

Infisical como **fuente de secretos del core** de [Hermes Agent](https://hermes-agent.nousresearch.com/), más los comandos para configurarla. El repo hace dos cosas distintas, y conviene no confundirlas:

- **`InfisicalSource`** — la fuente. Resuelve la carpeta del proyecto por **Universal Auth** (Client ID + Client Secret) y la inyecta completa al entorno del gateway al arrancar, igual que el Bitwarden BSM del core. Es un *bulk source*.
- **`hermes infisical setup | status`** — los comandos para escribir la configuración y verificarla.

**La fuente no corre desde el plugin.** `install.sh` la escribe en el árbol de Hermes (`agent/secret_sources/infisical.py`) y la registra en `_BUILTIN_SOURCES`. El motivo es el orden de arranque: Hermes valida las credenciales del modelo **antes** de cargar plugins, así que un plugin llega tarde. En runtime, lo que aporta el plugin son los comandos.

> **Aporte a la comunidad Hermes.** Publicado como repo standalone (la doc oficial del harness indica que Infisical no va in-tree: *"Everything else — Infisical, Proton Pass, HashiCorp Vault… — belongs in plugin repos"*).

## Requisitos

- Hermes Agent (cualquier versión con el sistema de secret sources — `agent.secret_sources`)
- CLI de Infisical (`infisical`) en el PATH
- Cuenta/proyecto Infisical con Universal Auth habilitado
- Python 3.11+
- **PyYAML** (`yaml`) — la usa `cli.py` para leer y escribir `config.yaml`

> PyYAML está declarada en `pyproject.toml`, así que `hermes plugins install`
> y `hermes plugins enable` la resuelven en el entorno del agente. Si instalás
> copiando los archivos a mano, instalala vos: `pip install "PyYAML>=6.0"`.
>
> Sin ella el plugin se instala igual y **muere al cargar** con
> `No module named 'yaml'`. Como no carga, no se aplican los secretos y el error
> que se ve habla de otra cosa —el proveedor del modelo se queda sin credencial
> (*"Set OLLAMA_API_KEY"*)—, así que conviene revisar esta dependencia primero.

## Instalación

### La vía completa: `install.sh` (plugin **y** patch)

```bash
git clone https://github.com/maurorosero/hermes-infisical-source ~/.hermes/plugins/infisical
cd ~/.hermes/plugins/infisical
bash install.sh --check    # informa, no escribe nada
bash install.sh            # instala el plugin y aplica el patch
```

`install.sh` hace tres cosas, y las tres son idempotentes:

1. instala o deja instalado el **plugin** (que aporta `hermes infisical setup` y `hermes infisical status`);
2. deriva `InfisicalSource` desde este `__init__.py` y lo escribe en el árbol de Hermes, en `agent/secret_sources/infisical.py`;
3. agrega la entrada `("agent.secret_sources.infisical", "InfisicalSource", "Infisical")` a `_BUILTIN_SOURCES` del core.

**Por qué el patch, y no sólo el plugin.** Hermes valida las credenciales del modelo antes de cargar los plugins: en `hermes doctor` esa validación es la sección 7 y los plugins recién cargan en la 18. Un secret source que vive como plugin aplica sus secretos **después** de esa mirada, así que el `doctor` reporta que el proveedor no tiene credencial aunque la bóveda esté perfecta. Las fuentes incluidas del core —Bitwarden, 1Password, `command`— no sufren eso porque el core las registra en el acto, sin depender del cargador de plugins. El patch le da a Infisical ese mismo trato; el plugin se queda con lo que el patch no puede dar, que es el CLI.

**El patch no sobrevive a `hermes update`.** El actualizador hace `stash push` y `reset --hard` sobre el árbol, así que la entrada de `_BUILTIN_SOURCES` se revierte. Después de cada actualización hay que volver a correr `bash install.sh`; el archivo del source sobrevive (no está versionado), la entrada no.

Para deshacerlo: `bash install.sh --revert` saca el patch del core y deja el plugin instalado.

### Sólo el plugin (sin el patch)

```bash
hermes plugins install maurorosero/hermes-infisical-source
```

> Portable packages se instalan deshabilitados — habilítalo después con `hermes plugins enable infisical`.

Sin el patch, el plugin **no resuelve ningún secreto**: su `register()` sólo registra los comandos
`hermes infisical setup | status`, no la fuente. Sirve para configurar y verificar, no para inyectar.
Un perfil con `secrets.infisical.enabled: true` y sin el patch arranca sin credenciales, y el
síntoma no habla de secretos: el proveedor del modelo se queda sin llave.

### Manual (cualquier perfil u otro agente)

```bash
# 1. Clona el repo (o copia los dos archivos) dentro del perfil:
#    ~/.hermes/plugins/infisical/  (o $HERMES_HOME/plugins/)
git clone https://github.com/maurorosero/hermes-infisical-source \
    ~/.hermes/plugins/infisical
```

### Bootstrap del secreto

El único secreto que el plugin necesita para **arrancar** es el Client Secret de Universal Auth, en `~/.hermes/.env` (o `$HERMES_HOME/.env`):

```env
INFISICAL_CLIENT_ID=...    # opcional — no sensible, puede ir en config
INFISICAL_CLIENT_SECRET=... # bootstrap — NUNCA en el repo
```

## Configuración — `config.yaml`

```yaml
plugins:
  enabled:
    - infisical

secrets:
  infisical:
    enabled: true
    env: prod
    folder: /PROJECT-SLUG
    project_id: 2465eb3c-841e-400b-947d-991ecfdc67bf
    timeout: 30
    fail_open: true        # los fallos NO bloquean el arranque
```

| Clave | Descripción |
|---|---|
| `enabled` | Activa el source |
| `project_id` | ID del proyecto Infisical |
| `folder` | Carpeta a inyectar (bulk) |
| `env` | Entorno (prod/dev/staging) |
| `timeout` | Timeout del fetch (s) |
| `fail_open` | Si falla, arrancar sin secretos en lugar de bloquear |

## Verificación

```bash
# lista rápida de secretos resueltos (solo NOMBRES, nunca valores)
infisical-ls
```

## Notas

- **El plugin NO toca `os.environ` directo**: implementa `SecretSource.fetch() → FetchResult` (contrato `agent.secret_sources.base`); el orquestador de Hermes es dueño de precedencia, conflictos y `os.environ`.
- Usa `run_secret_cli` (helper del core) con `allow_env` restringido — no pasa el entorno completo al CLI.
- Compatibilidad: usa `agent.secret_sources._cache` (módulo interno del core) — mantenlo al día con la versión del harness instalado.

## Gate de secretos

Este repo trae un guardrail local que **frena un secreto antes de que llegue al remoto**.
Son dos archivos versionados —`.pre-commit-config.yaml` y `.gitleaks.toml`— más un
`.gitignore` con la sección de secretos en claro.

**Después de clonar, hay que activarlo. Los hooks no se versionan: viven en `.git/hooks/`.**

```bash
pre-commit install --hook-type pre-commit --hook-type pre-push
```

Qué hace cada punto de intercepción:

- **`pre-commit`** — linters sobre lo que se está por commitear.
- **`pre-push`** — `gitleaks` sobre el **rango `origin/main..HEAD`**. Es la barrera real:
  un secreto commiteado y después borrado igual viaja en el historial, así que mirar el
  working tree no lo vería; mirar el rango de commits, sí.

Los secretos viven en **Infisical**, no en los archivos. El escáner es la red por si alguien
se equivoca, no el método. La única excepción son los archivos cifrados con SOPS
(`*.sops.yaml`, `*.sops.yml`, `*.sops.json`): se versionan a propósito y no se ignoran.

Y el límite honesto: GitHub no bloquea el push en repos privados sin plan pago, y una Action
corre **después** del push. Toda la eficacia está en el hook local, de ahí el `pre-commit install`.

## Licencia

MIT. Ver `LICENSE`.

## Autoría / crédito

- Autor original: **Alan Rosero One** (OPENTECH / ROSERO ONE) — plugin `infisical` v1.0.0
- Publicado por: **Mauro Rosero Pérez** (maurorosero)
