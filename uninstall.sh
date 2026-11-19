#!/usr/bin/env bash
# ============================================================
#   ARASAKA MIKOSHI // desinstalador
#   ./uninstall.sh          remove o app (mantem suas VMs)
#   ./uninstall.sh --tudo   remove tambem as VMs e configuracoes
#   QEMU, OVMF e swtpm NAO sao removidos.
# ============================================================
set -uo pipefail
APP_ID=arasaka-mikoshi
DATA="${XDG_DATA_HOME:-$HOME/.local/share}/$APP_ID"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
R=$'\e[38;2;227;18;31m'; B=$'\e[1m'; N=$'\e[0m'
ok() { printf '   %s■%s %s\n' "$R" "$N" "$*"; }

rm -f "$HOME/.local/bin/$APP_ID" "$APPS/$APP_ID.desktop" \
      "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps/$APP_ID.svg" \
      "${XDG_DATA_HOME:-$HOME/.local/share}/icons/Arasaka/scalable/apps/$APP_ID.svg"
rm -rf "$DATA/app" "$DATA/venv"
ok "app removido"
if [ "${1:-}" = "--tudo" ]; then
  printf '   Apagar TODAS as maquinas virtuais em %s? [s/N] ' "$DATA/machines"
  read -r r
  case "$r" in
    s|S|sim|SIM) rm -rf "$DATA" "${XDG_CONFIG_HOME:-$HOME/.config}/$APP_ID"; ok "VMs e configuracoes removidas" ;;
    *) echo "   VMs mantidas" ;;
  esac
else
  printf '   Suas VMs continuam em %s\n' "$DATA/machines"
fi
update-desktop-database -q "$APPS" 2>/dev/null
printf '\n%s%s ■ ARASAKA MIKOSHI REMOVIDO%s\n\n' "$R" "$B" "$N"
