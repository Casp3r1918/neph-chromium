<#
Nephs eigener CEF-Build in Stufen; ersetzt phase1.cmd/phase2.cmd in C:\cefbuild
(docs/chromium-build.md). Jede Stufe ist wiederholbar: Sync tut nichts, wenn der
Checkout schon steht, apply.py schreibt nur, was sich ändert, ninja baut nur
Geändertes, Install vergleicht den Versionsnamen.

  .\scripts\cef-build.ps1 -Sync -Commit 026c1f4        CEF auf den Commit, Chromium auf den
                                                       Tag aus CHROMIUM_BUILD_COMPATIBILITY.txt
  .\scripts\cef-build.ps1 -Patch [-Lenient]            CEF-Patcher, dann chromium-patches\apply.py
  .\scripts\cef-build.ps1 -Build                       Release x64, minimale Distribution
  .\scripts\cef-build.ps1 -Install [-ReleaseJson p]    Distribution nach third_party\, NEPH-BUILD.txt,
                                                       cef-release.json (Index-Eintrag aus cef-watch -Json)
  .\scripts\cef-build.ps1 -All -Commit <sha> ...       alle vier nacheinander

Der Branch kommt aus dem CEF-Commit (CHROMIUM_BUILD_COMPATIBILITY.txt nennt den
Chromium-Tag, der Tag nennt den Branch); -Branch nur für den Erst-Checkout nötig.
Sync geht zuerst den schnellen Weg (apply.py --revert, dann automate-git
--fast-update: nur der Tag und seine DEPS wechseln, der Baum wird nicht über
origin/main zurückgesetzt) und fällt bei einem Fehler auf den klassischen
Weg zurück (gclient revert, voller Checkout, wie phase1.cmd); -Slow erzwingt ihn.
Alle Prozesse laufen mit niedriger Priorität (BelowNormal), damit der Rechner
nutzbar bleibt; -Jobs <n> begrenzt die parallelen Compiler (autoninja nimmt
sonst Threads + 2; nach dem Stromausfall vom 03.10.2026 unter Volllast lief
der Rest mit 8). Protokolle unter C:\cefbuild\pipeline\<Stempel>\.
Exit 0 ok, 97 Patch-Anker nicht gefunden, sonst der Code der gescheiterten Stufe.
#>
[CmdletBinding()]
param(
    [switch]$Sync, [switch]$Patch, [switch]$Build, [switch]$Install, [switch]$All,
    [string]$Commit = '',
    [string]$Branch = '',
    [switch]$Lenient,
    [switch]$Slow,
    [int]$Jobs = 0,
    # Affinitaetsmaske fuer die Compiler statt der ersten n logischen Kerne
    # (dezimal oder 0x...): mit Hyperthreading teilen sich LP 0/1, 2/3, ...
    # einen Kern; -Jobs 4 hiess bisher zwei physische Kerne. 0x555 = sechs
    # eigene Kerne auf dem i5-10500, siso zaehlt die gesetzten Bits als Jobs.
    [string]$AffinityMask = '',
    [string]$ReleaseJson = '',
    [string]$BuildRoot = 'C:\cefbuild',
    [string]$LogDir = '',
    [string]$GnDefines = 'is_official_build=true proprietary_codecs=true ffmpeg_branding=Chrome enable_widevine=true use_thin_lto=false chrome_pgo_phase=0'
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$downloadDir = Join-Path $BuildRoot 'chromium_git'
$depotTools = Join-Path $BuildRoot 'depot_tools'
$cefDir = Join-Path $downloadDir 'cef'
$src = Join-Path $downloadDir 'chromium\src'
$automate = Join-Path $BuildRoot 'automate-git.py'
if ($All) { $Sync = $Patch = $Build = $Install = $true }
if (-not ($Sync -or $Patch -or $Build -or $Install)) { Get-Help $MyInvocation.MyCommand.Path; exit 2 }
if ($LogDir -eq '') { $LogDir = Join-Path $BuildRoot ('pipeline\' + (Get-Date -Format 'yyyyMMdd-HHmmss')) }
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$times = [ordered]@{}

function Log([string]$text) {
    $line = (Get-Date -Format 'HH:mm:ss') + ' ' + $text
    Write-Host $line
    Add-Content -LiteralPath (Join-Path $LogDir 'cef-build.log') -Value $line -Encoding UTF8
}

# Dieselbe Umgebung wie phase1.cmd/phase2.cmd: Build Tools unter Program Files (x86),
# depot_tools ohne Selbstaktualisierung, GN-Argumente für Nephs Build.
function Set-BuildEnvironment {
    $env:DEPOT_TOOLS_WIN_TOOLCHAIN = '0'
    $env:GYP_MSVS_VERSION = '2022'
    $env:vs2022_install = 'C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools'
    $env:GYP_MSVS_OVERRIDE_PATH = $env:vs2022_install
    $env:DEPOT_TOOLS_UPDATE = '0'
    $env:CEF_ARCHIVE_FORMAT = 'tar.bz2'
    $env:VPYTHON_VIRTUALENV_ROOT = Join-Path $BuildRoot 'vpython-root'
    $env:CIPD_CACHE_DIR = Join-Path $BuildRoot 'cipd-cache'
    $env:GN_DEFINES = $GnDefines
    # autoninja rechnet -j = logische Kerne + NINJA_CORE_ADDITION (Vorgabe 2).
    if ($Jobs -gt 0) { $env:NINJA_CORE_ADDITION = [string]($Jobs - [Environment]::ProcessorCount) }
    if (-not ($env:PATH -split ';' | Where-Object { $_ -eq $depotTools })) { $env:PATH = $depotTools + ';' + $env:PATH }
}

# Ein Prozess mit niedriger Priorität, Ausgabe in eine Protokolldatei. Kinder
# (ninja, clang) erben die Priorität. Liefert den Exit-Code.
function Invoke-Logged([string]$stage, [string]$file, [string[]]$arguments, [string]$workingDirectory) {
    $out = Join-Path $LogDir "$stage.log"
    $err = Join-Path $LogDir "$stage.err"
    Log ("{0}: {1} {2}" -f $stage, $file, ($arguments -join ' '))
    $started = Get-Date
    $process = Start-Process -FilePath $file -ArgumentList $arguments -WorkingDirectory $workingDirectory -NoNewWindow -PassThru -RedirectStandardOutput $out -RedirectStandardError $err
    # Ohne den Griff auf das Handle liefert Windows PowerShell nach WaitForExit
    # keinen ExitCode (null); so geschehen beim ersten Sync am 03.10.2026.
    $null = $process.Handle
    try { $process.PriorityClass = [System.Diagnostics.ProcessPriorityClass]::BelowNormal } catch {}
    # -Jobs: die ersten n logischen Kerne als Affinität; Kinder (siso, clang)
    # erben sie, und siso zählt seine Kerne über die Affinitätsmaske. Die
    # Umgebungsvariable allein reichte nicht (siso ignorierte -j, 03.10.2026).
    if ($AffinityMask -ne '') { try { $process.ProcessorAffinity = [IntPtr][int64]$AffinityMask } catch { Log ("Affinität nicht gesetzt: " + $_.Exception.Message) } }
    elseif ($Jobs -gt 0 -and $Jobs -lt 64) { try { $process.ProcessorAffinity = [IntPtr](([int64]1 -shl $Jobs) - 1) } catch { Log ("Affinität nicht gesetzt: " + $_.Exception.Message) } }
    $process.WaitForExit()
    $minutes = [math]::Round(((Get-Date) - $started).TotalMinutes, 1)
    $script:times[$stage] = $minutes
    $exitCode = $process.ExitCode
    if ($null -eq $exitCode) { Log ("{0}: Exit-Code unbekannt, gilt als Fehler" -f $stage); $exitCode = -1 }
    Log ("{0}: Exit {1} nach {2} min" -f $stage, $exitCode, $minutes)
    return $exitCode
}

function Invoke-Git([string]$dir, [string[]]$arguments) {
    # Windows PowerShell macht aus stderr-Zeilen unter 'Stop' Ausnahmen; git
    # schreibt dorthin auch Hinweise, darum hier nur der Exit-Code zählt.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { $output = & git.exe -C $dir @arguments 2>&1 } finally { $ErrorActionPreference = $previous }
    if ($LASTEXITCODE -ne 0) { throw "git $($arguments -join ' ') in $dir : $output" }
    return (($output | ForEach-Object { "$_" }) -join "`n").Trim()
}

function Resolve-Branch {
    if ($Branch -ne '') { return $Branch }
    $compat = Join-Path $cefDir 'CHROMIUM_BUILD_COMPATIBILITY.txt'
    if (-not (Test-Path -LiteralPath $compat)) { throw 'Branch unbekannt: -Branch angeben (CHROMIUM_BUILD_COMPATIBILITY.txt fehlt).' }
    $tag = [regex]::Match((Get-Content -LiteralPath $compat -Raw), "refs/tags/(\d+)\.(\d+)\.(\d+)\.(\d+)")
    if (-not $tag.Success) { throw 'Chromium-Tag in CHROMIUM_BUILD_COMPATIBILITY.txt nicht gefunden.' }
    return $tag.Groups[3].Value
}

function Write-Times { $times | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $LogDir 'stage-times.json') -Encoding UTF8 }

Set-BuildEnvironment
Log ("Protokolle: {0}" -f $LogDir)

if ($Sync) {
    if ($Commit -eq '') { throw '-Sync braucht -Commit <CEF-Commit>.' }
    if (-not (Test-Path -LiteralPath $cefDir)) { throw "CEF-Checkout fehlt unter $cefDir (Erst-Checkout: docs/chromium-build.md)." }
    # Der Commit muss auf dem Branch liegen; das Kurzformat aus dem Index wird
    # hier aufgelöst, damit das Protokoll den vollen Hash nennt.
    Invoke-Git $cefDir @('fetch', '--quiet', 'origin') | Out-Null
    $full = Invoke-Git $cefDir @('rev-parse', '--verify', "$Commit^{commit}")
    $current = Invoke-Git $cefDir @('rev-parse', 'HEAD')
    # Der Branch des Ziel-Commits steht in dessen Kompatibilitätsdatei.
    $compatText = Invoke-Git $cefDir @('show', "${full}:CHROMIUM_BUILD_COMPATIBILITY.txt")
    $tagMatch = [regex]::Match($compatText, "refs/tags/((\d+)\.(\d+)\.(\d+)\.(\d+))")
    if (-not $tagMatch.Success) { throw 'Chromium-Tag des Ziel-Commits nicht gefunden.' }
    $targetTag = $tagMatch.Groups[1].Value
    $targetBranch = $tagMatch.Groups[4].Value
    if ($Branch -ne '' -and $Branch -ne $targetBranch) { throw "Commit $Commit gehört zu Branch $targetBranch, nicht $Branch." }
    $Branch = $targetBranch
    Log ("Sync: CEF {0} -> {1} (Chromium {2}, Branch {3})" -f $current.Substring(0, 7), $full.Substring(0, 7), $targetTag, $Branch)
    $srcTag = ''
    try { $srcTag = Invoke-Git $src @('describe', '--tags', '--exact-match') } catch {}
    if ($current -eq $full -and $srcTag -eq $targetTag) {
        Log 'Sync: Checkout steht schon.'
        $times['sync'] = 0
    } else {
        # automate-git ohne Build und ohne Distribution: holt CEF, liest den Tag,
        # setzt Chromium zurück (gclient revert; Nephs Patches kommen in -Patch
        # neu), checkt den Tag aus, gclient sync + runhooks. src\out wandert
        # dabei nach out_<branch> und zurück, der inkrementelle Build bleibt.
        $arguments = @($automate, "--download-dir=$downloadDir", "--depot-tools-dir=$depotTools", '--no-depot-tools-update',
            "--branch=$Branch", "--checkout=$full", '--x64-build', '--no-build', '--no-distrib', '--no-debug-build')
        $fast = -not $Slow
        if ($fast) {
            # Schneller Weg. automate-git --fast-update arbeitet in src\cef selbst,
            # setzt CEFs gepatchte Dateien zurück, checkt den Tag aus, gclient sync
            # ohne Reset, CEF-Patches wieder drauf. Es verlangt einen Baum ohne
            # fremde Änderungen, darum zuerst Nephs Dateien zurück; und src\cef
            # ohne eigene Änderungen (version_manager.py könnte welche hinterlassen).
            # apply.py --revert setzt auch Nephs Datei in src\cef zurück (Patch downloads),
            # darum erst zurücksetzen, dann prüfen.
            $code = Invoke-Logged 'sync-revert' 'python' @((Join-Path $repo 'scripts\chromium-patches\apply.py'), $src, '--revert') $BuildRoot
            if ($code -ne 0) { Log 'apply.py --revert gescheitert (sync-revert.log/.err).'; $fast = $false }
        }
        if ($fast) {
            $cefDirty = Invoke-Git (Join-Path $src 'cef') @('status', '--porcelain', '--untracked-files=no')
            if ($cefDirty -ne '') { Log ("Schneller Weg nicht möglich, src\cef hat Änderungen:`n" + $cefDirty); $fast = $false }
        }
        if ($fast) {
            $code = Invoke-Logged 'sync' 'python' ($arguments + '--fast-update') $BuildRoot
            if ($code -ne 0) { Log 'Schneller Sync gescheitert (sync.log/sync.err); klassischer Weg folgt.'; $fast = $false }
        }
        if (-not $fast) {
            $code = Invoke-Logged 'sync-full' 'python' $arguments $BuildRoot
            if ($code -ne 0) { Write-Times; Log 'Sync gescheitert, siehe sync-full.log/sync-full.err.'; exit $code }
        }
        # Der Checkout neben dem Baum (chromium_git\cef) folgt mit; der Build-Lauf
        # liest dort die Kompatibilitätsdatei.
        if ((Invoke-Git $cefDir @('rev-parse', 'HEAD')) -ne $full) { Invoke-Git $cefDir @('checkout', '--quiet', '--force', $full) | Out-Null }
        $srcTag = Invoke-Git $src @('describe', '--tags', '--exact-match')
        if ($srcTag -ne $targetTag) { Write-Times; Log "Sync: Chromium steht auf $srcTag statt $targetTag."; exit 98 }
        if ((Invoke-Git (Join-Path $src 'cef') @('rev-parse', 'HEAD')) -ne $full) { Write-Times; Log 'Sync: src\cef steht nicht auf dem Ziel-Commit.'; exit 98 }
        Log ("Sync fertig: Chromium {0}, CEF {1}" -f $srcTag, $full.Substring(0, 7))
    }
}

if ($Patch) {
    if ($Branch -eq '') { $Branch = Resolve-Branch }
    # Erst CEFs Patcher (überspringt Angewandtes), dann Nephs Skript, das CEFs
    # Dateien meidet. Reihenfolge wie phase2.cmd (docs/chromium-build.md).
    $code = Invoke-Logged 'patch-cef' 'python' @('tools\patcher.py') (Join-Path $src 'cef')
    if ($code -ne 0) { Write-Times; Log 'CEF-Patcher gescheitert.'; exit $code }
    $applyArguments = @((Join-Path $repo 'scripts\chromium-patches\apply.py'), $src)
    if ($Lenient) { $applyArguments += '--lenient' }
    $code = Invoke-Logged 'patch-neph' 'python' $applyArguments $BuildRoot
    if ($code -ne 0) { Write-Times; Log 'apply.py: Anker nicht gefunden (patch-neph.log). Nicht bauen.'; exit 97 }
    $report = Join-Path $src 'neph-patches.json'
    if (Test-Path -LiteralPath $report) {
        Copy-Item -LiteralPath $report -Destination (Join-Path $LogDir 'neph-patches.json') -Force
        $parsed = Get-Content -LiteralPath $report -Raw | ConvertFrom-Json
        if ($parsed.optional_failed) { foreach ($name in $parsed.optional_failed) { Log ("WARNUNG Kür-Patch ausgefallen: {0} - {1}" -f $name, $parsed.patches.$name) } }
    }
}

if ($Build) {
    if ($Branch -eq '') { $Branch = Resolve-Branch }
    $head = Invoke-Git (Join-Path $src 'cef') @('rev-parse', 'HEAD')
    $arguments = @($automate, "--download-dir=$downloadDir", "--depot-tools-dir=$depotTools", '--no-depot-tools-update', '--no-update',
        "--branch=$Branch", "--checkout=$head", '--x64-build', '--force-build', '--no-debug-build', '--minimal-distrib', '--minimal-distrib-only', '--build-log-file')
    $code = Invoke-Logged 'build' 'python' $arguments $BuildRoot
    $ninjaLog = Join-Path $downloadDir "build-$Branch-release.log"
    if (Test-Path -LiteralPath $ninjaLog) { Copy-Item -LiteralPath $ninjaLog -Destination (Join-Path $LogDir 'ninja-release.log') -Force }
    if ($code -ne 0) { Write-Times; Log 'Build gescheitert, siehe build.log/build.err/ninja-release.log.'; exit $code }
}

if ($Install) {
    $distribRoot = Join-Path $src 'cef\binary_distrib'
    $distrib = Get-ChildItem -LiteralPath $distribRoot -Directory -Filter 'cef_binary_*_windows64_minimal' | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $distrib) { throw "Keine Distribution unter $distribRoot." }
    if (-not (Test-Path -LiteralPath (Join-Path $distrib.FullName 'Release\libcef.dll'))) { throw "Distribution unvollständig: $($distrib.FullName)" }
    $version = [regex]::Match($distrib.Name, '^cef_binary_(.+)_windows64_minimal$').Groups[1].Value
    $chromium = [regex]::Match($version, 'chromium-([\d.]+)$').Groups[1].Value
    $cefCommit = Invoke-Git (Join-Path $src 'cef') @('rev-parse', '--short', 'HEAD')
    $target = Join-Path $repo ('third_party\' + $distrib.Name)
    $marker = Join-Path $target 'NEPH-BUILD.txt'
    if ((Test-Path -LiteralPath $marker) -and ((Get-Item -LiteralPath (Join-Path $target 'Release\libcef.dll')).LastWriteTime -ge (Get-Item -LiteralPath (Join-Path $distrib.FullName 'Release\libcef.dll')).LastWriteTime)) {
        Log ("Install: {0} ist schon eingehängt." -f $distrib.Name)
    } else {
        Log ("Install: {0} -> third_party" -f $distrib.Name)
        $started = Get-Date
        & robocopy $distrib.FullName $target /MIR /NFL /NDL /NJH /NJS /NP | Out-Null
        if ($LASTEXITCODE -ge 8) { throw "robocopy meldete $LASTEXITCODE." }
        $times['install'] = [math]::Round(((Get-Date) - $started).TotalMinutes, 1)
    }
    $patchReport = Join-Path $src 'neph-patches.json'
    $patchText = if (Test-Path -LiteralPath $patchReport) { Get-Content -LiteralPath $patchReport -Raw } else { '(neph-patches.json fehlt)' }
    $header = @(
        "Neph's own CEF build (not the official cef-builds.spotifycdn.com archive).",
        ("Built {0} on this machine from CEF {1} ({2}) / Chromium {3}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm'), $cefCommit, $version.Split('+')[0], $chromium),
        'with scripts/chromium-patches/apply.py (scripts/cef-build.ps1) and',
        ('GN: ' + $GnDefines),
        'Patches: Manifest V2 stays supported; product name "Neph" in every string table (translation ids recomputed);',
        'GPU program cache 64 MB; program-cache scope before MakeCurrent (linked binaries reach the disk cache);',
        'ANGLE D3D11 default output layout with every declared output (no second compile at the first draw);',
        'Widevine CDM component registered only with --neph-widevine (the browser neither ships nor fetches the CDM otherwise).',
        'Saved passwords encrypted by Neph''s vault (master password + TPM-sealed device secret) instead of the OS key (patch vault).',
        'Downloads keep reporting after the tab that started them closed; partial files grow as <name>.crdownload (patch downloads).',
        '', $patchText)
    [IO.File]::WriteAllText($marker, ($header -join "`r`n"), (New-Object Text.UTF8Encoding $true))
    # cef-release.json: fetch-cef.ps1 und CMake finden die Distribution darüber.
    # Der Index-Eintrag derselben Version (cef-watch -Json: release) trägt die
    # offiziellen Dateinamen; ohne ihn ein Eintrag aus dem Ordnernamen.
    $lockPath = Join-Path $repo 'third_party\cef-release.json'
    $entry = $null
    if ($ReleaseJson -ne '' -and (Test-Path -LiteralPath $ReleaseJson)) {
        $watch = Get-Content -LiteralPath $ReleaseJson -Raw | ConvertFrom-Json
        if ($watch.release -and $watch.release.cef_version -eq $version) { $entry = $watch.release }
        elseif ($watch.cef_version -eq $version -and $watch.files) { $entry = $watch }
    }
    if (-not $entry) {
        $entry = [ordered]@{ cef_version = $version; chromium_version = $chromium; channel = 'stable';
            files = @([ordered]@{ type = 'minimal'; name = ($distrib.Name + '.tar.bz2'); sha1 = ''; size = 0; last_modified = (Get-Date).ToUniversalTime().ToString('s') + 'Z' }) }
    }
    $entry | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $lockPath -Encoding UTF8
    Log ("Install fertig: CEF {0} / Chromium {1} in third_party, cef-release.json aktualisiert." -f $version.Split('+')[0], $chromium)
}
Write-Times
Log 'Fertig.'
exit 0
