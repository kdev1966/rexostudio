#!/bin/bash
# ---------------------------------------------------------------------------
# Cree l'application "MontageIA" (icone a double-cliquer), sur le bureau par
# defaut :
#     ./scripts/install_launcher.sh            -> ~/Desktop/MontageIA.app
#     ./scripts/install_launcher.sh /Applications
#
# Au double-clic : demarre le serveur s'il ne tourne pas (sans fenetre de
# Terminal), attend qu'il reponde, puis ouvre l'interface dans le navigateur.
# S'il tourne deja, ouvre simplement l'interface. On le quitte avec le bouton
# "Quitter" de l'interface. Journal : ~/Library/Logs/MontageIA.log
# ---------------------------------------------------------------------------
set -eu
cd "$(dirname "$0")/.."
PROJECT="$(pwd)"
DEST="${1:-$HOME/Desktop}"
APP="$DEST/MontageIA.app"
BUNDLE_ID="local.montagia.launcher"
PORT="$(python3 -c 'from montagia import config; print(config.PORT)' 2>/dev/null || echo 8080)"

# On ne remplace qu'une application creee par ce script.
if [ -e "$APP" ]; then
  if [ "$(defaults read "$APP/Contents/Info" CFBundleIdentifier 2>/dev/null)" != "$BUNDLE_ID" ]; then
    echo "$APP existe et n'a pas ete cree par MontageIA : rien n'est modifie." >&2
    exit 1
  fi
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
BUILD="$WORK/MontageIA.app"
mkdir -p "$BUILD/Contents/MacOS" "$BUILD/Contents/Resources"

# --- icone -----------------------------------------------------------------
echo "Icone..."
python3 scripts/make_icon.py "$WORK/icon.png"
ICONSET="$WORK/MontageIA.iconset"
mkdir "$ICONSET"
for size in 16 32 128 256 512; do
  sips -z "$size" "$size" "$WORK/icon.png" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
  double=$((size * 2))
  sips -z "$double" "$double" "$WORK/icon.png" --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$BUILD/Contents/Resources/MontageIA.icns"

# --- description de l'application -----------------------------------------
cat > "$BUILD/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>MontageIA</string>
  <key>CFBundleDisplayName</key><string>MontageIA</string>
  <key>CFBundleIdentifier</key><string>$BUNDLE_ID</string>
  <key>CFBundleExecutable</key><string>MontageIA</string>
  <key>CFBundleIconFile</key><string>MontageIA</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>LSMinimumSystemVersion</key><string>10.13</string>
</dict>
</plist>
PLIST

# --- lanceur ----------------------------------------------------------------
cat > "$BUILD/Contents/MacOS/MontageIA" <<LAUNCHER
#!/bin/bash
# Lanceur de MontageIA (genere par scripts/install_launcher.sh).
PROJECT="$PROJECT"
URL="http://127.0.0.1:$PORT"
LOG="\$HOME/Library/Logs/MontageIA.log"
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"

up() { curl -s --max-time 2 -o /dev/null -f "\$URL/api/status"; }
alert() { osascript -e "display alert \"\$1\" message \"\$2\" as critical" >/dev/null 2>&1; }

if ! up; then
  if [ ! -x "\$PROJECT/start.sh" ]; then
    alert "MontageIA est introuvable" "Dossier attendu : \$PROJECT"
    exit 1
  fi
  mkdir -p "\$(dirname "\$LOG")"
  cd "\$PROJECT" || exit 1
  # Serveur detache du lanceur : il continue apres la fin de ce script.
  # (Commande simple en arriere-plan : pas de sous-shell qui resterait en vie.)
  MONTAGIA_NO_BROWSER=1 nohup ./start.sh > "\$LOG" 2>&1 &
  for _ in \$(seq 1 90); do
    sleep 1
    up && break
  done
  if ! up; then
    alert "MontageIA n'a pas démarré" "Le journal est ici : \$LOG"
    exit 1
  fi
fi
open "\$URL"
LAUNCHER
chmod +x "$BUILD/Contents/MacOS/MontageIA"

# --- installation -----------------------------------------------------------
mkdir -p "$DEST"
rm -rf "$APP"
mv "$BUILD" "$APP"
touch "$APP"            # le Finder relit l'icone
echo "Application installee : $APP"
