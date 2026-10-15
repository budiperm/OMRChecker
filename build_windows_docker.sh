#!/usr/bin/env bash
# Cross-build OMRChecker.exe (GUI) from Linux using Wine + Windows Python in Docker.
set -euo pipefail
cd "$(dirname "$0")"
docker run --rm -v "$PWD":/src -w /src tobix/pywine:3.12 bash -c '
  set -e
  wine python -m pip install -q -r requirements.gui.txt -c requirements.wine-pins.txt
  wine pyinstaller --noconfirm --clean --onefile --windowed --name OMRChecker \
    --distpath dist --workpath build \
    --noupx --paths . --collect-submodules src --hidden-import openpyxl gui.py
  # Console variant that prints errors, for troubleshooting
  wine pyinstaller --noconfirm --onefile --console --name OMRChecker-debug \
    --distpath dist --workpath build \
    --noupx --paths . --collect-submodules src --hidden-import openpyxl gui.py
  chown -R '"$(id -u):$(id -g)"' dist build OMRChecker.spec OMRChecker-debug.spec
'
rm -rf dist/samples && cp -r samples dist/samples
(cd dist && rm -f OMRChecker-windows.zip && cp ../PERSYARATAN.txt . && zip -qr OMRChecker-windows.zip OMRChecker.exe PERSYARATAN.txt samples)
echo "Selesai: dist/OMRChecker.exe dan dist/OMRChecker-windows.zip"
