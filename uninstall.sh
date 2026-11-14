#!/usr/bin/env bash
# Palettier uninstaller — removes installed binaries, desktop shortcut,
# virtual environment, systemd service, and restores original desktop themes.

set -euo pipefail

YES=0
PURGE=0

print_help() {
    cat <<'EOF'
Palettier Uninstaller

Usage:
  ./uninstall.sh [OPTIONS]

Options:
  -y, --yes     Non-interactive mode
      --purge   Also delete user configuration (~/.config/palettier)
  -h, --help    Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -y|--yes)
            YES=1
            shift
            ;;
        --purge)
            PURGE=1
            shift
            ;;
        -h|--help)
            print_help
            exit 0
            ;;
        *)
            echo "[!] Unknown option: $1" >&2
            print_help >&2
            exit 2
            ;;
    esac
done

XDG_DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
PALETTIER_HOME="$XDG_DATA_HOME/palettier"
BIN_DIR="${PALETTIER_BIN_DIR:-$HOME/.local/bin}"

PALETTIER_CMD=""
if [[ -x "$BIN_DIR/palettier" ]]; then
    PALETTIER_CMD="$BIN_DIR/palettier"
elif [[ -x "$PALETTIER_HOME/venv/bin/palettier" ]]; then
    PALETTIER_CMD="$PALETTIER_HOME/venv/bin/palettier"
elif command -v palettier >/dev/null 2>&1; then
    PALETTIER_CMD="$(command -v palettier)"
fi

if [[ -n "$PALETTIER_CMD" ]]; then
    "$PALETTIER_CMD" --uninstall || true
else
    echo "[*] Palettier CLI not found; cleaning local installation files only."
fi

rm -f "$BIN_DIR/palettier" "$BIN_DIR/palettier-gui"
rm -f "$XDG_DATA_HOME/applications/palettier.desktop"
rm -f "$XDG_DATA_HOME/icons/hicolor/512x512/apps/palettier.png"
rm -f "$XDG_DATA_HOME/icons/hicolor/scalable/apps/palettier.svg"

if [[ -d "$PALETTIER_HOME" ]]; then
    rm -rf "$PALETTIER_HOME"
    echo "[✓] Removed application data: $PALETTIER_HOME"
fi

if command -v update-desktop-database >/dev/null 2>&1 && [[ -d "$XDG_DATA_HOME/applications" ]]; then
    update-desktop-database "$XDG_DATA_HOME/applications" >/dev/null 2>&1 || true
fi

CONFIG_DIR="$XDG_CONFIG_HOME/palettier"
if [[ -d "$CONFIG_DIR" ]]; then
    if [[ "$PURGE" -eq 1 ]]; then
        rm -rf "$CONFIG_DIR"
        echo "[✓] Removed user configuration: $CONFIG_DIR"
    elif [[ "$YES" -eq 0 && -t 0 ]]; then
        read -r -p "[?] Remove saved Palettier configuration ($CONFIG_DIR)? [y/N] " ans
        if [[ "${ans,,}" == "y" || "${ans,,}" == "yes" || "${ans,,}" == "s" ]]; then
            rm -rf "$CONFIG_DIR"
            echo "[✓] Removed user configuration: $CONFIG_DIR"
        else
            echo "[*] Preserved configuration at: $CONFIG_DIR"
        fi
    else
        echo "[*] Preserved configuration at: $CONFIG_DIR (use --purge to remove)"
    fi
fi

echo "[✓] Palettier uninstalled cleanly."
