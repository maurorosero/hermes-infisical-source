#!/usr/bin/env bash
# =============================================================================
# install.sh — instala Infisical en Hermes: el plugin recortado Y el patch que lo
# vuelve una fuente incluida del core.
#
# Por qué hacen falta las dos cosas. Un plugin se carga DESPUÉS de que Hermes valida
# credenciales: `hermes doctor` mira la configuración del modelo en su sección 7, y los
# plugins recién cargan en la 18. Por eso los secretos de un plugin llegan tarde y el
# doctor reporta que el proveedor no tiene credencial —aunque la bóveda esté perfecta—.
# Las fuentes incluidas (1Password, Bitwarden, command) no sufren eso porque el core las
# registra en el acto, sin depender del cargador de plugins.
#
# Este script pone `InfisicalSource` en la lista de fuentes incluidas del core, y deja el
# plugin con lo único que el patch no puede dar: los comandos `hermes infisical setup|status`.
#
# El patch vive en el árbol de Hermes y NO sobrevive a `hermes update` (el actualizador
# hace `stash push` y `reset --hard`). Volvé a correr este script después de cada update.
#
# Uso:
#   ./install.sh                 # instala el plugin si falta y aplica el patch
#   ./install.sh --check         # no escribe nada: informa y sale 1 si falta algo
#   ./install.sh --deep          # además corre `hermes doctor` (tarda ~1 min)
#   ./install.sh --revert        # saca el patch del core (deja el plugin instalado)
#
# Nada de esto lleva secretos adentro: las credenciales se leen de Infisical en tiempo
# de ejecución, como con cualquier otra fuente.
# =============================================================================
set -Eeuo pipefail

REPO_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
AGENT_HOME=${HERMES_HOME:-$HOME/.hermes}
TREE="$AGENT_HOME/hermes-agent"
SOURCES="$TREE/agent/secret_sources"
DEST="$SOURCES/infisical.py"
REGISTRY="$SOURCES/registry.py"
PLUGIN_ORIGEN="maurorosero/hermes-infisical-source"

MODO=aplicar
FALLAS=0
# `hermes` vive en ~/.local/bin en las instalaciones nativas; sin esto el script no lo
# encuentra cuando corre desde un cron o un ssh sin perfil cargado.
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) PATH="$HOME/.local/bin:$PATH" ;; esac
export PATH
DEEP=false
for a in "$@"; do
  case "$a" in
    --check)  MODO=check ;;
    --deep)   DEEP=true ;;
    --revert) MODO=revert ;;
    -h|--help) sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) printf '  [error] argumento desconocido: %s\n' "$a" >&2; exit 2 ;;
  esac
done

info() { printf '  [..] %s\n' "$*"; }
ok()   { printf '  [ok] %s\n' "$*"; }
aviso(){ printf '  [aviso] %s\n' "$*"; }
die()  { local c=$1; shift; printf '  [error] %s\n' "$*" >&2; exit "$c"; }

# --- El intérprete: el de la máquina si existe, si no python3 -----------------
PY=""
for cand in "${PYTHON:-}" "$HOME/bin/runtime-python.sh" "$(command -v python3 2>/dev/null || true)"; do
  [ -n "$cand" ] || continue
  if [ -x "$cand" ]; then PY=$("$cand" -c 'import sys; print(sys.executable)' 2>/dev/null) && [ -n "$PY" ] && break; fi
done
[ -n "$PY" ] || die 2 "no encuentro un intérprete de Python"
command -v hermes >/dev/null || aviso "hermes no está en PATH: se aplica el patch igual, pero no puedo instalar el plugin"

[ -f "$REGISTRY" ] || die 3 "no encuentro el árbol de Hermes en $TREE (¿HERMES_HOME distinto?)"
[ -f "$REPO_DIR/__init__.py" ] || die 3 "no encuentro __init__.py junto a este script"

echo "  repo:        $REPO_DIR"
echo "  árbol:       $TREE"
echo "  intérprete:  $PY"
echo

# --- 1) El plugin recortado, por la vía de Hermes -----------------------------
echo "1 · plugin (el CLI setup|status)"
# Chequeo por disco y no con `hermes plugins list`: ese comando tarda más de un minuto en
# una máquina con dependencias desincronizadas, y lo único que hace falta saber es si el
# plugin está en su carpeta y listado como habilitado.
PLUGIN_DIR="$AGENT_HOME/plugins/infisical"
HABILITADO=""
[ -f "$AGENT_HOME/config.yaml" ] && HABILITADO=$(grep -A20 '^plugins:' "$AGENT_HOME/config.yaml" 2>/dev/null | grep -c '^\s*-\s*infisical\s*$' || true)
if [ -f "$PLUGIN_DIR/plugin.yaml" ] && [ "${HABILITADO:-0}" -gt 0 ]; then
  ok "instalado y habilitado en $PLUGIN_DIR"
elif [ -f "$PLUGIN_DIR/plugin.yaml" ]; then
  if [ "$MODO" = check ]; then
    aviso "el plugin está en disco pero no figura habilitado (hermes plugins enable infisical)"
    FALLAS=$((FALLAS + 1))
  elif [ "$MODO" = revert ]; then
    ok "no se toca el plugin en modo revert"
  else
    hermes plugins enable infisical >/dev/null 2>&1 && ok "habilitado" || aviso "no pude habilitarlo"
  fi
elif [ "$MODO" = check ]; then
  aviso "falta el plugin (hermes plugins install $PLUGIN_ORIGEN)"
  FALLAS=$((FALLAS + 1))
elif [ "$MODO" = revert ]; then
  ok "no se toca el plugin en modo revert"
else
  info "instalando $PLUGIN_ORIGEN"
  hermes plugins install "$PLUGIN_ORIGEN" --yes-deps --enable >/dev/null 2>&1 \
    && ok "plugin instalado y habilitado" || aviso "no pude instalarlo automáticamente"
fi
echo

# --- 2) El source, derivado del repo (una sola fuente) ------------------------
echo "2 · el patch: el source en el árbol de Hermes"
NUEVO=$(mktemp)
trap 'rm -f "$NUEVO"' EXIT
"$PY" - "$REPO_DIR/__init__.py" > "$NUEVO" <<'PY'
import pathlib, sys
lineas = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8").splitlines(keepends=True)
corte = len(lineas)
for i, ln in enumerate(lineas):
    if ln.startswith("def register("):
        corte = i
        break
# se recorta el bloque de registro del plugin: como fuente del core ese registro sobra
# (el core instancia la clase directamente) y su import relativo a .cli rompería.
sys.stdout.write("".join(lineas[:corte]).rstrip() + "\n")
PY
[ -s "$NUEVO" ] || die 4 "la derivación quedó vacía: revisá el __init__.py del repo"

if [ "$MODO" = revert ]; then
  if [ -f "$DEST" ]; then rm -f "$DEST" && ok "source quitado del árbol"; else ok "no había source que quitar"; fi
elif [ -f "$DEST" ] && cmp -s "$NUEVO" "$DEST"; then
  ok "ya está puesto y al día ($(wc -l < "$DEST") líneas)"
elif [ "$MODO" = check ]; then
  [ -f "$DEST" ] && aviso "está desactualizado respecto del repo" || aviso "falta $DEST"
  FALLAS=$((FALLAS + 1))
else
  install -m 644 "$NUEVO" "$DEST"
  ok "escrito $(wc -l < "$DEST") líneas en $DEST"
fi
echo

# --- 3) La línea en la lista de fuentes incluidas -----------------------------
echo "3 · el patch: la entrada en _BUILTIN_SOURCES"
if [ "$MODO" = revert ]; then
  if grep -qF 'agent.secret_sources.infisical' "$REGISTRY"; then
    "$PY" - "$REGISTRY" <<'PY'
import pathlib, sys
p = pathlib.Path(sys.argv[1])
t = p.read_text(encoding="utf-8")
linea = '    ("agent.secret_sources.infisical", "InfisicalSource", "Infisical"),\n'
p.write_text(t.replace(linea, ""), encoding="utf-8")
PY
    ok "entrada quitada"
  else
    ok "no había entrada que quitar"
  fi
elif grep -qF 'agent.secret_sources.infisical' "$REGISTRY"; then
  ok "la entrada ya está"
elif [ "$MODO" = check ]; then
  aviso "falta la entrada (el source no se registraría)"
  FALLAS=$((FALLAS + 1))
else
  "$PY" - "$REGISTRY" <<'PY'
import pathlib, sys
p = pathlib.Path(sys.argv[1])
t = p.read_text(encoding="utf-8")
ancla = '    ("agent.secret_sources.command", "CommandSource", "command"),\n'
linea = '    ("agent.secret_sources.infisical", "InfisicalSource", "Infisical"),\n'
if linea not in t:
    if ancla not in t:
        sys.exit("no encuentro el cierre de _BUILTIN_SOURCES: no toco nada")
    t = t.replace(ancla, ancla + linea, 1)
    p.write_text(t, encoding="utf-8")
PY
  ok "entrada agregada"
fi
echo

# --- 4) Verificación: que de verdad quede registrado --------------------------
# En modo revert se acaba de quitar a propósito, así que no hay nada que verificar.
echo "4 · verificación"
if [ "$MODO" = revert ]; then
  ok "el patch ya no está; el plugin sigue instalado"
elif $PY - "$TREE" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
from agent.secret_sources.registry import list_sources, _SOURCE_ORIGINS
nombres = [s.name for s in list_sources()]
origen = _SOURCE_ORIGINS.get("infisical", "")
sys.exit(0 if "infisical" in nombres and origen == "builtin" and nombres.count("infisical") == 1 else 1)
PY
then ok "infisical figura como fuente incluida del core, sin duplicados"
else
  aviso "el source NO quedó registrado como fuente del core"
  exit 1
fi

if $DEEP; then
  echo
  echo "5 · el doctor (tarda)"
  if hermes doctor 2>&1 | grep -q 'no API key is configured'; then
    aviso "el doctor sigue marcando falta de credencial"
    exit 1
  else
    ok "el doctor no marca falta de credencial"
  fi
fi

echo
if [ "$FALLAS" -gt 0 ]; then
  printf '  --check: %s cosa(s) por resolver. No se escribió nada.\n' "$FALLAS"
  exit 1
fi
case "$MODO" in
  check)  echo "  --check: no se escribió nada. Todo en su lugar." ;;
  revert) echo "  patch quitado. El plugin sigue instalado (comandos del CLI)." ;;
  *)      echo "  listo. Recordá: el próximo 'hermes update' borra el patch — volvé a correr este script." ;;
esac
