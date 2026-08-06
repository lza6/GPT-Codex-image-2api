# Compute a fingerprint of the frontend build inputs (source + version + key configs).
# Any change to these invalidates the cached web_dist build and triggers a rebuild.
# Pure ASCII on purpose: PowerShell 5.1 reads a BOM-less .ps1 as the system ANSI codepage.
$ErrorActionPreference = 'SilentlyContinue'
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root

$items = @()
$items += Get-Item 'VERSION', 'CHANGELOG.md'
# web root config files (next.config.ts, tsconfig, tailwind/postcss config, package.json, locks, ...)
$items += Get-ChildItem 'web' -File
# source + static assets
$items += Get-ChildItem 'web\src', 'web\public' -Recurse -File

$content = ($items | Sort-Object FullName | ForEach-Object {
    '{0}|{1}|{2}' -f $_.FullName.Substring($root.Length), $_.Length, $_.LastWriteTimeUtc.Ticks
}) -join "`n"

$sha = [System.Security.Cryptography.SHA256]::Create()
$hash = [BitConverter]::ToString($sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($content))) -replace '-', ''
Pop-Location
Write-Output $hash
