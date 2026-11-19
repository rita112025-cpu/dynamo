#Requires -Version 5.1
<#
.SYNOPSIS
  Menu for the Dynamo tools listed in launcher/tools.json. Starts Revit 2025 only when it is not already running.

.DESCRIPTION
  Pick one tool from launcher/tools.json and an existing .rvt. This script then calls
  launcher/poc/New-DynamoJournal.ps1 -Launch, which writes a system-ANSI journal with
  no BOM and starts Revit. The graph loads in manual mode and is not run.

  If Revit 2025 is already open, the menu tells you to close it and stops. It does
  not attach to that session.

  Run with Windows PowerShell 5.1. The desktop shortcut created by
  Install-DynamoToolbox.ps1 is the supported way to open this menu.

.EXAMPLE
  powershell.exe -NoProfile -ExecutionPolicy Bypass -STA -File .\launcher\Show-DynamoToolbox.ps1
#>
$ErrorActionPreference = 'Stop'

$script:RevitAlreadyRunningMessage = 'Revit 2025 已在執行中。請先關閉 Revit 再重新開啟。此啟動器不會連接到已開啟的 Revit。'

function Read-Utf8Text([string]$Path) {
  $utf8 = New-Object System.Text.UTF8Encoding $false
  return [System.IO.File]::ReadAllText($Path, $utf8)
}

function Get-DynamoToolboxCatalog {
  $jsonPath = Join-Path $PSScriptRoot 'tools.json'
  if (-not (Test-Path -LiteralPath $jsonPath)) { throw "tools.json not found: $jsonPath" }
  $tools = @((Read-Utf8Text -Path $jsonPath | ConvertFrom-Json).tools)
  if ($tools.Count -lt 1) { throw 'tools.json does not list any tools.' }
  $catalog = @()
  $seen = @{}
  foreach ($tool in $tools) {
    $id = [string]$tool.id
    if ([string]::IsNullOrWhiteSpace($id)) { throw 'tools.json has an entry with no id.' }
    if ($seen.ContainsKey($id)) { throw "tools.json lists ToolId '$id' more than once." }
    $seen[$id] = $true
    if ($tool.PSObject.Properties['hidden'] -and $tool.hidden -eq $true) { continue }
    if ([string]::IsNullOrWhiteSpace($tool.name) -or [string]::IsNullOrWhiteSpace($tool.dyn)) {
      throw "tools.json entry '$id' needs a name and a dyn path."
    }
    $catalog += [pscustomobject]@{
      Id   = $id
      Name = [string]$tool.name
      Dyn  = [string]$tool.dyn
    }
  }
  return $catalog
}

function Test-Revit2025Running {
  $procs = @(Get-Process -Name Revit -ErrorAction SilentlyContinue)
  foreach ($proc in $procs) {
    $path = $proc.Path
    if (-not $path) {
      try { $path = $proc.MainModule.FileName } catch { $path = $null }
    }
    if ($path -and $path -like '*\Revit 2025\*') { return $true }
  }
  return $false
}

function Get-DynamoToolboxRoot {
  return (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
}

function Show-DynamoToolboxForm {
  $desktop = $PSVersionTable.PSEdition -eq 'Desktop'
  $sta = [System.Threading.Thread]::CurrentThread.GetApartmentState() -eq 'STA'
  if (-not $desktop -or -not $sta) {
    $powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    if (-not (Test-Path -LiteralPath $powershell)) {
      throw 'Windows PowerShell 5.1 (powershell.exe) was not found. PowerShell 7 cannot write the system-ANSI journal.'
    }
    $args = '-NoProfile -ExecutionPolicy Bypass -STA -File "{0}"' -f $PSCommandPath
    Start-Process -FilePath $powershell -ArgumentList $args
    return
  }

  # Opt in to DPI awareness before any window exists, so Windows does not bitmap-stretch (blur) the UI.
  if (-not ('DynamoToolboxDpi' -as [type])) {
    Add-Type -TypeDefinition 'using System.Runtime.InteropServices; public static class DynamoToolboxDpi { [DllImport("user32.dll")] public static extern bool SetProcessDPIAware(); }'
  }
  try { [void][DynamoToolboxDpi]::SetProcessDPIAware() } catch { Write-Warning "DPI awareness not enabled: $($_.Exception.Message)" }

  Add-Type -AssemblyName System.Windows.Forms
  Add-Type -AssemblyName System.Drawing
  [System.Windows.Forms.Application]::EnableVisualStyles()

  $fontName = 'Segoe UI'
  $installed = New-Object System.Drawing.Text.InstalledFontCollection
  $families = @($installed.Families | ForEach-Object { $_.Name })
  foreach ($candidate in @('Microsoft JhengHei UI', 'Microsoft JhengHei', 'PMingLiU', 'Segoe UI')) {
    if ($families -contains $candidate) { $fontName = $candidate; break }
  }

  $script:catalog = @(Get-DynamoToolboxCatalog)
  $script:journalScript = Join-Path $PSScriptRoot 'poc\New-DynamoJournal.ps1'
  if (-not (Test-Path -LiteralPath $script:journalScript)) {
    throw "Journal writer not found: $script:journalScript"
  }

  $form = New-Object System.Windows.Forms.Form
  $script:toolboxForm = $form
  $form.Text = 'Dynamo 工具箱'
  $form.FormBorderStyle = 'FixedDialog'
  $form.MaximizeBox = $false
  $form.StartPosition = 'CenterScreen'
  $form.Font = New-Object System.Drawing.Font($fontName, 10)
  $form.AutoScaleMode = [System.Windows.Forms.AutoScaleMode]::Dpi
  $form.ClientSize = New-Object System.Drawing.Size(560, 508)

  $intro = New-Object System.Windows.Forms.Label
  $intro.Location = New-Object System.Drawing.Point(16, 12)
  $intro.Size = New-Object System.Drawing.Size(528, 52)
  $intro.Text = '選擇一個工具與一個既有的 .rvt。Revit 2025 必須先關閉。圖形會以手動模式載入，不會自動執行。'
  $form.Controls.Add($intro)

  $toolLabel = New-Object System.Windows.Forms.Label
  $toolLabel.Location = New-Object System.Drawing.Point(16, 72)
  $toolLabel.Size = New-Object System.Drawing.Size(528, 20)
  $toolLabel.Text = '工具'
  $form.Controls.Add($toolLabel)

  $script:toolList = New-Object System.Windows.Forms.ListBox
  $script:toolList.Location = New-Object System.Drawing.Point(16, 96)
  $script:toolList.Size = New-Object System.Drawing.Size(528, 168)
  $script:toolList.IntegralHeight = $false
  foreach ($tool in $script:catalog) {
    [void]$script:toolList.Items.Add($tool.Name)
  }
  $script:toolList.SelectedIndex = 0
  $form.Controls.Add($script:toolList)

  $projectLabel = New-Object System.Windows.Forms.Label
  $projectLabel.Location = New-Object System.Drawing.Point(16, 276)
  $projectLabel.Size = New-Object System.Drawing.Size(528, 20)
  $projectLabel.Text = '既有專案 (.rvt)'
  $form.Controls.Add($projectLabel)

  $script:projectBox = New-Object System.Windows.Forms.TextBox
  $script:projectBox.Location = New-Object System.Drawing.Point(16, 300)
  $script:projectBox.Size = New-Object System.Drawing.Size(400, 24)
  $form.Controls.Add($script:projectBox)

  $browse = New-Object System.Windows.Forms.Button
  $browse.Location = New-Object System.Drawing.Point(424, 298)
  $browse.Size = New-Object System.Drawing.Size(120, 28)
  $browse.Text = '瀏覽(&B)...'
  $browse.Add_Click({
    $dialog = New-Object System.Windows.Forms.OpenFileDialog
    $dialog.Filter = 'Revit 專案 (*.rvt)|*.rvt'
    $dialog.Title = '選擇既有的 Revit 專案'
    $dialog.CheckFileExists = $true
    $dialog.Multiselect = $false
    if ($dialog.ShowDialog($script:toolboxForm) -eq [System.Windows.Forms.DialogResult]::OK) {
      $script:projectBox.Text = $dialog.FileName
    }
  })
  $form.Controls.Add($browse)

  $hint = New-Object System.Windows.Forms.Label
  $hint.Location = New-Object System.Drawing.Point(16, 340)
  $hint.Size = New-Object System.Drawing.Size(528, 48)
  $hint.Text = '不會開啟樣板 (.rte)。若 Revit 2025 已在執行，請先關閉再按「啟動」。'
  $form.Controls.Add($hint)

  $launch = New-Object System.Windows.Forms.Button
  $launch.Location = New-Object System.Drawing.Point(16, 408)
  $launch.Size = New-Object System.Drawing.Size(140, 32)
  $launch.Text = '啟動(&L)'
  $launch.Add_Click({
    $index = $script:toolList.SelectedIndex
    if ($index -lt 0 -or $index -ge $script:catalog.Count) {
      [System.Windows.Forms.MessageBox]::Show($script:toolboxForm, '請選擇一個工具。', 'Dynamo 工具箱', [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Warning) | Out-Null
      return
    }
    $project = $script:projectBox.Text.Trim().Trim('"')
    $extension = [System.IO.Path]::GetExtension($project)
    $isRvt = $extension -and $extension.Equals('.rvt', [System.StringComparison]::OrdinalIgnoreCase)
    if (-not $isRvt -or -not (Test-Path -LiteralPath $project -PathType Leaf)) {
      [System.Windows.Forms.MessageBox]::Show($script:toolboxForm, '請選擇既有的 .rvt 檔案。不會開啟樣板 (.rte)。', 'Dynamo 工具箱', [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Warning) | Out-Null
      return
    }
    if (Test-Revit2025Running) {
      [System.Windows.Forms.MessageBox]::Show($script:toolboxForm, $script:RevitAlreadyRunningMessage, '請先關閉 Revit', [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Warning) | Out-Null
      return
    }
    try {
      & $script:journalScript -ToolId $script:catalog[$index].Id -Project $project -Launch
    } catch {
      [System.Windows.Forms.MessageBox]::Show($script:toolboxForm, $_.Exception.Message, 'Dynamo 工具箱', [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Warning) | Out-Null
      return
    }
    $script:toolboxForm.Close()
  })
  $form.Controls.Add($launch)

  $close = New-Object System.Windows.Forms.Button
  $close.Location = New-Object System.Drawing.Point(168, 408)
  $close.Size = New-Object System.Drawing.Size(140, 32)
  $close.Text = '關閉(&C)'
  $close.Add_Click({ $script:toolboxForm.Close() })
  $form.Controls.Add($close)

  $form.AcceptButton = $launch
  $form.CancelButton = $close
  [void]$form.ShowDialog()
}

if ($MyInvocation.InvocationName -ne '.') {
  Show-DynamoToolboxForm
}
