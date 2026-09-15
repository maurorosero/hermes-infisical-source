# Integrar el plugin en cualquier perfil de Hermes (Andrea, Alan, otros)

## Vía instalador oficial (recomendada)

```bash
hermes plugins install maurorosero/hermes-infisical-source
hermes plugins enable infisical
```

## Vía manual (perfil específico)

```bash
git clone https://github.com/maurorosero/hermes-infisical-source \
    $HERMES_HOME/plugins/infisical
```

Donde `$HERMES_HOME` = `~/.hermes/profiles/<perfil>/`.

## Pasos de configuración

1. Bootstrap: `INFISICAL_CLIENT_SECRET` en `$HERMES_HOME/.env`
2. Config: bloque `secrets.infisical` en `$HERMES_HOME/config.yaml` (ver `examples/config.yaml`)
3. Reiniciar el gateway del perfil (los secret sources se resuelven al arranque)

## Notas de integración

- El plugin es **bulk**: inyecta TODA la carpeta configurada (p. ej. `/ALAN-AI`) al entorno — los perfiles solo necesitan que su proyecto Infisical tenga la carpeta.
- Fail-open: si Infisical no responde, el perfil arranca sin secretos (no se bloquea el gateway).
- Compatibilidad: usa `agent.secret_sources._cache` (interno del core) — mantener el harness actualizado.
