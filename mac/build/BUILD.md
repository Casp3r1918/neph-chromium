# Nachbau des Chromium Embedded Framework für Neph 0.4.6 (macOS, Apple Silicon)

Gebaut auf macOS 26.2 (Apple Silicon, 10 Kerne, 16 GB RAM) mit Xcode 26.5, Python 3,
Platz: 42 GB (`~/cefbuild`, Baum ohne Git-Verlauf samt Build). Mit `chrome_pgo_phase=0 use_thin_lto=false symbol_level=0` und 8 parallelen
Compilern dauerte der Vollbuild etwa 4½ Stunden (13.10.2026).

1. depot_tools holen (`git clone https://chromium.googlesource.com/chromium/tools/depot_tools.git ~/cefbuild/depot_tools`),
   `DEPOT_TOOLS_UPDATE=0`, depot_tools vorn in den `PATH`.
2. `automate-git.py` aus CEF (https://github.com/chromiumembedded/cef, `tools/automate/automate-git.py`) holen und ausführen:

   `python3 automate-git.py --download-dir=~/cefbuild/chromium_git --depot-tools-dir=~/cefbuild/depot_tools --no-depot-tools-update --branch=7977 --checkout=841e03d --no-chromium-history --arm64-build --no-build --no-distrib --no-debug-build`

   Das stellt CEF auf Commit `841e03d` und Chromium auf `refs/tags/152.0.7977.158` (aus `CHROMIUM_BUILD_COMPATIBILITY.txt`);
   danach in `chromium_git/chromium` `gclient sync --nohooks --no-history` und `gclient runhooks`.
3. CEFs Patches: `python3 tools/patcher.py` in `chromium/src/cef`.
4. Nephs Patches: `python3 patches/apply.py ~/cefbuild/chromium_git/chromium/src` (oder die Diffs in `patches/` mit
   `git apply` einspielen; `angle-mrt-layout.patch` gehört in `third_party/angle`, `cef-downloads.patch` in `cef`).
5. `GN_DEFINES="is_official_build=true proprietary_codecs=false ffmpeg_branding=Chromium enable_widevine=true use_thin_lto=false chrome_pgo_phase=0 symbol_level=0"` setzen (`build/args.gn` zeigt die erzeugte Konfiguration) und bauen:

   `python3 automate-git.py --download-dir=~/cefbuild/chromium_git --depot-tools-dir=~/cefbuild/depot_tools --no-depot-tools-update --no-update --branch=7977 --checkout=841e03d --arm64-build --force-build --no-debug-build --minimal-distrib --minimal-distrib-only`

6. Ergebnis: `chromium/src/cef/binary_distrib/cef_binary_152.0.13+g841e03d+chromium-152.0.7977.158_macosarm64_minimal` mit `Release/Chromium Embedded Framework.framework`.

`build/cef-build.sh` ist das Skript, mit dem Neph genau diese Schritte ausführt (`sync`, `patch`, `build`, `install`).
