#Requires -Version 5.1
<#
.SYNOPSIS
  Layout checks for the Dynamo toolbox window. Run on Windows PowerShell 5.1.

.DESCRIPTION
  Dot-sources Show-DynamoToolbox.ps1, builds the form without ShowDialog, and
  checks list contents, clipping, overlap, and Launch validation. It does not
  call the journal script and it does not start Revit.

  Repeat at 100%, 125%, 150%, and 200%:
  Windows Settings > System > Display > Scale. Sign out if Windows asks you to.

.EXAMPLE
  powershell.exe -NoProfile -ExecutionPolicy Bypass -STA -File G:\Dynamo\launcher\tests\Test-DynamoToolboxLayout.ps1
#>
$ErrorActionPreference = 'Stop'

$script:FailMessages = @()

function Add-Pass {
  param([string]$Message)
  Write-Host "PASS: $Message"
}

function Add-Fail {
  param([string]$Message)
  $script:FailMessages += $Message
  Write-Host "FAIL: $Message"
}

function Find-ToolboxControl {
  param($Control, [string]$Name)
  if ($null -eq $Control) { return $null }
  if ($Control.Name -eq $Name) { return $Control }
  foreach ($child in @($Control.Controls)) {
    $found = Find-ToolboxControl -Control $child -Name $Name
    if ($found) { return $found }
  }
  return $null
}

function Test-BoundsOverlap {
  param($First, $Second, [int]$Tolerance)
  $left = [Math]::Max($First.Left, $Second.Left)
  $top = [Math]::Max($First.Top, $Second.Top)
  $right = [Math]::Min($First.Right, $Second.Right)
  $bottom = [Math]::Min($First.Bottom, $Second.Bottom)
  return (($right - $left) -gt $Tolerance) -and (($bottom - $top) -gt $Tolerance)
}

$testDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$menuPath = Join-Path (Split-Path -Parent $testDir) 'Show-DynamoToolbox.ps1'
if (-not (Test-Path -LiteralPath $menuPath)) {
  Write-Host "FAIL: menu script not found: $menuPath"
  exit 1
}

if ($PSVersionTable.PSEdition -ne 'Desktop') {
  Write-Host 'FAIL: run this test with Windows PowerShell 5.1 (powershell.exe -STA), not PowerShell 7.'
  exit 1
}
$apartment = [System.Threading.Thread]::CurrentThread.GetApartmentState()
if ($apartment -ne 'STA') {
  Write-Host 'FAIL: this test needs an STA thread. Run: powershell.exe -NoProfile -ExecutionPolicy Bypass -STA -File G:\Dynamo\launcher\tests\Test-DynamoToolboxLayout.ps1'
  exit 1
}

. $menuPath

$form = $null
$bitmap = $null
$tempRvt = Join-Path $env:TEMP 'DynamoToolboxLayoutExisting.rvt'
$tempRte = Join-Path $env:TEMP 'DynamoToolboxLayoutTemplate.rte'
$exitCode = 1

try {
  $catalog = @(Get-DynamoToolboxCatalog)
  if ($catalog.Count -eq 6) {
    Add-Pass 'tools.json lists six tools'
  } else {
    Add-Fail ("tools.json lists {0} tools, expected 6" -f $catalog.Count)
  }

  $pickTool = Get-DynamoToolboxLaunchWarning -ToolIndex -1 -ToolCount $catalog.Count -ProjectText 'C:\Models\ok.rvt'
  if ($pickTool -and $pickTool.Message -eq 'Pick one tool.' -and $pickTool.Title -eq 'Dynamo toolbox') {
    Add-Pass 'empty tool selection returns Pick one tool.'
  } else {
    Add-Fail 'empty tool selection did not return the Pick one tool. warning'
  }

  $emptyPath = Get-DynamoToolboxLaunchWarning -ToolIndex 0 -ToolCount $catalog.Count -ProjectText ''
  $emptyMessage = 'Choose an existing .rvt file. Templates (.rte) are not opened.'
  if ($emptyPath -and $emptyPath.Message -eq $emptyMessage -and $emptyPath.Title -eq 'Dynamo toolbox') {
    Add-Pass 'empty path returns the existing-.rvt warning'
  } else {
    Add-Fail 'empty path did not return the existing-.rvt warning'
  }

  [System.IO.File]::WriteAllBytes($tempRte, (New-Object 'byte[]' 0))
  $rteWarning = Get-DynamoToolboxLaunchWarning -ToolIndex 0 -ToolCount $catalog.Count -ProjectText $tempRte
  if ($rteWarning -and $rteWarning.Message -eq $emptyMessage -and $rteWarning.Title -eq 'Dynamo toolbox') {
    Add-Pass 'existing .rte path returns the existing-.rvt warning'
  } else {
    Add-Fail 'existing .rte path did not return the existing-.rvt warning'
  }

  $missingRvt = Join-Path $env:TEMP 'DynamoToolboxLayoutMissing.rvt'
  if (Test-Path -LiteralPath $missingRvt) { Remove-Item -LiteralPath $missingRvt -Force }
  $missingWarning = Get-DynamoToolboxLaunchWarning -ToolIndex 0 -ToolCount $catalog.Count -ProjectText $missingRvt
  if ($missingWarning -and $missingWarning.Message -eq $emptyMessage) {
    Add-Pass 'missing .rvt path returns the existing-.rvt warning'
  } else {
    Add-Fail 'missing .rvt path did not return the existing-.rvt warning'
  }

  [System.IO.File]::WriteAllBytes($tempRvt, (New-Object 'byte[]' 0))
  $okWarning = Get-DynamoToolboxLaunchWarning -ToolIndex 0 -ToolCount $catalog.Count -ProjectText $tempRvt
  $quoted = Get-DynamoToolboxLaunchWarning -ToolIndex 0 -ToolCount $catalog.Count -ProjectText ('"' + $tempRvt + '"')
  if ($null -eq $okWarning -and $null -eq $quoted) {
    Add-Pass 'existing .rvt (plain and quoted) passes validation and does not call the journal script'
  } else {
    Add-Fail 'existing .rvt was rejected by validation'
  }

  $form = New-DynamoToolboxForm
  Enable-DynamoToolboxDpiAwareness
  Initialize-DynamoToolboxFormType
  Add-Pass 'DPI and form type init can run twice without an Add-Type name collision'
  $form.Show()
  Sync-DynamoToolboxLayout -Form $form
  $form.PerformLayout()
  $form.Refresh()
  [System.Windows.Forms.Application]::DoEvents()

  $dpi = 96
  $dpiProp = $form.GetType().GetProperty('DeviceDpi')
  if ($dpiProp) { $dpi = [int]$dpiProp.GetValue($form, $null) }
  Write-Host ("DeviceDpi: {0}" -f $dpi)
  Write-Host ("ClientSize: {0}x{1}" -f $form.ClientSize.Width, $form.ClientSize.Height)
  Write-Host ("Font: {0} {1}pt {2}" -f $form.Font.Name, $form.Font.SizeInPoints, $form.Font.Unit)
  Write-Host ("AutoScaleMode: {0}" -f $form.AutoScaleMode)

  $awarenessName = 'unavailable'
  $awarenessValue = $null
  $equalV2 = $false
  if ('DynamoToolboxNative' -as [type]) {
    try {
      $context = [DynamoToolboxNative]::GetThreadDpiAwarenessContext()
      $awarenessValue = [DynamoToolboxNative]::GetAwarenessFromDpiAwarenessContext($context)
      $equalV2 = [DynamoToolboxNative]::AreDpiAwarenessContextsEqual($context, ([System.IntPtr]::new(-4)))
      $equalPerMonitor = [DynamoToolboxNative]::AreDpiAwarenessContextsEqual($context, ([System.IntPtr]::new(-3)))
      $equalSystem = [DynamoToolboxNative]::AreDpiAwarenessContextsEqual($context, ([System.IntPtr]::new(-2)))
      $equalUnaware = [DynamoToolboxNative]::AreDpiAwarenessContextsEqual($context, ([System.IntPtr]::new(-1)))
      Write-Host ("ThreadDpiAwarenessContext: {0}" -f $context)
      Write-Host ("AwarenessFromDpiAwarenessContext: {0} (0=unaware, 1=system, 2=per-monitor)" -f $awarenessValue)
      Write-Host ("EqualPerMonitorV2: {0}" -f $equalV2)
      Write-Host ("EqualPerMonitor: {0}" -f $equalPerMonitor)
      Write-Host ("EqualSystemAware: {0}" -f $equalSystem)
      Write-Host ("EqualUnaware: {0}" -f $equalUnaware)
      if ($equalV2) { $awarenessName = 'PerMonitorV2' }
      elseif ($equalPerMonitor -or $awarenessValue -eq 2) { $awarenessName = 'PerMonitor' }
      elseif ($equalSystem -or $awarenessValue -eq 1) { $awarenessName = 'System' }
      elseif ($equalUnaware -or $awarenessValue -eq 0) { $awarenessName = 'Unaware' }
      else { $awarenessName = ("value " + $awarenessValue) }
    } catch {
      Add-Fail ("DPI awareness query failed: " + $_.Exception.Message)
    }
  } else {
    Add-Fail 'DynamoToolboxNative was not loaded, so DPI awareness could not be queried'
  }
  Write-Host ("DpiAwareness: {0}" -f $awarenessName)
  if ($awarenessName -eq 'Unaware' -or $awarenessValue -eq 0 -or $awarenessValue -eq -1) {
    Add-Fail 'thread DPI awareness is still unaware or invalid, so Windows will bitmap-stretch the window'
  } elseif ($awarenessName -ne 'unavailable') {
    Add-Pass ("thread DPI awareness is {0}" -f $awarenessName)
  }

  $pngPath = Join-Path $env:TEMP ("DynamoToolboxLayout_{0}.png" -f $dpi)
  $bitmap = New-Object System.Drawing.Bitmap($form.Width, $form.Height)
  $form.DrawToBitmap($bitmap, (New-Object System.Drawing.Rectangle(0, 0, $form.Width, $form.Height)))
  $bitmap.Save($pngPath, [System.Drawing.Imaging.ImageFormat]::Png)
  Write-Host "PNG: $pngPath"
  if (Test-Path -LiteralPath $pngPath) {
    Add-Pass "saved layout image to $pngPath"
  } else {
    Add-Fail "layout image was not written to $pngPath"
  }

  $list = Find-ToolboxControl -Control $form -Name 'toolList'
  $intro = Find-ToolboxControl -Control $form -Name 'introLabel'
  $hint = Find-ToolboxControl -Control $form -Name 'hintLabel'
  $toolLabel = Find-ToolboxControl -Control $form -Name 'toolLabel'
  $projectLabel = Find-ToolboxControl -Control $form -Name 'projectLabel'
  $projectBox = Find-ToolboxControl -Control $form -Name 'projectBox'
  $browse = Find-ToolboxControl -Control $form -Name 'browseButton'
  $launch = Find-ToolboxControl -Control $form -Name 'launchButton'
  $close = Find-ToolboxControl -Control $form -Name 'closeButton'
  $required = @($list, $intro, $hint, $toolLabel, $projectLabel, $projectBox, $browse, $launch, $close)
  if ($required -contains $null) {
    Add-Fail 'one or more named controls are missing from the form'
  } else {
    Add-Pass 'named controls are present'
  }

  if ($list -and $catalog.Count -eq $list.Items.Count) {
    $namesMatch = $true
    for ($i = 0; $i -lt $catalog.Count; $i++) {
      if ([string]$list.Items[$i] -ne [string]$catalog[$i].Name) { $namesMatch = $false }
    }
    if ($namesMatch) {
      Add-Pass 'list items equal tools.json names in order'
    } else {
      Add-Fail 'list items do not equal tools.json names in order'
    }
  } else {
    Add-Fail 'list item count does not equal tools.json'
  }

  if ($list -and $list.DrawMode -eq [System.Windows.Forms.DrawMode]::OwnerDrawFixed -and $list.IntegralHeight -eq $false) {
    Add-Pass 'tool list is OwnerDrawFixed with IntegralHeight off'
  } else {
    Add-Fail 'tool list is not OwnerDrawFixed or IntegralHeight is on'
  }

  if ($list -and (($list.ItemHeight * $list.Items.Count) -le $list.ClientSize.Height)) {
    Add-Pass ("list shows all {0} items without vertical scroll (item {1}px, client {2}px)" -f $list.Items.Count, $list.ItemHeight, $list.ClientSize.Height)
  } else {
    Add-Fail 'list client height is shorter than item height times item count, so it would scroll'
  }

  $scale = 1.0
  if ($dpi -ge 96) { $scale = $dpi / 96.0 }
  if ($form.ClientSize.Width -ge [int](640 * $scale * 0.90) -and $form.ClientSize.Width -le [int](640 * $scale * 1.45) -and $form.ClientSize.Height -ge [int](560 * $scale * 0.90) -and $form.ClientSize.Height -le [int](560 * $scale * 1.45)) {
    Add-Pass ("client size {0}x{1} is about 640x560 at 96 DPI, scaled by {2}" -f $form.ClientSize.Width, $form.ClientSize.Height, $scale)
  } else {
    Add-Fail ("client size {0}x{1} is outside the expected range around 640x560 at DPI {2}" -f $form.ClientSize.Width, $form.ClientSize.Height, $dpi)
  }

  if ($form.AutoScaleMode -eq [System.Windows.Forms.AutoScaleMode]::Dpi) {
    Add-Pass 'AutoScaleMode is Dpi'
  } else {
    Add-Fail ("AutoScaleMode is {0}" -f $form.AutoScaleMode)
  }

  $fontName = Get-DynamoToolboxFontName
  $point = [System.Drawing.GraphicsUnit]::Point
  $bold = [System.Drawing.FontStyle]::Bold
  if ($form.Font.Name -eq $fontName -and $form.Font.Unit -eq $point -and [Math]::Abs($form.Font.SizeInPoints - 10) -lt 0.1) {
    Add-Pass ("body font is {0} 10pt" -f $fontName)
  } else {
    Add-Fail ("body font is {0} {1}pt {2}" -f $form.Font.Name, $form.Font.SizeInPoints, $form.Font.Unit)
  }
  if ($toolLabel -and $projectLabel -and $toolLabel.Font.SizeInPoints -eq 11 -and $projectLabel.Font.SizeInPoints -eq 11 -and $toolLabel.Font.Style -eq $bold -and $projectLabel.Font.Style -eq $bold) {
    Add-Pass 'section labels are 11pt bold'
  } else {
    Add-Fail 'section labels are not 11pt bold'
  }
  $gray = [System.Drawing.SystemColors]::GrayText
  if ($intro -and $hint -and $intro.Font.SizeInPoints -eq 9 -and $hint.Font.SizeInPoints -eq 9 -and $intro.ForeColor.ToArgb() -eq $gray.ToArgb() -and $hint.ForeColor.ToArgb() -eq $gray.ToArgb()) {
    Add-Pass 'intro and hint are 9pt GrayText'
  } else {
    Add-Fail 'intro or hint is not 9pt gray'
  }

  if ($launch -and $close -and $form.AcceptButton -eq $launch -and $form.CancelButton -eq $close) {
    Add-Pass 'Launch is AcceptButton and Close is CancelButton'
  } else {
    Add-Fail 'AcceptButton or CancelButton is not Launch/Close'
  }
  if ($launch -and $close -and [Math]::Abs($launch.Width - $close.Width) -le 2) {
    Add-Pass 'Launch and Close have the same width'
  } else {
    Add-Fail 'Launch and Close widths differ'
  }
  if ($browse -and $projectBox -and [Math]::Abs($browse.Height - $projectBox.Height) -le 2 -and $projectBox.Width -gt $browse.Width) {
    Add-Pass 'project path stretches and Browse matches its height'
  } else {
    Add-Fail 'project path and Browse are not a stretching row of equal height'
  }
  if ($intro -and $intro.Text -eq 'Pick one tool and an existing .rvt. Revit 2025 must be closed. The graph loads in manual mode and does not run.' -and $browse -and $browse.Text -eq '&Browse...' -and $launch -and $launch.Text -eq '&Launch' -and $close -and $close.Text -eq '&Close') {
    Add-Pass 'visible strings and mnemonics are unchanged'
  } else {
    Add-Fail 'a visible string or mnemonic changed'
  }

  $tolerance = 2
  $wrapFlags = [System.Windows.Forms.TextFormatFlags]'WordBreak, TextBoxControl, NoPadding'
  $buttonFlags = [System.Windows.Forms.TextFormatFlags]'SingleLine, NoPadding'
  $itemFlags = [System.Windows.Forms.TextFormatFlags]'SingleLine, NoPadding, NoPrefix'
  $geometryFails = $script:FailMessages.Count
  foreach ($start in @($form)) {
    $stack = New-Object System.Collections.ArrayList
    [void]$stack.Add($start)
    while ($stack.Count -gt 0) {
      $parent = $stack[$stack.Count - 1]
      $stack.RemoveAt($stack.Count - 1)
      $kids = @($parent.Controls)
      foreach ($kid in $kids) { [void]$stack.Add($kid) }
      for ($i = 0; $i -lt $kids.Count; $i++) {
        $child = $kids[$i]
        if (-not $child.Visible) { continue }
        $bounds = $child.Bounds
        $client = $parent.ClientSize
        $inside = $bounds.Width -gt 0 -and $bounds.Height -gt 0 -and $bounds.Left -ge (0 - $tolerance) -and $bounds.Top -ge (0 - $tolerance) -and $bounds.Right -le ($client.Width + $tolerance) -and $bounds.Bottom -le ($client.Height + $tolerance)
        if (-not $inside) {
          Add-Fail ("{0} bounds {1} are outside parent {2} client {3}x{4}" -f $child.Name, $bounds, $parent.Name, $client.Width, $client.Height)
        }
        if ($child -is [System.Windows.Forms.Label] -or $child -is [System.Windows.Forms.Button]) {
          $preferred = $child.PreferredSize
          if ($preferred.Width -gt ($child.Width + $tolerance) -or $preferred.Height -gt ($child.Height + $tolerance)) {
            Add-Fail ("{0} PreferredSize {1}x{2} exceeds Size {3}x{4}" -f $child.Name, $preferred.Width, $preferred.Height, $child.Width, $child.Height)
          }
        }
        if ($child -is [System.Windows.Forms.Label] -and -not [string]::IsNullOrEmpty($child.Text)) {
          $proposed = New-Object System.Drawing.Size([Math]::Max(1, $child.ClientSize.Width), [int]::MaxValue)
          $measured = [System.Windows.Forms.TextRenderer]::MeasureText($child.Text, $child.Font, $proposed, $wrapFlags)
          if ($measured.Width -gt ($child.ClientSize.Width + $tolerance) -or $measured.Height -gt ($child.ClientSize.Height + $tolerance)) {
            Add-Fail ("{0} text {1}x{2} exceeds client {3}x{4}" -f $child.Name, $measured.Width, $measured.Height, $child.ClientSize.Width, $child.ClientSize.Height)
          }
        }
        if ($child -is [System.Windows.Forms.Button]) {
          $measuredButton = [System.Windows.Forms.TextRenderer]::MeasureText($child.Text, $child.Font, $buttonFlags)
          if ($measuredButton.Width -gt ($child.ClientSize.Width + $tolerance) -or $measuredButton.Height -gt ($child.ClientSize.Height + $tolerance)) {
            Add-Fail ("{0} button text {1}x{2} exceeds client {3}x{4}" -f $child.Name, $measuredButton.Width, $measuredButton.Height, $child.ClientSize.Width, $child.ClientSize.Height)
          }
        }
        for ($j = $i + 1; $j -lt $kids.Count; $j++) {
          $other = $kids[$j]
          if (-not $other.Visible) { continue }
          if (Test-BoundsOverlap -First $child.Bounds -Second $other.Bounds -Tolerance $tolerance) {
            Add-Fail ("{0} overlaps {1}" -f $child.Name, $other.Name)
          }
        }
      }
    }
  }

  if ($list) {
    $padX = 8
    if ($null -ne $list.Tag) { $padX = [int]$list.Tag }
    $available = $list.ClientSize.Width - (2 * $padX)
    foreach ($item in @($list.Items)) {
      $measuredItem = [System.Windows.Forms.TextRenderer]::MeasureText([string]$item, $list.Font, $itemFlags)
      if ($measuredItem.Width -gt ($available + $tolerance) -or $measuredItem.Height -gt ($list.ItemHeight + $tolerance)) {
        Add-Fail ("list text does not fit: width {0} available {1}, height {2} item {3}" -f $measuredItem.Width, $available, $measuredItem.Height, $list.ItemHeight)
      }
    }
  }
  if ($script:FailMessages.Count -eq $geometryFails) {
    Add-Pass 'every control is inside its parent, text fits, and siblings do not overlap'
  }

  if ($script:FailMessages.Count -eq 0) {
    Add-Pass 'all layout checks'
    $exitCode = 0
  } else {
    Write-Host ("FAIL: {0} check(s) failed" -f $script:FailMessages.Count)
    $exitCode = 1
  }
} catch {
  Write-Host ("FAIL: " + $_.Exception.Message)
  $exitCode = 1
} finally {
  if ($bitmap) { $bitmap.Dispose() }
  if ($form) {
    try { $form.Hide() } catch { }
    try { $form.Dispose() } catch { }
  }
  foreach ($tempPath in @($tempRvt, $tempRte)) {
    if ($tempPath -and (Test-Path -LiteralPath $tempPath)) {
      Remove-Item -LiteralPath $tempPath -Force -ErrorAction SilentlyContinue
    }
  }
}

exit $exitCode
