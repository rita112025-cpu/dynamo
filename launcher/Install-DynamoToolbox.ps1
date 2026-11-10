#Requires -Version 5.1
<#
.SYNOPSIS
  Create a desktop shortcut that opens the five-tool Dynamo menu.

.DESCRIPTION
  Writes "Dynamo Toolbox" on the current user's desktop. The shortcut starts
  Windows PowerShell 5.1, which opens launcher/Show-DynamoToolbox.ps1.
  Run this again if the repository folder moves. It does not start Revit and
  it does not modify any .dyn file or project.

.EXAMPLE
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\launcher\Install-DynamoToolbox.ps1
#>
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'Show-DynamoToolbox.ps1')

function Get-DynamoToolboxShortcutSpec {
  $menuPath = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'Show-DynamoToolbox.ps1')).Path
  $journalPath = Join-Path $PSScriptRoot 'poc\New-DynamoJournal.ps1'
  if (-not (Test-Path -LiteralPath $journalPath)) { throw "Journal writer not found: $journalPath" }
  if ([string]::IsNullOrWhiteSpace($env:SystemRoot)) {
    throw 'Windows system directory was not found. Run this installer on Windows with Windows PowerShell 5.1.'
  }
  $powershell = $env:SystemRoot.TrimEnd('\') + '\System32\WindowsPowerShell\v1.0\powershell.exe'
  [pscustomobject]@{
    Powershell       = $powershell
    MenuPath         = $menuPath
    WorkingDirectory = (Get-DynamoToolboxRoot)
    Arguments        = '-NoProfile -ExecutionPolicy Bypass -STA -File "{0}"' -f $menuPath
    Description      = 'Open an existing Revit project and one Dynamo tool in manual mode. Close Revit 2025 first.'
    Name             = 'Dynamo Toolbox.lnk'
  }
}

function Install-DynamoToolboxShortcut {
  $spec = Get-DynamoToolboxShortcutSpec
  if (-not (Test-Path -LiteralPath $spec.Powershell)) {
    throw 'Windows PowerShell 5.1 (powershell.exe) was not found. The shortcut is not created for PowerShell 7.'
  }

  $catalog = @(Get-DynamoToolboxCatalog)
  foreach ($tool in $catalog) {
    $dyn = Join-Path $spec.WorkingDirectory ($tool.Dyn -replace '/', '\')
    if (-not (Test-Path -LiteralPath $dyn)) { throw ".dyn not found: $dyn" }
  }

  $desktop = [Environment]::GetFolderPath('Desktop')
  if ([string]::IsNullOrWhiteSpace($desktop)) { throw 'The current user desktop folder was not found.' }
  $shortcutPath = Join-Path $desktop $spec.Name
  $existed = Test-Path -LiteralPath $shortcutPath

  $shell = New-Object -ComObject WScript.Shell
  $link = $shell.CreateShortcut($shortcutPath)
  $link.TargetPath = $spec.Powershell
  $link.Arguments = $spec.Arguments
  $link.WorkingDirectory = $spec.WorkingDirectory
  $link.Description = $spec.Description
  $link.WindowStyle = 1
  $link.Save()

  Write-Host ("Tools   : " + (($catalog | ForEach-Object { $_.Id }) -join ', '))
  Write-Host "Shortcut: $shortcutPath"
  if ($existed) {
    Write-Host 'Updated the existing desktop shortcut.'
  } else {
    Write-Host 'Created the desktop shortcut.'
  }
  Write-Host 'Close Revit 2025 before opening the shortcut. The graph loads in manual mode and does not run.'
}

if ($MyInvocation.InvocationName -ne '.') {
  Install-DynamoToolboxShortcut
}
