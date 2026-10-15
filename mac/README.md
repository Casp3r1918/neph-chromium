# Neph für macOS: Quellen des Chromium-Anteils

Neph für macOS (Apple Silicon) liefert das `Chromium Embedded Framework.framework` aus einem eigenen Build aus. Darin steckt
ffmpeg unter der GNU Lesser General Public License 2.1. Dieser Ordner erfüllt das Angebot nach LGPL 2.1 § 6 für den Mac wie
das Repository als Ganzes für Windows: genaue Stände, alle Änderungen Nephs, Bauanleitung. Das Angebot gilt mindestens drei
Jahre ab der jeweiligen Veröffentlichung; auf Anfrage beim Herausgeber auch als Archiv.

*Source offer (LGPL 2.1 § 6) for the Chromium/CEF part of Neph for macOS: exact upstream revisions, every modification
Neph applies, and the build instructions. Valid for at least three years after each release; available as an archive on request.*

## Neph 0.4.6 für macOS (2026-10-15)

| Bestandteil | Stand | Quelle |
|---|---|---|
| Chromium | `152.0.7977.158` (Commit `900724803344`) | https://chromium.googlesource.com/chromium/src/+/refs/tags/152.0.7977.158 |
| CEF | `152.0.13+g841e03d+chromium-152.0.7977.158` (Branch 7977, Commit `841e03d`) | https://github.com/chromiumembedded/cef/commit/841e03d |
| ffmpeg (`third_party/ffmpeg`) | `2b68d2babae7` | https://chromium.googlesource.com/chromium/third_party/ffmpeg/+/2b68d2babae73714846961fb0ee47e3b3d2e39a9 |
| ANGLE (`third_party/angle`) | `4f2e7d39252e` | https://chromium.googlesource.com/angle/angle/+/4f2e7d39252ed0e8387ebee1b222d4715f2dea7d |
| Nephs Änderungen | `mac/patches/` | dieses Repository, Tag `neph-v0.4.6` |
| GN-Argumente | `mac/build/GN_DEFINES.txt`, `mac/build/args.gn` | dieses Repository |

## Inhalt

- `patches/apply.py` mit `vault_patch.py` und `downloads_patch.py`: das Skript, das Nephs Änderungen schreibt.
- `patches/neph-code.patch`, `patches/neph-strings.patch`: dieselben Änderungen als Diff gegen den Chromium-Tag,
  aus dem Baum, aus dem dieses Framework gebaut wurde.
- `patches/angle-mrt-layout.patch`, `patches/cef-downloads.patch`: Änderungen in ANGLE und in CEF selbst.
- `patches/neph-patches.json`: Bericht des Skripts aus diesem Build.
- `build/BUILD.md`, `build/cef-build.sh`, `build/GN_DEFINES.txt`, `build/args.gn`: Bauablauf und Konfiguration.
- `LICENSES/`: Lizenztexte von Chromium, CEF, ffmpeg (LGPL 2.1) und ANGLE.

Was Neph gegenüber Chromium/CEF ändert: keine proprietären Codecs (`proprietary_codecs=false`, `ffmpeg_branding=Chromium`: kein H.264, AAC, HEVC), Manifest-V2-Erweiterungen bleiben nutzbar, Produktname „Neph“ in den Dialogen,
feinere Zoomstufen, GPU-Programm-Cache und Shader-Cache wie unter Windows, die Widevine-CDM-Komponente wird nur mit dem Schalter
`--neph-widevine` registriert, gespeicherte Passwörter verschlüsselt Nephs Tresor (Master-Passwort und ein Geräteschlüssel in der
Secure Enclave oder im Schlüsselbund) statt Chromiums Schlüssel im Schlüsselbund, Downloads melden auch nach dem Schließen ihres Tabs
weiter, Chrome-Seiten bekommen einen undurchsichtigen Grund, und Chromium fragt Googles Kontenliste (ListAccounts) nicht ab. Details im
Kopf von `patches/apply.py`.

Nicht enthalten: Nephs eigener Quelltext (Host, Oberfläche, Himmel, Updater). Er linkt nur dynamisch gegen das Framework
(BSD-3-Clause) und ist kein abgeleitetes Werk der LGPL-Bestandteile.
