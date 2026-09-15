# hermes-infisical-source

Plugin de **secret source** para [Hermes Agent](https://hermes-agent.nousresearch.com/): resuelve credenciales de proveedor desde una carpeta de proyecto de Infisical al arranque, vía **Universal Auth** (Client ID + Client Secret). Es un *bulk source*: inyecta la carpeta completa configurada (p. ej. `/ALAN-AI`) al entorno del gateway, igual que el Bitwarden BSM del core.

> **Aporte a la comunidad Hermes.** Publicado como repo standalone (la doc oficial del harness indica que Infisical no va in-tree: *"Everything else — Infisical, Proton Pass, HashiCorp Vault… — belongs in plugin repos"*).

## Requisitos

- Hermes Agent (cualquier versión con el sistema de secret sources — `agent.secret_sources`)
- CLI de Infisical (`infisical`) en el PATH
- Cuenta/proyecto Infisical con Universal Auth habilitado
- Python 3.11+

## Instalación

### Como plugin de Hermes (la vía recomendada para agentes)

```bash
hermes plugins install maurorosero/hermes-infisical-source
```

> Portable packages se instalan deshabilitados — habilítalo después con `hermes plugins enable infisical`.

### Manual (cualquier perfil/agente: Andrea, Alan, etc.)

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
    folder: /ALAN-AI
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

## Licencia

MIT. Ver `LICENSE`.

## Autoría / crédito

- Autor original: **Alan Rosero One** (OPENTECH / ROSERO ONE) — plugin `infisical` v1.0.0
- Publicado por: **Mauro Rosero Pérez** (maurorosero)
