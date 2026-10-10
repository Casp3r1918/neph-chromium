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

## Aktuelle Version: Neph 0.4.3 (2026-10-10)

| Bestandteil | Stand | Quelle |
|---|---|---|
| Chromium | `152.0.7977.158` (Commit `900724803344`) | https://chromium.googlesource.com/chromium/src/+/refs/tags/152.0.7977.158 |
| CEF | `152.0.13+g841e03d+chromium-152.0.7977.158` (Branch 7977, Commit `841e03d`) | https://github.com/chromiumembedded/cef/commit/841e03d |
| ffmpeg (`third_party/ffmpeg`) | `2b68d2babae7` | https://chromium.googlesource.com/chromium/third_party/ffmpeg/+/2b68d2babae73714846961fb0ee47e3b3d2e39a9 |
| ANGLE (`third_party/angle`) | `4f2e7d39252e` | https://chromium.googlesource.com/angle/angle/+/4f2e7d39252ed0e8387ebee1b222d4715f2dea7d |
| Nephs Änderungen | `patches/` | dieses Repository, Tag `neph-v0.4.3` |
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

Was Neph gegenüber Chromium/CEF ändert: proprietäre Codecs eingeschaltet (``proprietary_codecs=true``, ``ffmpeg_branding=Chrome``), Manifest-V2-Erweiterungen bleiben nutzbar, Produktname „Neph“ in den Dialogen, GPU-Programm-Cache
64 MB und zwei Korrekturen am Shader-Cache (Chromium, ANGLE), die Widevine-CDM-Komponente wird nur mit dem Schalter
`--neph-widevine` registriert, gespeicherte Passwörter verschlüsselt Nephs Tresor (Master-Passwort und TPM) statt des
Windows-Schlüssels, und Downloads melden auch nach dem Schließen ihres Tabs weiter, wachsen als `.crdownload` und werden
beim Schließen eines Tabs nicht mehr abgebrochen. Details stehen im Kopf von `patches/apply.py`.

Nicht enthalten: Nephs eigener Quelltext (Host, Oberfläche, Himmel, Setup, Updater). Er linkt nur dynamisch gegen
`libcef.dll` (BSD-3-Clause) und ist kein abgeleitetes Werk der LGPL-Bestandteile.

## Frühere Versionen

Zu den meisten Neph-Versionen gibt es hier einen Tag `neph-v<Version>`. Versionen ohne eigenen Tag bauen den
Chromium-Anteil nicht neu, sondern liefern die `libcef.dll` einer früheren Version aus und verweisen auf deren Tag;
`VERSIONS.md` listet jede Version mit ihrem Tag und ihren Ständen.