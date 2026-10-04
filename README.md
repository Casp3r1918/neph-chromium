# neph-chromium

Quelltextangebot für den Chromium-/CEF-Anteil des Browsers **Neph** (https://github.com/Casp3r1918/neph-releases).

Neph liefert `libcef.dll` aus einem eigenen Build des Chromium Embedded Framework aus. Darin steckt ffmpeg,
das unter der GNU Lesser General Public License 2.1 steht. Dieses Repository erfüllt das Angebot nach LGPL 2.1 § 6:
es nennt für jede Neph-Version den genauen Stand der Quellen und enthält alles, was Neph gegenüber diesen Quellen
ändert, samt Bauanleitung. Das Angebot gilt mindestens drei Jahre ab der jeweiligen Veröffentlichung; wer kein Git
verwenden möchte, erhält die Dateien vom Herausgeber auf Anfrage als Archiv.

*Source offer (LGPL 2.1 § 6) for the Chromium/CEF part of the Neph browser: exact upstream revisions per release,
every modification Neph applies, and the build instructions. Valid for at least three years after each release;
available as an archive on request.*

## Aktuelle Version: Neph 0.3.3 (2026-10-04)

| Bestandteil | Stand | Quelle |
|---|---|---|
| Chromium | `152.0.7977.149` (Commit `ba6d62e0eace`) | https://chromium.googlesource.com/chromium/src/+/refs/tags/152.0.7977.149 |
| CEF | `152.0.11+g026c1f4+chromium-152.0.7977.149` (Branch 7977, Commit `026c1f4`) | https://github.com/chromiumembedded/cef/commit/026c1f4 |
| ffmpeg (`third_party/ffmpeg`) | `2b68d2babae7` | https://chromium.googlesource.com/chromium/third_party/ffmpeg/+/2b68d2babae73714846961fb0ee47e3b3d2e39a9 |
| ANGLE (`third_party/angle`) | `6c47c4b6dae7` | https://chromium.googlesource.com/angle/angle/+/6c47c4b6dae794245a23a16b3826efc09ebdefd0 |
| Nephs Änderungen | `patches/` | dieses Repository, Tag `neph-v0.3.3` |
| GN-Argumente | `build/GN_DEFINES.txt`, `build/args.gn` | dieses Repository |

Alle weiteren Abhängigkeiten (DEPS) ergeben sich aus dem Chromium-Tag; `gclient sync` stellt sie exakt wieder her.

## Inhalt

- `patches/apply.py`: das Skript, das Nephs Änderungen in den Chromium-Baum schreibt (idempotent, erklärt jede Änderung),
  mit seinen Modulen `vault_patch.py` (Passwortspeicher) und `downloads_patch.py` (Downloads).
- `patches/neph-code.patch`: dieselben Änderungen als Diff gegen den Chromium-Tag, ohne Zeichenketten.
- `patches/neph-strings.patch`: Produktname „Neph“ in den Zeichenketten-Tabellen und ihren Übersetzungen.
- `patches/angle-mrt-layout.patch`: Änderung in ANGLE (eigenes Repository unter `third_party/angle`).
- `patches/cef-downloads.patch`: Änderung in CEF selbst (eigenes Repository unter `cef`).
- `patches/neph-patches.json`: Bericht des Skripts aus dem Build dieser Version.
- `build/BUILD.md`, `build/cef-build.ps1`, `build/GN_DEFINES.txt`, `build/args.gn`: Bauablauf und Konfiguration.
- `LICENSES/`: Lizenztexte von Chromium, CEF, ffmpeg (LGPL 2.1) und ANGLE.

Was Neph gegenüber Chromium/CEF ändert: proprietäre Codecs eingeschaltet (`proprietary_codecs=true`,
`ffmpeg_branding=Chrome`), Manifest-V2-Erweiterungen bleiben nutzbar, Produktname „Neph“ in den Dialogen, GPU-Programm-Cache
64 MB und zwei Korrekturen am Shader-Cache (Chromium, ANGLE), die Widevine-CDM-Komponente wird nur mit dem Schalter
`--neph-widevine` registriert, gespeicherte Passwörter verschlüsselt Nephs Tresor (Master-Passwort und TPM) statt des
Windows-Schlüssels, und Downloads melden auch nach dem Schließen ihres Tabs weiter, wachsen als `.crdownload` und werden
beim Schließen eines Tabs nicht mehr abgebrochen. Details stehen im Kopf von `patches/apply.py`.

Nicht enthalten: Nephs eigener Quelltext (Host, Oberfläche, Himmel, Setup, Updater). Er linkt nur dynamisch gegen
`libcef.dll` (BSD-3-Clause) und ist kein abgeleitetes Werk der LGPL-Bestandteile.

## Frühere Versionen

Jede Neph-Version hat hier einen Tag `neph-v<Version>`; `VERSIONS.md` listet sie mit ihren Ständen.