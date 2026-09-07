$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$manifest = Get-Content -LiteralPath (Join-Path $project 'extension\manifest.json') -Raw | ConvertFrom-Json
$sha = [System.Security.Cryptography.SHA256]::Create().ComputeHash([Convert]::FromBase64String($manifest.key))
$hex = -join ($sha[0..15] | ForEach-Object { $_.ToString('x2') })
$extensionId = -join ($hex.ToCharArray() | ForEach-Object { [char]([int][char]'a' + [Convert]::ToInt32($_.ToString(), 16)) })
$origin = "chrome-extension://$extensionId/"
function Write-Utf8NoBom([string]$Path, [string]$Value) {
  [System.IO.File]::WriteAllText($Path, $Value, (New-Object System.Text.UTF8Encoding($false)))
}

$python = $null
try { $python = (& py.exe -3 -c "import sys; print(sys.executable)" 2>$null | Select-Object -First 1) } catch {}
if (-not $python) {
  try { $python = (& python.exe -c "import sys; print(sys.executable)" 2>$null | Select-Object -First 1) } catch {}
}
if (-not $python -or -not (Test-Path -LiteralPath $python)) {
  throw 'Python 3 not found. Install Python 3 from python.org, then run install.cmd again.'
}

$root = Join-Path $env:LOCALAPPDATA 'ClashSiteRule'
New-Item -ItemType Directory -Force -Path $root | Out-Null
Copy-Item -LiteralPath (Join-Path $project 'native\host.py') -Destination (Join-Path $root 'host.py') -Force
Write-Utf8NoBom (Join-Path $root 'launcher.txt') ($python + [Environment]::NewLine + (Join-Path $root 'host.py'))

$cscCandidates = @(
  "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe",
  "$env:WINDIR\Microsoft.NET\Framework\v4.0.30319\csc.exe"
)
$csc = $cscCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $csc) { throw '.NET Framework C# compiler not found.' }
& $csc /nologo /target:exe "/out:$root\host.exe" (Join-Path $project 'native\windows_launcher.cs')
if ($LASTEXITCODE -ne 0) { throw 'Failed to compile the native messaging launcher.' }

$settingsPath = Join-Path $root 'settings.json'
if (Test-Path -LiteralPath $settingsPath) {
  $settings = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json
} else {
  $settings = [ordered]@{ secret = ''; controller = ''; profile_path = ''; clash_home = '' }
}
if ($settings.PSObject.Properties.Name -contains 'origin') {
  $settings.origin = $origin
} else {
  $settings | Add-Member -NotePropertyName origin -NotePropertyValue $origin
}
$settingsJson = $settings | ConvertTo-Json
Write-Utf8NoBom $settingsPath $settingsJson

$hostManifest = Join-Path $root 'local.clash_site_rule.json'
$hostManifestJson = @{
  name = 'local.clash_site_rule'
  description = 'Clash site rule editor'
  path = (Join-Path $root 'host.exe')
  type = 'stdio'
  allowed_origins = @($origin)
} | ConvertTo-Json
Write-Utf8NoBom $hostManifest $hostManifestJson
$key = 'HKCU:\Software\Google\Chrome\NativeMessagingHosts\local.clash_site_rule'
New-Item -Force -Path $key | Out-Null
Set-Item -LiteralPath $key -Value $hostManifest

Write-Host "Native helper installed. Extension ID: $extensionId"
Write-Host 'Open chrome://extensions, enable Developer mode, click Load unpacked, and select:'
Write-Host (Join-Path $project 'extension')
