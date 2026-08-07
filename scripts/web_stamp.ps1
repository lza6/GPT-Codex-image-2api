# Compute a fingerprint of the frontend build inputs (source + version + key configs).
# Any change to these invalidates the cached web_dist build and triggers a rebuild.
# Pure ASCII on purpose: PowerShell 5.1 reads a BOM-less .ps1 as the system ANSI codepage.
$ErrorActionPreference = 'SilentlyContinue'
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root

$items = @()
$items += Get-Item 'VERSION', 'CHANGELOG.md'
# web 根配置（next.config.ts/tsconfig/package.json/locks/tailwind 等）；
# 排除构建自动再生成物（next-env.d.ts、*.tsbuildinfo），它们的 mtime 每次 build 都变、不代表源码改动
$items += Get-ChildItem 'web' -File | Where-Object { $_.Name -ne 'next-env.d.ts' -and $_.Name -notlike '*.tsbuildinfo' }
# source + static assets
$items += Get-ChildItem 'web\src', 'web\public' -Recurse -File

$content = ($items | Sort-Object FullName | ForEach-Object {
    '{0}|{1}|{2}' -f $_.FullName.Substring($root.Length), $_.Length, $_.LastWriteTimeUtc.Ticks
}) -join "`n"

$sha = [System.Security.Cryptography.SHA256]::Create()
$hash = [BitConverter]::ToString($sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($content))) -replace '-', ''
Pop-Location
Write-Output $hash
