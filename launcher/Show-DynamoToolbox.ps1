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

  Before the window is created, the menu asks Windows for per-monitor DPI awareness
  so powershell.exe is not bitmap-stretched on a scaled display. Layout is a
  TableLayoutPanel with point-sized fonts and AutoScaleMode.Dpi. Pixel padding is
  computed from the form DeviceDpi. Moving the window onto a monitor with a
  different scale is best-effort: .NET Framework WinForms (the Windows PowerShell
  5.1 runtime) does not get a PerMonitorV2 app.config for powershell.exe, so
  cross-monitor rescaling is not the same as a current .NET WinForms app.

.EXAMPLE
  powershell.exe -NoProfile -ExecutionPolicy Bypass -STA -File .\launcher\Show-DynamoToolbox.ps1
#>
$ErrorActionPreference = 'Stop'

$script:RevitAlreadyRunningMessage = 'Revit 2025 is already running. Close Revit, then run this again. This launcher does not attach to an open Revit session.'

# Captured when this file is executed or dot-sourced. Install-DynamoToolbox.ps1
# dot-sources this file from the same folder; $PSCommandPath still points here.
if ($PSCommandPath) {
  $script:DynamoToolboxLauncherDir = Split-Path -Parent $PSCommandPath
} else {
  $script:DynamoToolboxLauncherDir = $PSScriptRoot
}

function Read-Utf8Text([string]$Path) {
  $utf8 = New-Object System.Text.UTF8Encoding $false
  return [System.IO.File]::ReadAllText($Path, $utf8)
}

function Get-DynamoToolboxLauncherDir {
  if (-not [string]::IsNullOrWhiteSpace($script:DynamoToolboxLauncherDir)) {
    return $script:DynamoToolboxLauncherDir
  }
  return $PSScriptRoot
}

function Get-DynamoToolboxCatalog {
  $jsonPath = Join-Path (Get-DynamoToolboxLauncherDir) 'tools.json'
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
  return (Resolve-Path -LiteralPath (Join-Path (Get-DynamoToolboxLauncherDir) '..')).Path
}

# Returns a warning (Message, Title) or $null when the tool index and project
# path pass. Same checks, same order, and same strings as the Launch button.
# Revit-already-running stays in the button handler so this function does not
# start Revit or call the journal script.
function Get-DynamoToolboxLaunchWarning {
  param(
    [int]$ToolIndex,
    [int]$ToolCount,
    [AllowEmptyString()][string]$ProjectText
  )
  if ($ToolIndex -lt 0 -or $ToolIndex -ge $ToolCount) {
    return [pscustomobject]@{
      Message = 'Pick one tool.'
      Title   = 'Dynamo toolbox'
    }
  }
  if ($null -eq $ProjectText) { $ProjectText = '' }
  $project = $ProjectText.Trim().Trim('"')
  $extension = [System.IO.Path]::GetExtension($project)
  $isRvt = $extension -and $extension.Equals('.rvt', [System.StringComparison]::OrdinalIgnoreCase)
  if (-not $isRvt -or -not (Test-Path -LiteralPath $project -PathType Leaf)) {
    return [pscustomobject]@{
      Message = 'Choose an existing .rvt file. Templates (.rte) are not opened.'
      Title   = 'Dynamo toolbox'
    }
  }
  return $null
}

function Initialize-DynamoToolboxNative {
  if ('DynamoToolboxNative' -as [type]) { return }
  $code = @'
using System;
using System.Runtime.InteropServices;
public static class DynamoToolboxNative {
    [DllImport("user32.dll", SetLastError = true)]
    public static extern bool SetProcessDpiAwarenessContext(IntPtr value);

    [DllImport("shcore.dll", SetLastError = true)]
    public static extern int SetProcessDpiAwareness(int awareness);

    [DllImport("user32.dll", SetLastError = true)]
    public static extern bool SetProcessDPIAware();

    [DllImport("user32.dll", SetLastError = true)]
    public static extern IntPtr SetThreadDpiAwarenessContext(IntPtr value);

    [DllImport("user32.dll", SetLastError = true)]
    public static extern IntPtr GetThreadDpiAwarenessContext();

    [DllImport("user32.dll", SetLastError = true)]
    public static extern bool AreDpiAwarenessContextsEqual(IntPtr a, IntPtr b);

    [DllImport("user32.dll", SetLastError = true)]
    public static extern int GetAwarenessFromDpiAwarenessContext(IntPtr value);
}
'@
  try {
    Add-Type -TypeDefinition $code -ErrorAction Stop
  } catch {
    # Already defined in this AppDomain, or this Windows build has no C# compiler.
  }
}

function Initialize-DynamoToolboxFormType {
  if ('DynamoToolboxForm' -as [type]) { return }
  # WM_DPICHANGED (0x02E0). .NET Framework raises Form.DpiChanged only when
  # powershell.exe.config opts into PerMonitorV2, which we do not ship. This
  # subclass still forwards that message so the layout can be rebuilt.
  $code = @'
using System;
using System.Windows.Forms;
public class DynamoToolboxForm : Form {
    public event EventHandler DpiWorkaround;
    protected override void WndProc(ref Message m) {
        bool dpiMessage = (m.Msg == 0x02E0);
        base.WndProc(ref m);
        if (dpiMessage && DpiWorkaround != null) {
            DpiWorkaround(this, EventArgs.Empty);
        }
    }
}
'@
  try {
    $winForms = [System.Windows.Forms.Form].Assembly.Location
    $drawing = [System.Drawing.Font].Assembly.Location
    Add-Type -TypeDefinition $code -ReferencedAssemblies @($winForms, $drawing) -ErrorAction Stop
  } catch {
    # Fall back to a normal Form. DpiChanged is still hooked when it exists.
  }
}

# Process default first (V2, then per-monitor, then system). Failures such as
# ACCESS_DENIED, an awareness mode that is already set, or a missing entry
# point on older Windows are ignored. The thread is then set to V2 because a
# console HWND may have locked the process default before this script ran.
function Enable-DynamoToolboxDpiAwareness {
  Initialize-DynamoToolboxNative
  if (-not ('DynamoToolboxNative' -as [type])) { return }

  $perMonitorV2 = [System.IntPtr]::new(-4)
  $processSet = $false
  try {
    $processSet = [bool][DynamoToolboxNative]::SetProcessDpiAwarenessContext($perMonitorV2)
  } catch {
    $processSet = $false
  }
  if (-not $processSet) {
    try {
      $hr = [DynamoToolboxNative]::SetProcessDpiAwareness(2)
      if ($hr -eq 0) { $processSet = $true }
    } catch {
    }
  }
  if (-not $processSet) {
    try { [void][DynamoToolboxNative]::SetProcessDPIAware() } catch { }
  }
  try { [void][DynamoToolboxNative]::SetThreadDpiAwarenessContext($perMonitorV2) } catch { }
}

function Enable-DynamoToolboxVisualStyles {
  Add-Type -AssemblyName System.Windows.Forms
  Add-Type -AssemblyName System.Drawing
  [System.Windows.Forms.Application]::EnableVisualStyles()
  try {
    [System.Windows.Forms.Application]::SetCompatibleTextRenderingDefault($false)
  } catch {
    # Already called, or some other window already exists in this process.
  }
}

function Get-DynamoToolboxFontName {
  $installed = New-Object System.Drawing.Text.InstalledFontCollection
  try {
    $families = @($installed.Families | ForEach-Object { $_.Name })
    foreach ($candidate in @('Microsoft JhengHei UI', 'Microsoft JhengHei', 'PMingLiU', 'Segoe UI')) {
      if ($families -contains $candidate) { return $candidate }
    }
  } finally {
    $installed.Dispose()
  }
  return 'Segoe UI'
}

function ConvertTo-DynamoToolboxPx {
  param([int]$Px, [int]$Dpi)
  if ($Dpi -lt 96) { $Dpi = 96 }
  return [int][Math]::Round($Px * $Dpi / 96.0)
}

function Get-DynamoToolboxDeviceDpi {
  param($Control)
  if ($null -eq $Control) { return 96 }
  $prop = $Control.GetType().GetProperty('DeviceDpi')
  if ($prop) {
    try {
      $value = [int]$prop.GetValue($Control, $null)
      if ($value -gt 0) { return $value }
    } catch {
    }
  }
  try {
    $graphics = $Control.CreateGraphics()
    try { return [int][Math]::Round($graphics.DpiX) } finally { $graphics.Dispose() }
  } catch {
    return 96
  }
}

function New-DynamoToolboxFont {
  param(
    [string]$Family,
    [single]$SizePt,
    [System.Drawing.FontStyle]$Style = 'Regular'
  )
  return New-Object System.Drawing.Font($Family, $SizePt, $Style, [System.Drawing.GraphicsUnit]::Point)
}

function New-DynamoToolboxPadding {
  param([int]$Left, [int]$Top, [int]$Right, [int]$Bottom)
  return New-Object System.Windows.Forms.Padding($Left, $Top, $Right, $Bottom)
}

function Set-DynamoToolboxRowStyle {
  param($Table, [int]$Index, $Type, [single]$Height)
  $style = $Table.RowStyles[$Index]
  $style.SizeType = $Type
  $style.Height = $Height
}

# Rebuild device-pixel metrics for the current DPI. Safe to call more than once.
# Cross-monitor changes are best-effort; see the comment on Show-DynamoToolboxForm.
function Sync-DynamoToolboxLayout {
  param(
    $Form,
    [int]$Dpi = 0
  )
  if ($script:DynamoToolboxLayoutBusy) { return }
  if ($null -eq $script:DynamoToolboxUi) { return }
  $ui = $script:DynamoToolboxUi
  if ($ui.Form -ne $Form) { return }

  $script:DynamoToolboxLayoutBusy = $true
  try {
    if ($Dpi -le 0) { $Dpi = Get-DynamoToolboxDeviceDpi -Control $Form }
    if ($Dpi -lt 96) { $Dpi = 96 }

    $fontName = [string]$ui.FontName
    $body = New-DynamoToolboxFont -Family $fontName -SizePt 10
    $Form.Font = $body
    $ui.List.Font = $body
    $ui.ProjectBox.Font = $body
    $ui.Launch.Font = $body
    $ui.Close.Font = $body
    $ui.Browse.Font = $body
    $ui.Intro.Font = New-DynamoToolboxFont -Family $fontName -SizePt 9
    $ui.Hint.Font = New-DynamoToolboxFont -Family $fontName -SizePt 9
    $ui.ToolLabel.Font = New-DynamoToolboxFont -Family $fontName -SizePt 11 -Style Bold
    $ui.ProjectLabel.Font = New-DynamoToolboxFont -Family $fontName -SizePt 11 -Style Bold

    $pad = ConvertTo-DynamoToolboxPx -Px 16 -Dpi $Dpi
    $gap = ConvertTo-DynamoToolboxPx -Px 8 -Dpi $Dpi
    $Form.Padding = New-DynamoToolboxPadding -Left $pad -Top $pad -Right $pad -Bottom $pad

    $clientW = ConvertTo-DynamoToolboxPx -Px 640 -Dpi $Dpi
    $clientH = ConvertTo-DynamoToolboxPx -Px 560 -Dpi $Dpi
    $contentW = $clientW - (2 * $pad)
    if ($contentW -lt 200) { $contentW = 200 }

    $wrapFlags = [System.Windows.Forms.TextFormatFlags]'WordBreak, TextBoxControl, NoPadding'
    # No NoPrefix: TextRenderer treats "&Launch" as the visible word Launch.
    $buttonFlags = [System.Windows.Forms.TextFormatFlags]'SingleLine, NoPadding'
    $proposed = New-Object System.Drawing.Size($contentW, [int]::MaxValue)

    foreach ($label in @($ui.Intro, $ui.Hint, $ui.ToolLabel, $ui.ProjectLabel)) {
      $label.UseCompatibleTextRendering = $false
      $label.AutoSize = $true
      $label.MaximumSize = New-Object System.Drawing.Size($contentW, 0)
      $measured = [System.Windows.Forms.TextRenderer]::MeasureText($label.Text, $label.Font, $proposed, $wrapFlags)
      $preferred = $label.PreferredSize
      $width = [Math]::Max($measured.Width, $preferred.Width)
      if ($width -gt $contentW -or $width -lt 1) { $width = $contentW }
      $height = [Math]::Max($measured.Height, $preferred.Height) + 2
      $label.MinimumSize = New-Object System.Drawing.Size($width, $height)
    }

    $ui.Intro.Margin = New-DynamoToolboxPadding -Left 0 -Top 0 -Right 0 -Bottom $gap
    $ui.ToolLabel.Margin = New-DynamoToolboxPadding -Left 0 -Top $gap -Right 0 -Bottom (ConvertTo-DynamoToolboxPx -Px 4 -Dpi $Dpi)
    $ui.ProjectLabel.Margin = New-DynamoToolboxPadding -Left 0 -Top $gap -Right 0 -Bottom (ConvertTo-DynamoToolboxPx -Px 4 -Dpi $Dpi)
    $ui.Hint.Margin = New-DynamoToolboxPadding -Left 0 -Top $gap -Right 0 -Bottom $gap

    $buttonWidth = ConvertTo-DynamoToolboxPx -Px 120 -Dpi $Dpi
    $buttonHeight = ConvertTo-DynamoToolboxPx -Px 32 -Dpi $Dpi
    foreach ($button in @($ui.Launch, $ui.Close, $ui.Browse)) {
      $textSize = [System.Windows.Forms.TextRenderer]::MeasureText($button.Text, $button.Font, $buttonFlags)
      $wantedW = $textSize.Width + (ConvertTo-DynamoToolboxPx -Px 28 -Dpi $Dpi)
      $wantedH = $textSize.Height + (ConvertTo-DynamoToolboxPx -Px 14 -Dpi $Dpi)
      if ($button.PreferredSize.Width -gt $wantedW) { $wantedW = $button.PreferredSize.Width }
      if ($button.PreferredSize.Height -gt $wantedH) { $wantedH = $button.PreferredSize.Height }
      if ($wantedW -gt $buttonWidth) { $buttonWidth = $wantedW }
      if ($wantedH -gt $buttonHeight) { $buttonHeight = $wantedH }
    }
    $ui.Launch.MinimumSize = New-Object System.Drawing.Size($buttonWidth, $buttonHeight)
    $ui.Close.MinimumSize = New-Object System.Drawing.Size($buttonWidth, $buttonHeight)
    $ui.Launch.Margin = New-DynamoToolboxPadding -Left 0 -Top 0 -Right 0 -Bottom 0
    $ui.Close.Margin = New-DynamoToolboxPadding -Left 0 -Top 0 -Right 0 -Bottom 0

    $boxHeight = $ui.ProjectBox.PreferredSize.Height
    if ($boxHeight -lt $buttonHeight) { $boxHeight = $buttonHeight }
    $ui.Browse.MinimumSize = New-Object System.Drawing.Size($buttonWidth, $boxHeight)
    $ui.Browse.Margin = New-DynamoToolboxPadding -Left 0 -Top 0 -Right 0 -Bottom 0
    $ui.ProjectBox.Margin = New-DynamoToolboxPadding -Left 0 -Top 0 -Right $gap -Bottom 0
    $ui.PathRow.Margin = New-DynamoToolboxPadding -Left 0 -Top 0 -Right 0 -Bottom 0
    $ui.ButtonRow.Margin = New-DynamoToolboxPadding -Left 0 -Top 0 -Right 0 -Bottom 0

    $auto = [System.Windows.Forms.SizeType]::AutoSize
    $absolute = [System.Windows.Forms.SizeType]::Absolute
    $percent = [System.Windows.Forms.SizeType]::Percent
    Set-DynamoToolboxRowStyle -Table $ui.Root -Index 0 -Type $auto -Height 0
    Set-DynamoToolboxRowStyle -Table $ui.Root -Index 1 -Type $auto -Height 0
    Set-DynamoToolboxRowStyle -Table $ui.Root -Index 2 -Type $percent -Height 100
    Set-DynamoToolboxRowStyle -Table $ui.Root -Index 3 -Type $auto -Height 0
    Set-DynamoToolboxRowStyle -Table $ui.Root -Index 4 -Type $absolute -Height $boxHeight
    Set-DynamoToolboxRowStyle -Table $ui.Root -Index 5 -Type $auto -Height 0
    Set-DynamoToolboxRowStyle -Table $ui.Root -Index 6 -Type $absolute -Height $buttonHeight

    $sampleFlags = [System.Windows.Forms.TextFormatFlags]'SingleLine, NoPadding, NoPrefix'
    $sampleText = 'Mg'
    if ($ui.List.Items.Count -gt 0) { $sampleText = [string]$ui.List.Items[0] }
    $sample = [System.Windows.Forms.TextRenderer]::MeasureText($sampleText, $ui.List.Font, $sampleFlags)
    $minItem = $sample.Height + (ConvertTo-DynamoToolboxPx -Px 12 -Dpi $Dpi)
    if ($minItem -lt 1) { $minItem = 1 }
    if ($minItem -gt 255) { $minItem = 255 }

    $widest = 0
    foreach ($item in @($ui.List.Items)) {
      $itemSize = [System.Windows.Forms.TextRenderer]::MeasureText([string]$item, $ui.List.Font, $sampleFlags)
      if ($itemSize.Width -gt $widest) { $widest = $itemSize.Width }
      $itemNeed = $itemSize.Height + (ConvertTo-DynamoToolboxPx -Px 8 -Dpi $Dpi)
      if ($itemNeed -gt $minItem) { $minItem = $itemNeed }
    }
    if ($minItem -gt 255) { $minItem = 255 }
    if ($minItem -lt 1) { $minItem = 1 }
    $ui.List.MinimumSize = New-Object System.Drawing.Size(0, (($minItem * [Math]::Max(1, $ui.List.Items.Count)) + (ConvertTo-DynamoToolboxPx -Px 6 -Dpi $Dpi)))
    $listPadX = ConvertTo-DynamoToolboxPx -Px 10 -Dpi $Dpi
    $ui.List.Tag = $listPadX
    $neededContentW = $widest + (2 * $listPadX) + (ConvertTo-DynamoToolboxPx -Px 24 -Dpi $Dpi)
    if ($neededContentW -gt $contentW) {
      $clientW = $neededContentW + (2 * $pad)
      $contentW = $neededContentW
    }

    $Form.ClientSize = New-Object System.Drawing.Size($clientW, $clientH)
    $Form.PerformLayout()

    $fixedHeight = $Form.Padding.Vertical
    $fixedHeight += $ui.Intro.PreferredSize.Height + $ui.Intro.Margin.Vertical
    $fixedHeight += $ui.ToolLabel.PreferredSize.Height + $ui.ToolLabel.Margin.Vertical
    $fixedHeight += $ui.ProjectLabel.PreferredSize.Height + $ui.ProjectLabel.Margin.Vertical
    $fixedHeight += $boxHeight
    $fixedHeight += $ui.Hint.PreferredSize.Height + $ui.Hint.Margin.Vertical
    $fixedHeight += $buttonHeight
    $listChrome = $ui.List.Height - $ui.List.ClientSize.Height
    if ($listChrome -lt 0) { $listChrome = ConvertTo-DynamoToolboxPx -Px 4 -Dpi $Dpi }
    $listNeed = ($minItem * [Math]::Max(1, $ui.List.Items.Count)) + $listChrome + $ui.List.Margin.Vertical
    $neededClientH = $fixedHeight + $listNeed
    if ($neededClientH -gt $Form.ClientSize.Height -or $clientW -ne $Form.ClientSize.Width) {
      $Form.ClientSize = New-Object System.Drawing.Size(
        [Math]::Max($clientW, $Form.ClientSize.Width),
        [Math]::Max($clientH, $neededClientH))
      $Form.PerformLayout()
    }

    $count = [Math]::Max(1, $ui.List.Items.Count)
    $fitPass = 0
    while ($fitPass -lt 3) {
      $fitPass++
      $listChrome = $ui.List.Height - $ui.List.ClientSize.Height
      if ($listChrome -lt 0) { $listChrome = 0 }
      $clientListH = $ui.List.ClientSize.Height
      $itemHeight = 1
      if ($clientListH -gt 0) { $itemHeight = [int][Math]::Floor($clientListH / $count) }
      if ($itemHeight -lt $minItem) { $itemHeight = $minItem }
      if ($itemHeight -gt 255) { $itemHeight = 255 }
      $ui.List.ItemHeight = $itemHeight
      if ($ui.List.ClientSize.Height -ge ($itemHeight * $count)) { break }
      $needListH = ($itemHeight * $count) + $listChrome
      $ui.List.MinimumSize = New-Object System.Drawing.Size(0, $needListH)
      $grow = $needListH - $ui.List.Height
      if ($grow -lt 1) { $grow = 1 }
      $Form.ClientSize = New-Object System.Drawing.Size($Form.ClientSize.Width, ($Form.ClientSize.Height + $grow))
      $Form.PerformLayout()
    }

    # Sizes above are already device pixels. Match AutoScaleDimensions to this
    # DPI so WinForms does not scale them a second time. On a later DPI change
    # this function runs again and assigns the new device pixels directly.
    $Form.AutoScaleDimensions = New-Object System.Drawing.SizeF([single]$Dpi, [single]$Dpi)
    $Form.AutoScaleMode = [System.Windows.Forms.AutoScaleMode]::Dpi
    $ui.AppliedDpi = $Dpi
  } finally {
    $script:DynamoToolboxLayoutBusy = $false
  }
}

function New-DynamoToolboxForm {
  $script:catalog = @(Get-DynamoToolboxCatalog)
  $script:journalScript = Join-Path (Get-DynamoToolboxLauncherDir) 'poc\New-DynamoJournal.ps1'
  if (-not (Test-Path -LiteralPath $script:journalScript)) {
    throw "Journal writer not found: $script:journalScript"
  }

  # DPI before System.Windows.Forms is loaded. EnableVisualStyles and the form
  # come after the STA / Windows PowerShell 5.1 relaunch check, because
  # Show-DynamoToolboxForm only calls this function on that path. Tests call
  # this function directly so they can lay the form out without ShowDialog.
  Enable-DynamoToolboxDpiAwareness
  Enable-DynamoToolboxVisualStyles
  Initialize-DynamoToolboxFormType

  $fontName = Get-DynamoToolboxFontName
  if ('DynamoToolboxForm' -as [type]) {
    $form = New-Object DynamoToolboxForm
  } else {
    $form = New-Object System.Windows.Forms.Form
  }

  $script:toolboxForm = $form
  $form.SuspendLayout()
  $form.AutoScaleMode = [System.Windows.Forms.AutoScaleMode]::None
  $form.Text = 'Dynamo toolbox'
  $form.FormBorderStyle = 'FixedDialog'
  $form.MaximizeBox = $false
  $form.StartPosition = 'CenterScreen'
  $form.Font = New-DynamoToolboxFont -Family $fontName -SizePt 10

  $root = New-Object System.Windows.Forms.TableLayoutPanel
  $root.Name = 'rootLayout'
  $root.Dock = 'Fill'
  $root.AutoSize = $false
  $root.ColumnCount = 1
  $root.RowCount = 7
  $root.Margin = New-DynamoToolboxPadding -Left 0 -Top 0 -Right 0 -Bottom 0
  $root.Padding = New-DynamoToolboxPadding -Left 0 -Top 0 -Right 0 -Bottom 0
  $root.GrowStyle = 'FixedSize'
  $root.ColumnStyles.Clear()
  $root.RowStyles.Clear()
  [void]$root.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, 100)))
  for ($row = 0; $row -lt 7; $row++) {
    [void]$root.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::AutoSize, 0)))
  }

  $intro = New-Object System.Windows.Forms.Label
  $intro.Name = 'introLabel'
  $intro.Text = 'Pick one tool and an existing .rvt. Revit 2025 must be closed. The graph loads in manual mode and does not run.'
  $intro.ForeColor = [System.Drawing.SystemColors]::GrayText
  $intro.Anchor = 'Left, Top, Right'
  $root.Controls.Add($intro, 0, 0)

  $toolLabel = New-Object System.Windows.Forms.Label
  $toolLabel.Name = 'toolLabel'
  $toolLabel.Text = 'Tool'
  $toolLabel.Anchor = 'Left, Top'
  $root.Controls.Add($toolLabel, 0, 1)

  $script:toolList = New-Object System.Windows.Forms.ListBox
  $list = $script:toolList
  $list.Name = 'toolList'
  $list.Dock = 'Fill'
  $list.IntegralHeight = $false
  $list.HorizontalScrollbar = $false
  $list.ScrollAlwaysVisible = $false
  $list.DrawMode = 'OwnerDrawFixed'
  $list.TabIndex = 0
  $list.Margin = New-DynamoToolboxPadding -Left 0 -Top 0 -Right 0 -Bottom 0
  foreach ($tool in $script:catalog) {
    [void]$list.Items.Add($tool.Name)
  }
  if ($list.Items.Count -gt 0) { $list.SelectedIndex = 0 }
  $list.Add_DrawItem({
    param($sender, $e)
    if ($null -eq $e -or $e.Index -lt 0) { return }
    $selected = ($e.State -band [System.Windows.Forms.DrawItemState]::Selected) -eq [System.Windows.Forms.DrawItemState]::Selected
    $back = [System.Drawing.SystemBrushes]::Window
    $fore = [System.Drawing.SystemColors]::WindowText
    if ($selected) {
      $back = [System.Drawing.SystemBrushes]::Highlight
      $fore = [System.Drawing.SystemColors]::HighlightText
    }
    $e.Graphics.FillRectangle($back, $e.Bounds)
    $padX = 8
    if ($null -ne $sender.Tag) {
      try { $padX = [int]$sender.Tag } catch { $padX = 8 }
    }
    $rect = New-Object System.Drawing.Rectangle(
      ($e.Bounds.X + $padX),
      $e.Bounds.Y,
      [Math]::Max(0, ($e.Bounds.Width - (2 * $padX))),
      $e.Bounds.Height)
    $flags = [System.Windows.Forms.TextFormatFlags]'Left, VerticalCenter, EndEllipsis, NoPrefix, SingleLine'
    $text = [string]$sender.Items[$e.Index]
    [System.Windows.Forms.TextRenderer]::DrawText($e.Graphics, $text, $e.Font, $rect, $fore, $flags)
    $e.DrawFocusRectangle()
  })
  $root.Controls.Add($list, 0, 2)

  $projectLabel = New-Object System.Windows.Forms.Label
  $projectLabel.Name = 'projectLabel'
  $projectLabel.Text = 'Existing project (.rvt)'
  $projectLabel.Anchor = 'Left, Top'
  $root.Controls.Add($projectLabel, 0, 3)

  $pathRow = New-Object System.Windows.Forms.TableLayoutPanel
  $pathRow.Name = 'pathLayout'
  $pathRow.Dock = 'Fill'
  $pathRow.ColumnCount = 2
  $pathRow.RowCount = 1
  $pathRow.GrowStyle = 'FixedSize'
  $pathRow.Margin = New-DynamoToolboxPadding -Left 0 -Top 0 -Right 0 -Bottom 0
  $pathRow.Padding = New-DynamoToolboxPadding -Left 0 -Top 0 -Right 0 -Bottom 0
  $pathRow.ColumnStyles.Clear()
  $pathRow.RowStyles.Clear()
  [void]$pathRow.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, 100)))
  [void]$pathRow.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::AutoSize)))
  [void]$pathRow.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Percent, 100)))

  $script:projectBox = New-Object System.Windows.Forms.TextBox
  $projectBox = $script:projectBox
  $projectBox.Name = 'projectBox'
  $projectBox.Dock = 'Fill'
  $projectBox.TabIndex = 1
  $pathRow.Controls.Add($projectBox, 0, 0)

  $browse = New-Object System.Windows.Forms.Button
  $browse.Name = 'browseButton'
  $browse.Text = '&Browse...'
  $browse.Dock = 'Fill'
  $browse.AutoSize = $true
  $browse.TabIndex = 2
  $browse.UseVisualStyleBackColor = $true
  $browse.Add_Click({
    $dialog = New-Object System.Windows.Forms.OpenFileDialog
    $dialog.Filter = 'Revit project (*.rvt)|*.rvt'
    $dialog.Title = 'Select an existing Revit project'
    $dialog.CheckFileExists = $true
    $dialog.Multiselect = $false
    if ($dialog.ShowDialog($script:toolboxForm) -eq [System.Windows.Forms.DialogResult]::OK) {
      $script:projectBox.Text = $dialog.FileName
    }
  })
  $pathRow.Controls.Add($browse, 1, 0)
  $root.Controls.Add($pathRow, 0, 4)

  $hint = New-Object System.Windows.Forms.Label
  $hint.Name = 'hintLabel'
  $hint.Text = 'Templates (.rte) are not opened. If Revit 2025 is already running, close it before Launch.'
  $hint.ForeColor = [System.Drawing.SystemColors]::GrayText
  $hint.Anchor = 'Left, Top, Right'
  $root.Controls.Add($hint, 0, 5)

  $buttonRow = New-Object System.Windows.Forms.TableLayoutPanel
  $buttonRow.Name = 'buttonLayout'
  $buttonRow.Dock = 'Fill'
  $buttonRow.ColumnCount = 3
  $buttonRow.RowCount = 1
  $buttonRow.GrowStyle = 'FixedSize'
  $buttonRow.Margin = New-DynamoToolboxPadding -Left 0 -Top 0 -Right 0 -Bottom 0
  $buttonRow.Padding = New-DynamoToolboxPadding -Left 0 -Top 0 -Right 0 -Bottom 0
  $buttonRow.ColumnStyles.Clear()
  $buttonRow.RowStyles.Clear()
  [void]$buttonRow.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::AutoSize)))
  [void]$buttonRow.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, 100)))
  [void]$buttonRow.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::AutoSize)))
  [void]$buttonRow.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Percent, 100)))

  $launch = New-Object System.Windows.Forms.Button
  $launch.Name = 'launchButton'
  $launch.Text = '&Launch'
  $launch.AutoSize = $true
  $launch.Anchor = 'Left'
  $launch.TabIndex = 3
  $launch.UseVisualStyleBackColor = $true
  $launch.Add_Click({
    $index = $script:toolList.SelectedIndex
    $warning = Get-DynamoToolboxLaunchWarning -ToolIndex $index -ToolCount $script:catalog.Count -ProjectText $script:projectBox.Text
    if ($null -ne $warning) {
      [System.Windows.Forms.MessageBox]::Show($script:toolboxForm, $warning.Message, $warning.Title, [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Warning) | Out-Null
      return
    }
    $project = $script:projectBox.Text.Trim().Trim('"')
    if (Test-Revit2025Running) {
      [System.Windows.Forms.MessageBox]::Show($script:toolboxForm, $script:RevitAlreadyRunningMessage, 'Close Revit first', [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Warning) | Out-Null
      return
    }
    try {
      & $script:journalScript -ToolId $script:catalog[$index].Id -Project $project -Launch
    } catch {
      [System.Windows.Forms.MessageBox]::Show($script:toolboxForm, $_.Exception.Message, 'Dynamo toolbox', [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Warning) | Out-Null
      return
    }
    $script:toolboxForm.Close()
  })
  $buttonRow.Controls.Add($launch, 0, 0)

  $close = New-Object System.Windows.Forms.Button
  $close.Name = 'closeButton'
  $close.Text = '&Close'
  $close.AutoSize = $true
  $close.Anchor = 'Right'
  $close.TabIndex = 4
  $close.UseVisualStyleBackColor = $true
  $close.Add_Click({ $script:toolboxForm.Close() })
  $buttonRow.Controls.Add($close, 2, 0)
  $root.Controls.Add($buttonRow, 0, 6)

  $form.Controls.Add($root)
  $form.AcceptButton = $launch
  $form.CancelButton = $close
  $form.ResumeLayout($false)

  $script:DynamoToolboxUi = @{
    Form         = $form
    Root         = $root
    Intro        = $intro
    ToolLabel    = $toolLabel
    List         = $list
    ProjectLabel = $projectLabel
    PathRow      = $pathRow
    ProjectBox   = $projectBox
    Browse       = $browse
    Hint         = $hint
    ButtonRow    = $buttonRow
    Launch       = $launch
    Close        = $close
    FontName     = $fontName
    AppliedDpi   = 0
  }

  $onDpi = {
    param($sender, $e)
    $next = 0
    if ($null -ne $e) {
      $prop = $e.GetType().GetProperty('DeviceDpiNew')
      if ($prop) {
        try { $next = [int]$prop.GetValue($e, $null) } catch { $next = 0 }
      }
    }
    Sync-DynamoToolboxLayout -Form $sender -Dpi $next
  }
  try { $form.Add_DpiChanged($onDpi) } catch { }
  if ($form.GetType().GetEvent('DpiWorkaround')) {
    $form.Add_DpiWorkaround({
      param($sender, $e)
      Sync-DynamoToolboxLayout -Form $sender
    })
  }

  Sync-DynamoToolboxLayout -Form $form
  return $form
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

  $form = New-DynamoToolboxForm
  try {
    [void]$form.ShowDialog()
  } finally {
    if ($form) { $form.Dispose() }
  }
}

if ($MyInvocation.InvocationName -ne '.') {
  Show-DynamoToolboxForm
}
