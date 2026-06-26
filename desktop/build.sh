#!/usr/bin/env bash
# 從乾淨環境打包 TWStockSim.app（選單列 + 內建後端，單一自包含 .app）。
# 用法：cd ~/Code/twstock-sim && desktop/build.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
BUILD_VENV="desktop/.venv"
PY="${PYTHON:-python3.14}"

echo "==> 1/4 建置用 venv: ${BUILD_VENV}"
[ -d "$BUILD_VENV" ] || "$PY" -m venv "$BUILD_VENV"
"$BUILD_VENV/bin/python" -m pip install -q --upgrade pip
"$BUILD_VENV/bin/python" -m pip install -q \
  -r requirements.txt \
  rumps pyobjc-framework-WebKit pyinstaller

echo "==> 2/4 產生 app icon（icon.icns）"
# 優先用 make-icon.swift 渲染的精緻 1024 圖；沒有才退回小張 apple-touch-icon
if [ ! -f desktop/icon-1024.png ] && [ -f desktop/make-icon.swift ] && command -v swift >/dev/null; then
  swift desktop/make-icon.swift >/dev/null 2>&1 || true
fi
if [ ! -f desktop/menubar-icon.png ] && [ -f desktop/make-menubar-icon.swift ] && command -v swift >/dev/null; then
  swift desktop/make-menubar-icon.swift >/dev/null 2>&1 || true
fi
if [ -f desktop/icon-1024.png ]; then SRC_PNG="desktop/icon-1024.png"; else SRC_PNG="frontend/apple-touch-icon.png"; fi
if [ -f "$SRC_PNG" ] && command -v sips >/dev/null && command -v iconutil >/dev/null; then
  ICONSET="desktop/icon.iconset"
  rm -rf "$ICONSET" && mkdir -p "$ICONSET"
  sips -z 1024 1024 "$SRC_PNG" --out "$ICONSET/_big.png" >/dev/null 2>&1 || cp "$SRC_PNG" "$ICONSET/_big.png"
  for s in 16 32 64 128 256 512 1024; do
    sips -z "$s" "$s" "$ICONSET/_big.png" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null 2>&1 || true
  done
  # Retina 命名（iconutil 需要的對照）
  cp "$ICONSET/icon_32x32.png"   "$ICONSET/icon_16x16@2x.png"   2>/dev/null || true
  cp "$ICONSET/icon_64x64.png"   "$ICONSET/icon_32x32@2x.png"   2>/dev/null || true
  cp "$ICONSET/icon_256x256.png" "$ICONSET/icon_128x128@2x.png" 2>/dev/null || true
  cp "$ICONSET/icon_512x512.png" "$ICONSET/icon_256x256@2x.png" 2>/dev/null || true
  cp "$ICONSET/icon_1024x1024.png" "$ICONSET/icon_512x512@2x.png" 2>/dev/null || true
  rm -f "$ICONSET/icon_64x64.png" "$ICONSET/icon_1024x1024.png" "$ICONSET/_big.png"
  iconutil -c icns "$ICONSET" -o desktop/icon.icns 2>/dev/null && echo "    icon.icns OK" || echo "    icon 產生失敗，略過（用預設圖示）"
  rm -rf "$ICONSET"
else
  echo "    來源 png 或工具缺，略過 icon"
fi

echo "==> 3/4 PyInstaller 打包"
rm -rf build desktop/dist
"$BUILD_VENV/bin/pyinstaller" --clean --noconfirm \
  --distpath desktop/dist --workpath build \
  desktop/twstock-sim.spec

echo "==> 4/4 完成"
echo "    產出： $ROOT/desktop/dist/TWStockSim.app"
echo "    開啟： open desktop/dist/TWStockSim.app"
