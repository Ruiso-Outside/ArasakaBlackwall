#!/usr/bin/env bash
# ============================================================
#   ARASAKA MIKOSHI // instalador (Zorin OS / Ubuntu / Debian)
#   Maquinas virtuais Windows e Linux com QEMU + KVM
#
#   Uso:  ./install.sh [opcoes]        (NAO rode com sudo)
#     --sem-spice    nao instala o visualizador SPICE (virt-viewer)
#     --com-samba    instala o Samba (pastas compartilhadas com a VM)
#     -y             nao pede confirmacao
# ============================================================
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ID=arasaka-mikoshi
DATA="${XDG_DATA_HOME:-$HOME/.local/share}/$APP_ID"
BIN="$HOME/.local/bin"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICONS="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"

DO_SPICE=1 DO_SMB=0 YES=0
for a in "$@"; do
  case "$a" in
    --sem-spice) DO_SPICE=0 ;;
    --com-samba) DO_SMB=1 ;;
    -y|--yes) YES=1 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "Opcao desconhecida: $a"; exit 1 ;;
  esac
done

R=$'\e[38;2;227;18;31m'; RH=$'\e[38;2;255;59;71m'; W=$'\e[38;2;236;236;240m'
G=$'\e[38;2;120;120;130m'; B=$'\e[1m'; N=$'\e[0m'
STEP=0
step() { STEP=$((STEP + 1)); printf '\n%s%s[%02d]%s %s%s%s\n' "$R" "$B" "$STEP" "$N" "$W$B" "$*" "$N"; }
ok()   { printf '     %s■%s %s\n' "$R" "$N" "$*"; }
info() { printf '     %s›%s %s\n' "$R" "$N" "$*"; }
warn() { printf '     %s!! %s%s\n' "$RH" "$*" "$N"; }
die()  { printf '\n%s!! %s%s\n' "$RH" "$*" "$N"; exit 1; }

printf '\n%s%s   A R A S A K A   M I K O S H I%s\n' "$R" "$B" "$N"
printf '   %sMaquinas virtuais Windows e Linux%s\n' "$G" "$N"

[ "$EUID" -eq 0 ] && die "Rode como seu usuario normal (sem sudo): ./install.sh"
[ -f "$DIR/arasaka_mikoshi/app.py" ] || die "Arquivos do app nao encontrados em $DIR"
command -v python3 >/dev/null || die "python3 nao encontrado"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || die "Precisa de Python 3.9+"

if grep -qE ' (vmx|svm)' /proc/cpuinfo; then
  ok "virtualizacao da CPU disponivel"
else
  warn "VT-x/AMD-V nao detectado: ative 'Virtualization' / 'SVM' na BIOS/UEFI, senao as VMs ficam muito lentas"
fi

if [ "$YES" -eq 0 ]; then
  printf '\n   Vai instalar: QEMU/KVM, firmware UEFI (OVMF), TPM 2.0 (swtpm)'
  [ "$DO_SPICE" -eq 1 ] && printf ', virt-viewer'
  [ "$DO_SMB" -eq 1 ] && printf ', Samba'
  printf ' e o app (Python + Qt).\n   %sContinuar? [s/N] %s' "$W" "$N"
  read -r r
  case "$r" in s|S|y|Y|sim|SIM) ;; *) echo "Cancelado."; exit 0 ;; esac
fi

# ---------------------------------------------------------------- sistema
step "Pacotes do sistema"
sudo -v || die "sudo necessario"
PKGS=(qemu-system-x86 qemu-utils qemu-system-gui ovmf swtpm swtpm-tools
      python3-venv python3-pip libxcb-cursor0 libxkbcommon-x11-0 libxcb-icccm4 libxcb-keysyms1
      libxcb-image0 libxcb-render-util0 libxcb-xinerama0 libxcb-shape0 libegl1 xdg-utils)
[ "$DO_SPICE" -eq 1 ] && PKGS+=(virt-viewer)
[ "$DO_SMB" -eq 1 ] && PKGS+=(samba)
MISSING=()
for p in "${PKGS[@]}"; do dpkg -s "$p" >/dev/null 2>&1 || MISSING+=("$p"); done
if [ ${#MISSING[@]} -gt 0 ]; then
  info "instalando: ${MISSING[*]}"
  sudo apt-get update -qq || warn "apt update falhou"
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${MISSING[@]}" \
    || warn "alguns pacotes falharam; veja a aba SISTEMA do app"
fi
# Ubuntu 24.04+ separa SPICE e OpenGL em modulos
for p in qemu-system-modules-spice qemu-system-modules-opengl; do
  if apt-cache show "$p" >/dev/null 2>&1 && ! dpkg -s "$p" >/dev/null 2>&1; then
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "$p" >/dev/null 2>&1 && ok "$p"
  fi
done
command -v qemu-system-x86_64 >/dev/null && ok "$(qemu-system-x86_64 --version | head -1)"

NEED_RELOGIN=0
if ! id -nG "$USER" | tr ' ' '\n' | grep -qx kvm; then
  sudo usermod -aG kvm "$USER" && ok "usuario adicionado ao grupo kvm" && NEED_RELOGIN=1
else
  ok "usuario ja esta no grupo kvm"
fi

# ---------------------------------------------------------------- app
step "Ambiente Python (PySide6 / Qt 6)"
mkdir -p "$DATA"
if [ ! -x "$DATA/venv/bin/python" ]; then
  python3 -m venv "$DATA/venv" || die "falha ao criar o venv (falta python3-venv?)"
fi
"$DATA/venv/bin/python" -m pip install -q --upgrade pip >/dev/null 2>&1
info "baixando PySide6 (~120 MB na primeira vez)..."
"$DATA/venv/bin/python" -m pip install -q --upgrade "PySide6-Essentials>=6.5" || die "falha ao instalar PySide6"
ok "PySide6 $("$DATA/venv/bin/python" -c 'import PySide6; print(PySide6.__version__)')"

step "Arquivos do app"
rm -rf "$DATA/app"
mkdir -p "$DATA/app" "$BIN" "$APPS" "$ICONS"
cp -r "$DIR/arasaka_mikoshi" "$DATA/app/"
find "$DATA/app" -name '__pycache__' -prune -exec rm -rf {} +
cat > "$BIN/$APP_ID" <<EOF
#!/bin/sh
# ARASAKA MIKOSHI launcher
export PYTHONPATH="$DATA/app\${PYTHONPATH:+:\$PYTHONPATH}"
exec "$DATA/venv/bin/python" -m arasaka_mikoshi "\$@"
EOF
chmod +x "$BIN/$APP_ID"
cp "$DIR/arasaka_mikoshi/assets/arasaka-mikoshi.svg" "$ICONS/$APP_ID.svg"
cat > "$APPS/$APP_ID.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Arasaka Mikoshi
GenericName=Maquinas Virtuais
Comment=Rode Windows e Linux em maquinas virtuais (QEMU/KVM)
Exec="$BIN/$APP_ID"
Icon=$APP_ID
Terminal=false
Categories=System;Emulator;
Keywords=vm;virtual;machine;qemu;kvm;windows;linux;arasaka;mikoshi;
StartupWMClass=arasaka-mikoshi
EOF
update-desktop-database -q "$APPS" 2>/dev/null
ok "atalho no menu: Arasaka Mikoshi"

printf '\n%s%s ■ INSTALACAO CONCLUIDA%s\n' "$R" "$B" "$N"
if [ "$NEED_RELOGIN" -eq 1 ]; then
  printf '   %sEncerre a sessao e entre de novo (permissao do KVM) antes de ligar uma VM.%s\n' "$W$B" "$N"
fi
printf '   %sAbra "Arasaka Mikoshi" no menu do Zorin (ou rode: arasaka-mikoshi).%s\n\n' "$W" "$N"
