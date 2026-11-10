<#
.SYNOPSIS
  Generate a Revit 2025 journal that opens a user-selected .rvt, then opens a Dynamo graph in MANUAL mode (no Run).

.DESCRIPTION
  Read-only toward the repo and any model: it only writes one journal file under
  %LOCALAPPDATA%\DynamoToolbox\journals. It starts Revit ONLY when -Launch is given
  and no Revit 2025 process is already running.

  The journal matches the playback shape verified on Revit 2025.5: system ANSI code
  page, no byte-order mark, CRLF, one statement per line. It opens -Project with
  Jrn.Command "AccelKey" , "Open , ID_REVIT_FILE_OPEN", then loads the tool's .dyn
  with the UI shown and Run forced off (dynPathExecute=False, dynAutomation=False,
  dynForceManualRun=True, dynShowUI=True). It does not open an .rte template and it
  does not start Dynamo without a document.

  Before writing, the journal text is round-tripped through the system ANSI code
  page. If any character cannot be represented, the script stops and does not
  substitute '?'. Chinese paths on an English ANSI code page (such as cp1252) fail
  this check. Traditional Chinese Windows (cp950) can store those paths.

  Run with Windows PowerShell 5.1. Encoding.Default there is the system ANSI code
  page. PowerShell 7 reports UTF-8 as Default, and this script refuses to write that.

  When -Launch is set and Revit 2025 is already running, the script stops before
  writing and tells you to close Revit. It does not attach to that session.
  The desktop menu (launcher/Show-DynamoToolbox.ps1) is the supported way to call
  this script. Install it with launcher/Install-DynamoToolbox.ps1.

.PARAMETER ToolId
  Toolbox id from launcher/tools.json. The .dyn path is taken from that mapping.

.PARAMETER Project
  Full path of the existing .rvt to open before Dynamo.

.PARAMETER Launch
  Start Revit 2025 and play the generated journal.

.EXAMPLE
  .\New-DynamoJournal.ps1 -ToolId excel-sync -Project C:\Models\project.rvt

.EXAMPLE
  .\New-DynamoJournal.ps1 -ToolId excel-sync -Project C:\Models\project.rvt -Launch
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$ToolId,
  [Parameter(Mandatory)][string]$Project,
  [switch]$Launch
)
$ErrorActionPreference = 'Stop'

$root  = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$tools = (Get-Content -Raw -Encoding UTF8 (Join-Path $PSScriptRoot '..\tools.json') | ConvertFrom-Json).tools
$tool  = $tools | Where-Object id -eq $ToolId
if (-not $tool) { throw "Unknown ToolId '$ToolId'. Valid: $($tools.id -join ', ')" }

$dyn = Join-Path $root ($tool.dyn -replace '/', '\')
if (-not (Test-Path -LiteralPath $dyn)) { throw ".dyn not found: $dyn" }

if ([string]::IsNullOrWhiteSpace($Project)) { throw 'Pass -Project with the .rvt file to open.' }
if (-not (Test-Path -LiteralPath $Project -PathType Leaf)) { throw "Project not found: $Project" }
if (-not [System.IO.Path]::GetExtension($Project).Equals('.rvt', [System.StringComparison]::OrdinalIgnoreCase)) {
  throw 'Project must be an existing .rvt file. This journal does not open an .rte template.'
}
$projectPath = (Resolve-Path -LiteralPath $Project).Path

# Revit 2025 install location from registry (no hard-coded path)
$revitExe = $null
foreach ($k in Get-ChildItem 'HKLM:\SOFTWARE\Autodesk\Revit\2025*' -ErrorAction SilentlyContinue) {
  $loc = (Get-ItemProperty $k.PSPath -ErrorAction SilentlyContinue).InstallationLocation
  if ($loc -and (Test-Path (Join-Path $loc 'Revit.exe'))) { $revitExe = Join-Path $loc 'Revit.exe'; break }
}
if (-not $revitExe) {
  $cand = Join-Path $env:ProgramFiles 'Autodesk\Revit 2025\Revit.exe'
  if (Test-Path $cand) { $revitExe = $cand }
}
if (-not $revitExe) { throw 'Revit 2025 not found (registry and default path).' }

# VBScript string escaping: double any double-quote
function Q([string]$s) { '"' + ($s -replace '"', '""') + '"' }

function Test-Revit2025Running([string]$ExpectedPath) {
  $procs = @(Get-Process -Name Revit -ErrorAction SilentlyContinue)
  foreach ($proc in $procs) {
    $path = $proc.Path
    if (-not $path) {
      try { $path = $proc.MainModule.FileName } catch { $path = $null }
    }
    if (-not $path) { continue }
    if ($ExpectedPath -and ($path -eq $ExpectedPath)) { return $true }
    if ($path -like '*\Revit 2025\*') { return $true }
  }
  return $false
}

# Round-trip through the encoding that will be written. Replacement fallback turns
# an unmappable character into '?', so a mismatch means the journal would be wrong.
function Assert-AnsiJournalRoundTrip([string]$text, [System.Text.Encoding]$encoding) {
  if ($encoding.CodePage -eq 65001 -or $encoding.GetPreamble().Length -gt 0) {
    throw 'Refusing to write the journal: Encoding.Default is UTF-8 or has a BOM. Run this script with Windows PowerShell 5.1 so it uses the system ANSI code page.'
  }
  $round = $encoding.GetString($encoding.GetBytes($text))
  if ($round -eq $text) { return }

  $index = 0
  $limit = [Math]::Min($text.Length, $round.Length)
  while ($index -lt $limit -and $text[$index] -eq $round[$index]) { $index++ }
  $char = if ($index -lt $text.Length) { $text[$index] } else { '?' }
  $code = '{0:X4}' -f [int][char]$char
  throw "Refusing to write the journal: '$char' (U+$code) cannot be represented in the system ANSI code page (cp$($encoding.CodePage)). The writer does not substitute '?'. Chinese paths on an English ANSI code page (such as cp1252) cannot be stored in this journal. Move the .rvt and this toolbox onto a path whose characters exist in cp$($encoding.CodePage). Traditional Chinese Windows uses cp950."
}

$lines = @(
  "' Generated by New-DynamoJournal.ps1 (manual mode)",
  'Dim Jrn',
  'Set Jrn = CrsJournalScript',
  'Jrn.Command "AccelKey" , "Open , ID_REVIT_FILE_OPEN"',
  ('Jrn.Data "File Name" , "IDOK" , {0}' -f (Q $projectPath)),
  'Jrn.Command "Ribbon" , "Dynamo , ID_VISUAL_PROGRAMMING_DYNAMO"',
  ('Jrn.Data "APIStringStringMapJournalData" , 5 , "dynShowUI" , "True" , "dynAutomation" , "False" , "dynPath" , {0} , "dynPathExecute" , "False" , "dynForceManualRun" , "True"' -f (Q $dyn))
)

$outDir = Join-Path $env:LOCALAPPDATA 'DynamoToolbox\journals'
New-Item -ItemType Directory -Force $outDir | Out-Null
$journal = Join-Path $outDir ("{0}_{1:yyyyMMdd_HHmmss}.txt" -f $ToolId, (Get-Date))

if ($Launch -and (Test-Revit2025Running -ExpectedPath $revitExe)) {
  throw 'Revit 2025 is already running. Close Revit, then run this again. This launcher does not attach to an open Revit session.'
}

# System ANSI, no BOM. On Windows PowerShell 5.1, Encoding.Default is the active
# ANSI code page. GetBytes does not emit a preamble. A UTF-8 BOM (EF BB BF) or a
# UTF-16 BOM makes Revit 2025 ignore the file and start normally.
$encoding = [System.Text.Encoding]::Default
$body = ($lines -join "`r`n") + "`r`n"
Assert-AnsiJournalRoundTrip -text $body -encoding $encoding
[System.IO.File]::WriteAllBytes($journal, $encoding.GetBytes($body))

Write-Host "Revit   : $revitExe"
Write-Host "Project : $projectPath"
Write-Host "Dyn     : $dyn"
Write-Host "Journal : $journal"
Write-Host ("CodePage: {0} (system ANSI, no BOM)" -f $encoding.CodePage)

if ($Launch) {
  Start-Process -FilePath $revitExe -ArgumentList ('"{0}"' -f $journal)
}
