#!/usr/bin/env bash
# Palettier one-step installer for Linux desktops (GNOME / GTK 4 / Libadwaita).
# Supports local execution (./install.sh) and remote curl | bash installation.

set -euo pipefail

REPO_URL="https://github.com/PedroMachado1/Palettier.git"
TARBALL_URL="https://github.com/PedroMachado1/Palettier/archive/refs/heads/main.tar.gz"

YES=0
NO_SERVICE=0
NO_GUI=0
DO_UNINSTALL=0

print_help() {
    cat <<'EOF'
Palettier Installer

Usage:
  ./install.sh [OPTIONS]

Options:
  -y, --yes         Non-interactive mode (accept default prompts)
      --no-service  Skip systemd --user background service setup
      --no-gui      Skip desktop launcher (.desktop) and app icon installation
      --uninstall   Uninstall Palettier and restore desktop defaults
  -h, --help        Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -y|--yes)
            YES=1
            shift
            ;;
        --no-service)
            NO_SERVICE=1
            shift
            ;;
        --no-gui)
            NO_GUI=1
            shift
            ;;
        --uninstall)
            DO_UNINSTALL=1
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
VENV_DIR="$PALETTIER_HOME/venv"
APP_SRC_DIR="$PALETTIER_HOME/app"
BIN_DIR="${PALETTIER_BIN_DIR:-$HOME/.local/bin}"

SCRIPT_SOURCE="${BASH_SOURCE[0]:-}"
SCRIPT_DIR=""
if [[ -n "$SCRIPT_SOURCE" && -f "$SCRIPT_SOURCE" ]]; then
    SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_SOURCE")" && pwd)"
fi

if [[ "$DO_UNINSTALL" -eq 1 ]]; then
    if [[ -n "$SCRIPT_DIR" && -f "$SCRIPT_DIR/uninstall.sh" ]]; then
        exec bash "$SCRIPT_DIR/uninstall.sh" $([[ "$YES" -eq 1 ]] && echo "--yes")
    else
        echo "[*] Downloading uninstaller..."
        TMP_UNINSTALL="$(mktemp)"
        trap 'rm -f "$TMP_UNINSTALL"' EXIT
        if command -v curl >/dev/null 2>&1; then
            curl -fsSL "https://raw.githubusercontent.com/PedroMachado1/Palettier/main/uninstall.sh" -o "$TMP_UNINSTALL"
        elif command -v wget >/dev/null 2>&1; then
            wget -qO "$TMP_UNINSTALL" "https://raw.githubusercontent.com/PedroMachado1/Palettier/main/uninstall.sh"
        else
            echo "[!] curl or wget is required to fetch uninstall.sh." >&2
            exit 1
        fi
        exec bash "$TMP_UNINSTALL" $([[ "$YES" -eq 1 ]] && echo "--yes")
    fi
fi

echo "=================================================="
echo "             Palettier — Installer                "
echo "=================================================="

detect_pkg_manager() {
    if command -v dnf >/dev/null 2>&1; then
        echo "dnf"
    elif command -v apt-get >/dev/null 2>&1; then
        echo "apt"
    elif command -v pacman >/dev/null 2>&1; then
        echo "pacman"
    elif command -v zypper >/dev/null 2>&1; then
        echo "zypper"
    else
        echo "unknown"
    fi
}

PKG_MGR="$(detect_pkg_manager)"

distro_dep_cmd() {
    case "$PKG_MGR" in
        dnf)
            echo "sudo dnf install -y python3 python3-pillow python3-gobject gtk4 libadwaita"
            ;;
        apt)
            echo "sudo apt update && sudo apt install -y python3 python3-venv python3-pil python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-gio-2.0"
            ;;
        pacman)
            echo "sudo pacman -S --needed python python-pillow python-gobject gtk4 libadwaita"
            ;;
        zypper)
            echo "sudo zypper install -y python3 python3-Pillow python3-gobject gtk4 libadwaita typelib-1_0-Gtk-4_0 typelib-1_0-Adw-1"
            ;;
        *)
            echo "Install Python 3.10+, python3-venv, Pillow, PyGObject, GTK 4, and Libadwaita via your package manager."
            ;;
    esac
}

# 1. Verify Python >= 3.10 and venv support
if ! command -v python3 >/dev/null 2>&1; then
    echo "[!] python3 was not found." >&2
    echo "    Install dependencies with: $(distro_dep_cmd)" >&2
    exit 1
fi

if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
    echo "[!] Python 3.10 or newer is required (found: $(python3 --version))." >&2
    exit 1
fi

if ! python3 -m venv --help >/dev/null 2>&1; then
    echo "[!] Python 'venv' module is missing." >&2
    echo "    Install system packages first:" >&2
    echo "      $(distro_dep_cmd)" >&2
    exit 1
fi

# 2. Check native GNOME / GTK 4 / Libadwaita bindings (optional but recommended)
HAS_GI_GTK=0
if python3 -c 'import gi; gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1"); from gi.repository import Gtk, Adw' >/dev/null 2>&1; then
    HAS_GI_GTK=1
fi

if [[ "$HAS_GI_GTK" -eq 0 ]]; then
    echo "[*] Optional native GTK 4 / Libadwaita bindings (python3-gi) were not detected."
    echo "    Recommended for the native GNOME Settings window & --watch daemon:"
    echo "      $(distro_dep_cmd)"
    if [[ "$YES" -eq 0 && -t 0 && "$PKG_MGR" != "unknown" ]] && command -v sudo >/dev/null 2>&1; then
        read -r -p "[?] Install recommended native packages via sudo now? [y/N] " ans
        if [[ "${ans,,}" == "y" || "${ans,,}" == "yes" || "${ans,,}" == "s" ]]; then
            case "$PKG_MGR" in
                dnf) sudo dnf install -y python3-pillow python3-gobject gtk4 libadwaita || true ;;
                apt) sudo apt-get update && sudo apt-get install -y python3-venv python3-pil python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-gio-2.0 || true ;;
                pacman) sudo pacman -S --needed python-pillow python-gobject gtk4 libadwaita || true ;;
                zypper) sudo zypper install -y python3-Pillow python3-gobject gtk4 libadwaita typelib-1_0-Gtk-4_0 typelib-1_0-Adw-1 || true ;;
            esac
        fi
    else
        echo "    Continuing anyway — Palettier includes a local Web Settings UI fallback (--web-ui)."
    fi
fi

# 3. Resolve local source checkout or download repository
SOURCE_DIR=""
if [[ -n "$SCRIPT_DIR" && -f "$SCRIPT_DIR/pyproject.toml" && -f "$SCRIPT_DIR/palettier/__init__.py" ]]; then
    SOURCE_DIR="$SCRIPT_DIR"
    echo "[*] Installing from local directory: $SOURCE_DIR"
else
    echo "[*] Fetching Palettier source into: $APP_SRC_DIR"
    mkdir -p "$PALETTIER_HOME"
    if command -v git >/dev/null 2>&1; then
        if [[ -d "$APP_SRC_DIR/.git" ]]; then
            git -C "$APP_SRC_DIR" pull --ff-only
        else
            rm -rf "$APP_SRC_DIR"
            git clone --depth 1 "$REPO_URL" "$APP_SRC_DIR"
        fi
    else
        TMP_TAR="$(mktemp)"
        TMP_EXTRACT="$(mktemp -d)"
        trap 'rm -f "$TMP_TAR"; rm -rf "$TMP_EXTRACT"' EXIT
        if command -v curl >/dev/null 2>&1; then
            curl -fsSL "$TARBALL_URL" -o "$TMP_TAR"
        elif command -v wget >/dev/null 2>&1; then
            wget -qO "$TMP_TAR" "$TARBALL_URL"
        else
            echo "[!] Neither git, curl, nor wget is installed." >&2
            exit 1
        fi
        tar -xzf "$TMP_TAR" -C "$TMP_EXTRACT"
        EXTRACTED_DIR="$(find "$TMP_EXTRACT" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
        rm -rf "$APP_SRC_DIR"
        mv "$EXTRACTED_DIR" "$APP_SRC_DIR"
    fi
    SOURCE_DIR="$APP_SRC_DIR"
fi

# 4. Create isolated venv with --system-site-packages (preserves system PyGObject/GTK4)
echo "[*] Setting up virtual environment at: $VENV_DIR"
mkdir -p "$PALETTIER_HOME"
python3 -m venv --system-site-packages "$VENV_DIR"

if ! "$VENV_DIR/bin/python" -c "import PIL" >/dev/null 2>&1; then
    echo "[*] Installing Pillow in virtual environment..."
    "$VENV_DIR/bin/pip" install --quiet "Pillow>=9.0"
fi

echo "[*] Installing Palettier package..."
if "$VENV_DIR/bin/python" -c "import setuptools" >/dev/null 2>&1; then
    "$VENV_DIR/bin/pip" install --quiet --no-deps --no-build-isolation "$SOURCE_DIR"
else
    "$VENV_DIR/bin/pip" install --quiet --no-deps "$SOURCE_DIR"
fi

# 5. Install CLI symlinks in ~/.local/bin
mkdir -p "$BIN_DIR"
ln -sf "$VENV_DIR/bin/palettier" "$BIN_DIR/palettier"
if [[ -e "$VENV_DIR/bin/palettier-gui" ]]; then
    ln -sf "$VENV_DIR/bin/palettier-gui" "$BIN_DIR/palettier-gui"
fi
echo "[✓] CLI installed at: $BIN_DIR/palettier"

# 6. Install desktop entry and application icon
if [[ "$NO_GUI" -eq 0 ]]; then
    ICON_PNG_DIR="$XDG_DATA_HOME/icons/hicolor/512x512/apps"
    ICON_SVG_DIR="$XDG_DATA_HOME/icons/hicolor/scalable/apps"
    DESKTOP_DIR="$XDG_DATA_HOME/applications"
    mkdir -p "$DESKTOP_DIR"

    if [[ -f "$SOURCE_DIR/palettier/assets/palettier.png" ]]; then
        mkdir -p "$ICON_PNG_DIR"
        cp -f "$SOURCE_DIR/palettier/assets/palettier.png" "$ICON_PNG_DIR/palettier.png"
        rm -f "$ICON_SVG_DIR/palettier.svg"
    elif [[ -f "$SOURCE_DIR/palettier/assets/palettier.svg" ]]; then
        mkdir -p "$ICON_SVG_DIR"
        cp -f "$SOURCE_DIR/palettier/assets/palettier.svg" "$ICON_SVG_DIR/palettier.svg"
    fi

    cat > "$DESKTOP_DIR/palettier.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Palettier Settings
GenericName=Wallpaper Theme Synchronizer
Comment=Customize Material Design 3 wallpaper colors, icons, and theme targets
Exec=$BIN_DIR/palettier --gui
Icon=palettier
Terminal=false
Categories=Settings;DesktopSettings;GTK;
Keywords=wallpaper;theme;material;icons;colors;gnome;
StartupNotify=true
EOF

    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true
    fi
    if command -v gtk-update-icon-cache >/dev/null 2>&1; then
        gtk-update-icon-cache -f -t "$XDG_DATA_HOME/icons/hicolor" >/dev/null 2>&1 || true
    fi
    echo "[✓] Desktop shortcut installed at: $DESKTOP_DIR/palettier.desktop"
fi

# 7. Configure systemd --user background service
if [[ "$NO_SERVICE" -eq 0 ]]; then
    echo "[*] Installing systemd --user service..."
    "$BIN_DIR/palettier" --install-service

    if command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; then
        ENABLE_SVC=0
        if [[ "$YES" -eq 1 ]]; then
            ENABLE_SVC=1
        elif [[ -t 0 ]]; then
            read -r -p "[?] Enable and start background theme sync service now? [Y/n] " svc_ans
            if [[ -z "$svc_ans" || "${svc_ans,,}" == "y" || "${svc_ans,,}" == "yes" || "${svc_ans,,}" == "s" ]]; then
                ENABLE_SVC=1
            fi
        fi

        if [[ "$ENABLE_SVC" -eq 1 ]]; then
            systemctl --user daemon-reload
            systemctl --user enable --now palettier.service
            echo "[✓] Background service enabled and running!"
        fi
    else
        echo "[*] Systemd user D-Bus session not active here; skipping automatic enable."
        echo "    Enable later with: systemctl --user enable --now palettier.service"
    fi
fi

echo ""
echo "=================================================="
echo "          Palettier installed successfully!       "
echo "=================================================="
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    echo "[!] Note: $BIN_DIR is not currently in your \$PATH."
    echo "    Add it to ~/.bashrc or ~/.zshrc:"
    echo "      export PATH=\"$BIN_DIR:\$PATH\""
    echo ""
fi
echo "Next steps:"
echo "  • Open Settings UI:   $BIN_DIR/palettier --gui"
echo "  • Sync once now:      $BIN_DIR/palettier"
echo "  • Inspect palette:    $BIN_DIR/palettier --info"
echo "  • Config file:        $XDG_CONFIG_HOME/palettier/config.json"
