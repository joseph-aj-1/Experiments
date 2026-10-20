<#
Builds the Magic MCP Bridge plugin and (optionally) installs it into Catia Magic.

  .\build.ps1                                  # auto-detect Catia Magic, build only
  .\build.ps1 -Install                         # build + copy into <Catia Magic>\plugins (run as Administrator if under Program Files)
  .\build.ps1 -MagicHome "D:\Apps\Catia Magic SoS Architect 2024x" -Install

Needs a JDK 11+ (javac) on PATH or in JAVA_HOME.
Close Catia Magic before -Install, then start it again to load the plugin.
#>
param(
    [string]$MagicHome = "",
    [switch]$Install
)
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

# --- locate Catia Magic -------------------------------------------------
if (-not $MagicHome) {
    $roots = @($env:ProgramFiles, ${env:ProgramFiles(x86)}, "C:\", "D:\", "E:\") | Where-Object { $_ -and (Test-Path $_) }
    $candidates = foreach ($r in $roots) {
        Get-ChildItem -Path $r -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match "Magic|Cameo|Systems of Systems" -and (Test-Path (Join-Path $_.FullName "lib\md_api.jar")) }
    }
    $candidates = @($candidates | Sort-Object LastWriteTime -Descending)
    if ($candidates.Count -eq 0) { throw "Could not find Catia Magic. Pass -MagicHome '<install folder that contains lib\md_api.jar>'." }
    if ($candidates.Count -gt 1) {
        Write-Host "Found several installs, using the newest:" -ForegroundColor Yellow
        $candidates | ForEach-Object { Write-Host "  $($_.FullName)" }
    }
    $MagicHome = $candidates[0].FullName
}
if (-not (Test-Path (Join-Path $MagicHome "lib\md_api.jar"))) { throw "$MagicHome does not look like a Catia Magic install (no lib\md_api.jar)." }
Write-Host "Catia Magic: $MagicHome"

# --- locate javac ---------------------------------------------------------
$javac = (Get-Command javac -ErrorAction SilentlyContinue).Source
if (-not $javac -and $env:JAVA_HOME) { $javac = Join-Path $env:JAVA_HOME "bin\javac.exe" }
if (-not $javac -or -not (Test-Path $javac)) { throw "javac not found. Install a JDK 11+ (e.g. Temurin) or set JAVA_HOME." }

# --- compile ----------------------------------------------------------------
$out = Join-Path $here "build"
$classes = Join-Path $out "classes"
Remove-Item $out -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $classes | Out-Null

$cp = (Join-Path $MagicHome "lib\*") + ";" + (Join-Path $MagicHome "lib\bundles\*")
$sources = Get-ChildItem -Path (Join-Path $here "src") -Recurse -Filter *.java | ForEach-Object { $_.FullName }
& $javac --release 11 -encoding UTF-8 -nowarn -cp $cp -d $classes @sources
if ($LASTEXITCODE -ne 0) { throw "Compile failed." }

$pluginDir = Join-Path $out "com.arun.magicbridge"
New-Item -ItemType Directory -Force -Path $pluginDir | Out-Null

# Package the .jar (a zip with a manifest) directly, so no jar.exe is needed.
# Oracle's "javapath" shortcut on PATH ships javac.exe but not jar.exe.
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$jarPath = Join-Path $pluginDir "magicbridge.jar"
$zip = [System.IO.Compression.ZipFile]::Open($jarPath, [System.IO.Compression.ZipArchiveMode]::Create)
try {
    $entry = $zip.CreateEntry("META-INF/MANIFEST.MF")
    $w = New-Object System.IO.StreamWriter($entry.Open())
    $w.Write("Manifest-Version: 1.0`r`nCreated-By: build.ps1`r`n`r`n")
    $w.Close()
    $root = (Resolve-Path $classes).Path.TrimEnd('\') + '\'
    Get-ChildItem -Path $classes -Recurse -File | ForEach-Object {
        $name = $_.FullName.Substring($root.Length).Replace('\', '/')
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $_.FullName, $name) | Out-Null
    }
} finally {
    $zip.Dispose()
}
Copy-Item (Join-Path $here "plugin.xml") $pluginDir
Write-Host "Built: $pluginDir" -ForegroundColor Green

# --- install ------------------------------------------------------------------
if ($Install) {
    $target = Join-Path $MagicHome "plugins\com.arun.magicbridge"
    New-Item -ItemType Directory -Force -Path $target | Out-Null
    Copy-Item (Join-Path $pluginDir "*") $target -Force
    Write-Host "Installed to $target. Restart Catia Magic." -ForegroundColor Green
}
