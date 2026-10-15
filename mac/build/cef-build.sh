#!/bin/zsh
# Nephs eigener CEF-Build auf dem Mac (13.10.2026), das Gegenstück zu
# scripts/cef-build.ps1: dieselben vier Stufen, jede wiederholbar.
#
#   scripts/mac/cef-build.sh sync <CEF-Commit>     CEF auf den Commit, Chromium auf den Tag aus
#                                                  CHROMIUM_BUILD_COMPATIBILITY.txt, ohne Git-Verlauf,
#                                                  Abhängigkeiten und Hooks
#   scripts/mac/cef-build.sh patch [--lenient]     CEFs Patcher, dann chromium-patches/apply.py
#   scripts/mac/cef-build.sh build                 Release arm64, minimale Distribution (ohne Archiv)
#   scripts/mac/cef-build.sh install               Distribution nach third_party/, NEPH-BUILD.txt,
#                                                  cef-release-mac.json
#   scripts/mac/cef-build.sh all <CEF-Commit>      alle vier nacheinander
#
# Umgebung: NEPH_CEF_ROOT (Vorgabe ~/cefbuild) mit depot_tools und automate-git.py
# (scripts/mac/fetch-cef.py --build-tools legt beide an), NEPH_CEF_JOBS begrenzt die
# parallelen Compiler (Vorgabe: Kerne minus 2, 16 GB reichen nicht für alle),
# NEPH_GN_DEFINES ersetzt die GN-Vorgaben. Protokolle unter <Root>/pipeline/<Stempel>/.
# Fallen vom 13.10.2026: depot_tools' gsutil wird beim ersten parallelen Download
# doppelt installiert (Sperrfehler Errno 35), darum einmal vorab; automate-git hält
# einen vorhandenen Baum ohne Verlauf für fertig und holt die Abhängigkeiten nicht
# nach, darum gclient sync und runhooks von Hand; Chromiums Mac-Kern braucht Xcode.
set -euo pipefail
repo="${0:A:h:h:h}"
root="${NEPH_CEF_ROOT:-$HOME/cefbuild}"
download="$root/chromium_git"
depot="$root/depot_tools"
cefdir="$download/cef"
src="$download/chromium/src"
automate="$root/automate-git.py"
stamp="$(date +%Y%m%d-%H%M%S)"
logdir="$root/pipeline/$stamp"
mkdir -p "$logdir"
echo "$stamp" > "$root/pipeline/current"
export PATH="$depot:$PATH"
export DEPOT_TOOLS_UPDATE=0
export CEF_ARCHIVE_FORMAT=tar.bz2
# Wie Windows (cef-build.ps1), dazu symbol_level=0 (E41: Platz und Speicher).
export GN_DEFINES="${NEPH_GN_DEFINES:-is_official_build=true proprietary_codecs=false ffmpeg_branding=Chromium enable_widevine=true use_thin_lto=false chrome_pgo_phase=0 symbol_level=0}"
cores=$(sysctl -n hw.ncpu)
jobs="${NEPH_CEF_JOBS:-$(( cores > 2 ? cores - 2 : 1 ))}"
export NINJA_CORE_ADDITION=$(( jobs - cores ))

log() { local line="$(date +%H:%M:%S) $*"; echo "$line"; echo "$line" >> "$logdir/cef-build.log"; }
# Ein Schritt mit niedriger Priorität, wach gehalten, Ausgabe in eine Protokolldatei.
run_stage() {
  local name="$1"; shift
  log "$name: $*"
  local started=$(date +%s)
  set +e
  caffeinate -i -s nice -n 5 "$@" > "$logdir/$name.log" 2>&1
  local code=$?
  set -e
  log "$name: Exit $code nach $(( ($(date +%s) - started) / 60 )) min"
  return $code
}

stage="${1:-}"; shift || true
commit="${1:-}"
case "$stage" in
  sync|all)
    [[ -n "$commit" ]] || { echo "sync braucht den CEF-Commit (z. B. 841e03d)" >&2; exit 2; }
    [[ -f "$automate" ]] || { echo "automate-git.py fehlt unter $root" >&2; exit 2; }
    python3 "$depot/gsutil.py" version > /dev/null 2>&1 || true
    branch=""
    if [[ -d "$cefdir" ]]; then
      git -C "$cefdir" fetch --quiet origin
      branch=$(git -C "$cefdir" show "$commit:CHROMIUM_BUILD_COMPATIBILITY.txt" | sed -nE 's/.*refs\/tags\/[0-9]+\.[0-9]+\.([0-9]+)\.[0-9]+.*/\1/p' | head -1)
    fi
    args=(--download-dir="$download" --depot-tools-dir="$depot" --no-depot-tools-update --checkout="$commit"
          --no-chromium-history --arm64-build --no-build --no-distrib --no-debug-build)
    [[ -n "$branch" ]] && args+=(--branch="$branch")
    run_stage sync python3 "$automate" "${args[@]}" || { log "Sync gescheitert (sync.log)."; exit 1; }
    ( cd "$download/chromium" && run_stage sync-deps gclient sync --nohooks --no-history ) || { log "Abhängigkeiten gescheitert (sync-deps.log)."; exit 1; }
    ( cd "$download/chromium" && run_stage runhooks gclient runhooks ) || { log "Hooks gescheitert (runhooks.log)."; exit 1; }
    log "Sync fertig: Chromium $(git -C "$src" describe --tags --exact-match 2>/dev/null || echo '?'), CEF $(git -C "$cefdir" rev-parse --short HEAD)"
    [[ "$stage" == "all" ]] || exit 0
    ;&
  patch)
    [[ "$stage" == "all" ]] || commit=""
    lenient=""; [[ "${1:-}" == "--lenient" || "${2:-}" == "--lenient" ]] && lenient="--lenient"
    ( cd "$src/cef" && run_stage patch-cef python3 tools/patcher.py ) || { log "CEF-Patcher gescheitert."; exit 1; }
    run_stage patch-neph python3 "$repo/scripts/chromium-patches/apply.py" "$src" $lenient || { log "apply.py: Anker nicht gefunden (patch-neph.log). Nicht bauen."; exit 97; }
    [[ -f "$src/neph-patches.json" ]] && cp "$src/neph-patches.json" "$logdir/"
    [[ "$stage" == "all" ]] || exit 0
    ;&
  build)
    head=$(git -C "$src/cef" rev-parse HEAD)
    branch=$(sed -nE 's/.*refs\/tags\/[0-9]+\.[0-9]+\.([0-9]+)\.[0-9]+.*/\1/p' "$src/cef/CHROMIUM_BUILD_COMPATIBILITY.txt" | head -1)
    log "Build: Branch $branch, CEF ${head:0:7}, $jobs Compiler, GN: $GN_DEFINES"
    run_stage build python3 "$automate" --download-dir="$download" --depot-tools-dir="$depot" --no-depot-tools-update --no-update \
      --branch="$branch" --checkout="$head" --arm64-build --force-build --no-debug-build \
      --minimal-distrib --minimal-distrib-only --no-distrib-docs --no-distrib-archive --build-log-file \
      || { log "Build gescheitert (build.log, $download/build-$branch-release.log)."; exit 1; }
    [[ -f "$download/build-$branch-release.log" ]] && cp "$download/build-$branch-release.log" "$logdir/ninja-release.log"
    [[ "$stage" == "all" ]] || exit 0
    ;&
  install)
    distrib=$(ls -dt "$src"/cef/binary_distrib/cef_binary_*_macosarm64_minimal 2>/dev/null | head -1)
    [[ -n "$distrib" ]] || { echo "Keine Distribution unter $src/cef/binary_distrib" >&2; exit 1; }
    [[ -d "$distrib/Release/Chromium Embedded Framework.framework" ]] || { echo "Distribution unvollständig: $distrib" >&2; exit 1; }
    name=$(basename "$distrib")
    version=$(echo "$name" | sed -E 's/^cef_binary_(.+)_macosarm64_minimal$/\1/')
    chromium=$(echo "$version" | sed -E 's/.*chromium-([0-9.]+)$/\1/')
    target="$repo/third_party/$name"
    # Nur eine Distribution darf unter third_party liegen (neph_mac.cmake).
    for other in "$repo"/third_party/cef_binary_*_macosarm64*; do
      [[ -d "$other" && "$other" != "$target" ]] && { log "Install: entferne $(basename "$other")"; rm -rf "$other"; }
    done
    log "Install: $name -> third_party"
    rm -rf "$target"; cp -R "$distrib" "$target"
    {
      echo "Neph's own CEF build for macOS (not the official cef-builds.spotifycdn.com archive)."
      echo "Built $(date '+%Y-%m-%d %H:%M') on this Mac from CEF $(git -C "$src/cef" rev-parse --short HEAD) (${version%%+*}) / Chromium $chromium"
      echo "with scripts/chromium-patches/apply.py (scripts/mac/cef-build.sh), Xcode $(xcodebuild -version | head -1 | sed 's/Xcode //'), and"
      echo "GN: $GN_DEFINES"
      echo "Patches: see scripts/chromium-patches/apply.py; vault for login_database_mac.cc; exports as framework symbols."
      echo
      cat "$src/neph-patches.json" 2>/dev/null || echo "(neph-patches.json fehlt)"
    } > "$target/NEPH-BUILD.txt"
    python3 - "$repo/third_party/cef-release-mac.json" "$version" "$chromium" "$name" <<'PY'
import json, sys, datetime
path, version, chromium, name = sys.argv[1:5]
entry = {"platform": "macosarm64", "cef_version": version, "chromium_version": chromium, "channel": "stable",
         "files": [{"type": "minimal", "name": name + ".tar.bz2", "sha1": "", "size": 0,
                    "last_modified": datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}],
         "note": "Nephs eigener Mac-Kern (scripts/mac/cef-build.sh), nicht aus dem CEF-Index; NEPH-BUILD.txt in der Distribution."}
json.dump(entry, open(path, 'w'), indent=2, ensure_ascii=False)
open(path, 'a').write('\n')
PY
    log "Install fertig: CEF ${version%%+*} / Chromium $chromium in third_party, cef-release-mac.json aktualisiert."
    ;;
  *) sed -n 2,20p "$0"; exit 2 ;;
esac
log "Fertig."
