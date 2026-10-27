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

## Aktuelle Version: Neph 0.4.18 (2026-10-27)

| Bestandteil | Stand | Quelle |
|---|---|---|
| Chromium | `156.0.8078.48` (Commit `d0c02bfad08e`) | https://chromium.googlesource.com/chromium/src/+/refs/tags/156.0.8078.48 |
| CEF | `156.0.14+g4fa4ab5+chromium-156.0.8078.48` (Branch 8078, Commit `4fa4ab5`) | https://github.com/chromiumembedded/cef/commit/4fa4ab5 |
| ffmpeg (`third_party/ffmpeg`) | `9db86ce5b5b4` | https://chromium.googlesource.com/chromium/third_party/ffmpeg/+/9db86ce5b5b454dfc96c435f9f0723012980c37f |
| ANGLE (`third_party/angle`) | `3b89d84e9d59` | https://chromium.googlesource.com/angle/angle/+/3b89d84e9d59f75675ac4e2bef58fc068a9f0577 |
| Nephs Änderungen | `patches/` | dieses Repository, Tag `neph-v0.4.18` |
| GN-Argumente | `build/GN_DEFINES.txt`, `build/args.gn` | dieses Repository |

Alle weiteren Abhängigkeiten (DEPS) ergeben sich aus dem Chromium-Tag; `gclient sync` stellt sie exakt wieder her.

## Inhalt

- `patches/apply.py`: das Skript, das Nephs Änderungen in den Chromium-Baum schreibt (idempotent, erklärt jede Änderung),
  mit seinen Modulen `vault_patch.py` (Passwortspeicher) und `downloads_patch.py` (Downloads).
- `patches/neph-code.patch`: dieselben Änderungen als Diff gegen den Chromium-Tag, ohne Zeichenketten.
- `patches/neph-strings.patch`: Produktname „Neph“ in den Zeichenketten-Tabellen und ihren Übersetzungen.
- `patches/angle-mrt-layout.patch`: Änderung in ANGLE (eigenes Repository unter `third_party/angle`).
- `patches/cef-downloads.patch`: Änderung in CEF selbst (eigenes Repository unter `cef`).
- `patches/neph-overlays.patch`: Nephs Änderungen an Dateien, die auch CEFs eigene Patches ändern, als Diff gegen CEFs Fassung.
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