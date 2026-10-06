# Nachbau von libcef.dll für Neph 0.3.17

Windows 10/11 x64, Visual Studio 2022 Build Tools (C++, ATL/MFC), Windows SDK 10.0.26100, ~250 GB frei, 16 GB RAM
(mit `chrome_pgo_phase=0 use_thin_lto=false`; ein Vollbuild dauert auf einem i5-10500 etwa 13 Stunden).

1. depot_tools entpacken (https://storage.googleapis.com/chrome-infra/depot_tools.zip), `DEPOT_TOOLS_UPDATE=0`,
   `DEPOT_TOOLS_WIN_TOOLCHAIN=0`, `GYP_MSVS_VERSION=2022`.
2. `automate-git.py` aus CEF (https://github.com/chromiumembedded/cef, `tools/automate/automate-git.py`) holen und
   ausführen:

   `python automate-git.py --download-dir=C:\cefbuild\chromium_git --depot-tools-dir=C:\cefbuild\depot_tools --no-depot-tools-update --branch=7977 --checkout=e1f344f --x64-build --no-build --no-distrib --no-debug-build`

   Das stellt CEF auf Commit `e1f344f` und Chromium auf `refs/tags/152.0.7977.152` (aus `CHROMIUM_BUILD_COMPATIBILITY.txt`).
3. CEFs Patches: `python cef\tools\patcher.py` in `chromium\src\cef`.
4. Nephs Patches: `python patches\apply.py C:\cefbuild\chromium_git\chromium\src` (oder die Diffs in `patches\` mit
   `git apply` einspielen; `angle-mrt-layout.patch` gehört in `third_party\angle`, `cef-downloads.patch` in `cef`).
5. `GN_DEFINES=is_official_build=true proprietary_codecs=true ffmpeg_branding=Chrome enable_widevine=true use_thin_lto=false chrome_pgo_phase=0` setzen (`build\args.gn` zeigt die erzeugte Konfiguration) und bauen:

   `python automate-git.py --download-dir=C:\cefbuild\chromium_git --depot-tools-dir=C:\cefbuild\depot_tools --no-depot-tools-update --no-update --branch=7977 --checkout=e1f344f --x64-build --force-build --no-debug-build --minimal-distrib --minimal-distrib-only`

6. Ergebnis: `chromium\src\cef\binary_distrib\cef_binary_152.0.12+ge1f344f+chromium-152.0.7977.152_windows64_minimal` mit `Release\libcef.dll`.

`build\cef-build.ps1` ist das Skript, mit dem Neph genau diese Schritte ausführt.