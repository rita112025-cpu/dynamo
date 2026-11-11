#Requires -Version 5.1
<#
.SYNOPSIS
  Menu for the Dynamo tools listed in launcher/tools.json.

.DESCRIPTION
  The first tab starts one tool. The second tab builds a task queue: several tools,
  a JSON task config, and a run log. Both tabs call launcher/poc/New-DynamoJournal.ps1,
  which writes a system-ANSI journal with no BOM and loads the graph in manual mode.
  The graph is not run.

  If Revit 2025 is already open, the menu tells you to close it and stops. It does
  not attach to that session.

.EXAMPLE
  powershell.exe -NoProfile -ExecutionPolicy Bypass -STA -File .\launcher\Show-DynamoToolbox.ps1
#>
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'queue\DynamoQueue.ps1')

$script:RevitAlreadyRunningMessage = 'Revit 2025 is already running. Close Revit, then run this again. This launcher does not attach to an open Revit session.'

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

function Show-QueueNotice {
  param(
    [string]$Text,
    [string]$Title = '批次佇列',
    $Buttons = [System.Windows.Forms.MessageBoxButtons]::OK,
    $Icon = [System.Windows.Forms.MessageBoxIcon]::Information
  )
  return [System.Windows.Forms.MessageBox]::Show($script:toolboxForm, $Text, $Title, $Buttons, $Icon)
}

function Test-QueueEditable {
  if ($null -eq $script:queueSession) { return $true }
  foreach ($job in @($script:queueSession.jobs)) {
    if ($job.status -ne 'planned') { return $false }
  }
  return $true
}

function Reset-QueueIndexes {
  $number = 1
  foreach ($job in @($script:queueJobs)) {
    $job.index = $number
    $number++
  }
}

function Sync-QueueEditors {
  if ($null -eq $script:queueEditors) { return }
  $index = $script:queueDetailIndex
  if ($null -eq $index -or $index -lt 0) { return }
  if ($null -eq $script:queueJobs -or $index -ge $script:queueJobs.Count) { return }
  $job = $script:queueJobs[$index]
  $culture = [System.Globalization.CultureInfo]::InvariantCulture
  foreach ($spec in @($job.schema)) {
    $name = [string]$spec.name
    if (-not $script:queueEditors.ContainsKey($name)) { continue }
    $control = $script:queueEditors[$name]
    if ($spec.type -eq 'boolean') {
      $job.inputs[$name] = [bool]$control.Checked
    } elseif ($spec.type -eq 'string-list') {
      $parts = New-Object System.Collections.Generic.List[string]
      foreach ($line in ($control.Text -split "\r\n|\n")) {
        $trimmed = $line.Trim()
        if (-not [string]::IsNullOrWhiteSpace($trimmed)) { $parts.Add($trimmed) }
      }
      $items = $parts.ToArray()
      $job.inputs[$name] = $items
    } elseif ($spec.type -eq 'integer' -or $spec.type -eq 'number') {
      $text = $control.Text.Trim()
      if ($text -match '^-?\d+$') {
        $job.inputs[$name] = [int64]$text
      } elseif ($spec.type -eq 'number' -and $text -match '^-?\d+(\.\d+)?$') {
        $job.inputs[$name] = [double]::Parse($text, $culture)
      } else {
        $job.inputs[$name] = $text
      }
    } else {
      $job.inputs[$name] = $control.Text.Trim()
    }
  }
  if ($job.dryRunInput) {
    $job.run = [bool]$job.inputs[$job.dryRunInput]
  }
}

function Show-QueueDetail {
  $panel = $script:queueDetail
  $panel.Controls.Clear()
  $script:queueEditors = @{}
  $index = -1
  if ($null -ne $script:queueJobList) { $index = $script:queueJobList.SelectedIndex }
  $script:queueDetailIndex = $index
  if ($index -lt 0 -or $null -eq $script:queueJobs -or $index -ge $script:queueJobs.Count) { return }
  $job = $script:queueJobs[$index]
  $editable = Test-QueueEditable
  $y = 4
  foreach ($spec in @($job.schema)) {
    $name = [string]$spec.name
    $fieldType = [string]$spec.type
    if ($fieldType -eq 'boolean') {
      $check = New-Object System.Windows.Forms.CheckBox
      $check.Location = New-Object System.Drawing.Point(4, $y)
      $check.Size = New-Object System.Drawing.Size(360, 24)
      $check.Text = [string]$spec.label
      $check.Checked = [bool]$job.inputs[$name]
      $allowWrite = (-not $spec.writesModel) -or $script:queueConfirm.Checked
      $check.Enabled = $editable -and $allowWrite
      if ($spec.writesModel -and -not $script:queueConfirm.Checked) {
        $check.Checked = $false
        $job.inputs[$name] = $false
        $job.run = $false
      }
      $panel.Controls.Add($check)
      $script:queueEditors[$name] = $check
      if ($spec.help) { $script:queueTip.SetToolTip($check, [string]$spec.help) }
      $y += 28
      continue
    }
    $label = New-Object System.Windows.Forms.Label
    $label.Location = New-Object System.Drawing.Point(4, ($y + 4))
    $label.Size = New-Object System.Drawing.Size(110, 20)
    $label.Text = [string]$spec.label
    $panel.Controls.Add($label)
    $box = New-Object System.Windows.Forms.TextBox
    $box.Location = New-Object System.Drawing.Point(116, $y)
    $boxHeight = 22
    if ($fieldType -eq 'string-list') {
      $box.Multiline = $true
      $box.ScrollBars = 'Vertical'
      $box.AcceptsReturn = $true
      $boxHeight = 44
      $lines = @($job.inputs[$name])
      $box.Text = ($lines -join "`r`n")
    } else {
      $box.Text = [string]$job.inputs[$name]
    }
    $boxWidth = 210
    if ($fieldType -eq 'directory' -or $fieldType -eq 'file') { $boxWidth = 176 }
    $box.Size = New-Object System.Drawing.Size($boxWidth, $boxHeight)
    $box.ReadOnly = -not $editable
    $panel.Controls.Add($box)
    $script:queueEditors[$name] = $box
    if ($spec.help) { $script:queueTip.SetToolTip($box, [string]$spec.help) }
    if ($editable -and ($fieldType -eq 'directory' -or $fieldType -eq 'file')) {
      $browse = New-Object System.Windows.Forms.Button
      $browse.Location = New-Object System.Drawing.Point(296, $y)
      $browse.Size = New-Object System.Drawing.Size(36, 22)
      $browse.Text = '...'
      $target = $box
      $owner = $script:toolboxForm
      $pickedType = $fieldType
      $browse.Add_Click({
        if ($pickedType -eq 'directory') {
          $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
          if ($dialog.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) {
            $target.Text = $dialog.SelectedPath
          }
        } else {
          $dialog = New-Object System.Windows.Forms.OpenFileDialog
          $dialog.CheckFileExists = $true
          $dialog.Filter = 'All files (*.*)|*.*'
          if ($dialog.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) {
            $target.Text = $dialog.FileName
          }
        }
      }.GetNewClosure())
      $panel.Controls.Add($browse)
    }
    $y += ($boxHeight + 6)
  }
}

function Update-QueueLock {
  $locked = -not (Test-QueueEditable)
  foreach ($button in @($script:queueAdd, $script:queueRemove, $script:queueUp, $script:queueDown, $script:queueLoad, $script:queueApply)) {
    if ($null -ne $button) { $button.Enabled = -not $locked }
  }
  if ($null -ne $script:queueProjectBox) { $script:queueProjectBox.ReadOnly = $locked }
  if ($null -ne $script:queueFolderBox) { $script:queueFolderBox.ReadOnly = $locked }
  if ($null -ne $script:sessionNameBox) { $script:sessionNameBox.ReadOnly = $locked }
  if ($null -ne $script:queueConfirm) { $script:queueConfirm.Enabled = -not $locked }
  if ($null -ne $script:queueChecks) { $script:queueChecks.Enabled = -not $locked }
}

function Update-QueueJobList {
  param([int]$SelectIndex = -1)
  if (-not $script:queueRefresh) { Sync-QueueEditors }
  $script:queueRefresh = $true
  try {
    $list = $script:queueJobList
    $list.Items.Clear()
    foreach ($job in @($script:queueJobs)) {
      $mode = '試跑'
      if ($job.run) { $mode = '寫入' }
      $suffix = ''
      if ($null -ne $script:queueSession) {
        foreach ($record in @($script:queueSession.jobs)) {
          if ([int]$record.index -eq [int]$job.index) {
            $suffix = ' — ' + (Format-DynamoStatusText $record.status)
            break
          }
        }
      }
      [void]$list.Items.Add(('{0}. {1} — {2}{3}' -f $job.index, $job.toolName, $mode, $suffix))
    }
    if ($SelectIndex -ge 0 -and $SelectIndex -lt $list.Items.Count) {
      $list.SelectedIndex = $SelectIndex
    } elseif ($list.Items.Count -gt 0 -and $list.SelectedIndex -lt 0) {
      $list.SelectedIndex = 0
    }
  } finally {
    $script:queueRefresh = $false
  }
  Show-QueueDetail
  Update-QueueLock
}

function Get-QueueTaskConfig {
  Sync-QueueEditors
  $name = 'batch'
  if ($null -ne $script:sessionNameBox -and -not [string]::IsNullOrWhiteSpace($script:sessionNameBox.Text)) {
    $name = $script:sessionNameBox.Text.Trim()
  }
  $project = ''
  if ($null -ne $script:queueProjectBox) { $project = $script:queueProjectBox.Text.Trim().Trim('"') }
  $confirm = $false
  if ($null -ne $script:queueConfirm) { $confirm = [bool]$script:queueConfirm.Checked }
  return ConvertTo-DynamoTaskConfig -SessionName $name -HostProject $project -ConfirmWrite $confirm -Drafts $script:queueJobs
}

function Set-QueueFromPlan {
  param($Plan)
  $script:queueJobs = New-Object System.Collections.ArrayList
  foreach ($job in @($Plan.jobs)) {
    $draft = New-DynamoJobDraft -Catalog $script:catalog -ToolId $job.toolId
    foreach ($key in @($job.inputs.Keys)) {
      $draft.inputs[$key] = Copy-DynamoValue -Value $job.inputs[$key]
    }
    $draft.run = [bool]$job.run
    $draft.index = [int]$job.index
    [void]$script:queueJobs.Add($draft)
  }
  $script:queueProjectBox.Text = [string]$Plan.hostProject
  $script:sessionNameBox.Text = [string]$Plan.sessionName
  $script:queueConfirmGuard = $true
  $script:queueConfirm.Checked = [bool]$Plan.confirmWrite
  $script:queueConfirmGuard = $false
  $used = @{}
  foreach ($job in @($script:queueJobs)) { $used[$job.toolId] = $true }
  for ($i = 0; $i -lt @($script:catalog).Count; $i++) {
    $script:queueChecks.SetItemChecked($i, $used.ContainsKey([string]$script:catalog[$i].Id))
  }
  $script:queueSession = $null
  $script:queueSessionDir = $null
  Update-QueueJobList -SelectIndex 0
}

function Show-QueueResultForm {
  param($Job)
  $script:queueResult = $null
  $dialog = New-Object System.Windows.Forms.Form
  $dialog.Text = '記錄結果 — ' + $Job.toolName
  $dialog.FormBorderStyle = 'FixedDialog'
  $dialog.MaximizeBox = $false
  $dialog.MinimizeBox = $false
  $dialog.StartPosition = 'CenterParent'
  $dialog.ClientSize = New-Object System.Drawing.Size(460, 360)
  $dialog.Font = $script:toolboxForm.Font

  $statusLabel = New-Object System.Windows.Forms.Label
  $statusLabel.Location = New-Object System.Drawing.Point(16, 12)
  $statusLabel.Size = New-Object System.Drawing.Size(420, 20)
  $statusLabel.Text = '狀態'
  $dialog.Controls.Add($statusLabel)

  $combo = New-Object System.Windows.Forms.ComboBox
  $combo.Location = New-Object System.Drawing.Point(16, 36)
  $combo.Size = New-Object System.Drawing.Size(200, 24)
  $combo.DropDownStyle = 'DropDownList'
  $combo.Items.Add('試跑完成')
  $combo.Items.Add('失敗')
  $combo.Items.Add('略過')
  if ($Job.run -and $script:queueSession.confirmWrite) { $combo.Items.Add('已寫入') }
  $combo.SelectedIndex = 0
  $dialog.Controls.Add($combo)

  $countNames = @('files', 'changed', 'skipped', 'failed')
  $countLabels = @('檔案數', '變更數', '略過數', '失敗數')
  $countBoxes = @{}
  for ($i = 0; $i -lt $countNames.Count; $i++) {
    $label = New-Object System.Windows.Forms.Label
    $label.Location = New-Object System.Drawing.Point((16 + ($i * 110)), 76)
    $label.Size = New-Object System.Drawing.Size(100, 20)
    $label.Text = $countLabels[$i]
    $dialog.Controls.Add($label)
    $box = New-Object System.Windows.Forms.TextBox
    $box.Location = New-Object System.Drawing.Point((16 + ($i * 110)), 98)
    $box.Size = New-Object System.Drawing.Size(96, 24)
    $dialog.Controls.Add($box)
    $countBoxes[$countNames[$i]] = $box
  }

  $errorLabel = New-Object System.Windows.Forms.Label
  $errorLabel.Location = New-Object System.Drawing.Point(16, 136)
  $errorLabel.Size = New-Object System.Drawing.Size(420, 20)
  $errorLabel.Text = '錯誤（一行一則，可留白）'
  $dialog.Controls.Add($errorLabel)

  $errorBox = New-Object System.Windows.Forms.TextBox
  $errorBox.Location = New-Object System.Drawing.Point(16, 160)
  $errorBox.Size = New-Object System.Drawing.Size(428, 120)
  $errorBox.Multiline = $true
  $errorBox.ScrollBars = 'Vertical'
  $errorBox.AcceptsReturn = $true
  $dialog.Controls.Add($errorBox)

  $codes = @{
    '試跑完成' = 'dry-run'
    '失敗' = 'failed'
    '略過' = 'skipped'
    '已寫入' = 'written'
  }
  $ok = New-Object System.Windows.Forms.Button
  $ok.Location = New-Object System.Drawing.Point(16, 308)
  $ok.Size = New-Object System.Drawing.Size(120, 32)
  $ok.Text = '記錄'
  $ok.Add_Click({
    $counts = [ordered]@{}
    foreach ($key in @($countBoxes.Keys)) {
      $text = $countBoxes[$key].Text.Trim()
      if ([string]::IsNullOrWhiteSpace($text)) { continue }
      if ($text -notmatch '^\d+$') {
        [System.Windows.Forms.MessageBox]::Show($dialog, '計數必須是 0 以上的整數。', '記錄結果') | Out-Null
        return
      }
      $counts[$key] = [int64]$text
    }
    $errors = New-Object System.Collections.Generic.List[string]
    foreach ($line in ($errorBox.Text -split "\r\n|\n")) {
      if (-not [string]::IsNullOrWhiteSpace($line)) { $errors.Add($line.Trim()) }
    }
    $errorItems = $errors.ToArray()
    $script:queueResult = [ordered]@{
      Status = $codes[[string]$combo.SelectedItem]
      Counts = $counts
      Errors = $errorItems
    }
    $dialog.Close()
  }.GetNewClosure())
  $dialog.Controls.Add($ok)

  $cancel = New-Object System.Windows.Forms.Button
  $cancel.Location = New-Object System.Drawing.Point(148, 308)
  $cancel.Size = New-Object System.Drawing.Size(120, 32)
  $cancel.Text = '取消'
  $cancel.Add_Click({ $dialog.Close() }.GetNewClosure())
  $dialog.Controls.Add($cancel)
  $dialog.CancelButton = $cancel
  [void]$dialog.ShowDialog($script:toolboxForm)
  return $script:queueResult
}

function Start-QueueNextJob {
  if ($null -eq $script:queueJobs -or $script:queueJobs.Count -lt 1) {
    Show-QueueNotice '佇列是空的。先勾選工具再按加入勾選，或載入一份任務設定。' | Out-Null
    return
  }
  try {
    $config = Get-QueueTaskConfig
    $resolved = Resolve-DynamoTaskQueue -Catalog $script:catalog -Config $config
  } catch {
    Show-QueueNotice $_.Exception.Message '任務設定' ([System.Windows.Forms.MessageBoxButtons]::OK) ([System.Windows.Forms.MessageBoxIcon]::Warning) | Out-Null
    return
  }
  $project = [string]$resolved.hostProject
  if (-not (Test-Path -LiteralPath $project -PathType Leaf)) {
    Show-QueueNotice 'Choose an existing .rvt file. Templates (.rte) are not opened.' '批次佇列' ([System.Windows.Forms.MessageBoxButtons]::OK) ([System.Windows.Forms.MessageBoxIcon]::Warning) | Out-Null
    return
  }
  if (Test-Revit2025Running) {
    Show-QueueNotice $script:RevitAlreadyRunningMessage 'Close Revit first' ([System.Windows.Forms.MessageBoxButtons]::OK) ([System.Windows.Forms.MessageBoxIcon]::Warning) | Out-Null
    return
  }
  try {
    if ($null -eq $script:queueSession) {
      $sessionId = New-DynamoSessionId -SessionName $resolved.sessionName
      $script:queueSession = New-DynamoQueueSession -Plan $resolved -SessionId $sessionId
      $script:queueSessionDir = Join-Path (Get-DynamoDefaultSessionRoot) $script:queueSession.sessionId
    } elseif (Test-QueueEditable) {
      Update-DynamoQueueSessionPlan -Session $script:queueSession -Plan $resolved | Out-Null
    }
    Export-DynamoQueueSession -Session $script:queueSession -OutputDirectory $script:queueSessionDir | Out-Null
    $dispatch = Get-DynamoQueueDispatchPlan -Session $script:queueSession
  } catch {
    Show-QueueNotice $_.Exception.Message | Out-Null
    return
  }
  if ($dispatch.ExecuteGraph -or -not $dispatch.ManualMode) {
    throw '拒絕開啟：佇列只能以手動模式載入圖形。'
  }
  $job = $null
  foreach ($record in @($script:queueSession.jobs)) {
    if ([int]$record.index -eq [int]$dispatch.Index) { $job = $record; break }
  }
  Export-DynamoJobCard -Session $script:queueSession -Job $job -Catalog $script:catalog -OutputDirectory $script:queueSessionDir | Out-Null
  $card = Format-DynamoJobCard -Session $script:queueSession -Job $job -Catalog $script:catalog
  if ($job.run) {
    $writeAnswer = Show-QueueNotice "這個工作是寫入模式（$($job.toolName)）。`r`nRevit 會以手動模式開啟圖形。你要在 Dynamo 裡把 Run 設成 True 之後，自己按執行。`r`n確定要開啟？" '確認寫入' ([System.Windows.Forms.MessageBoxButtons]::YesNo) ([System.Windows.Forms.MessageBoxIcon]::Warning)
    if ($writeAnswer -ne [System.Windows.Forms.DialogResult]::Yes) { return }
  }
  $openAnswer = Show-QueueNotice $card '手動輸入' ([System.Windows.Forms.MessageBoxButtons]::OKCancel) ([System.Windows.Forms.MessageBoxIcon]::Information)
  if ($openAnswer -ne [System.Windows.Forms.DialogResult]::OK) { return }
  try {
    & $script:journalScript -ToolId $dispatch.ToolId -Project $dispatch.Project -Launch
  } catch {
    Show-QueueNotice $_.Exception.Message '批次佇列' ([System.Windows.Forms.MessageBoxButtons]::OK) ([System.Windows.Forms.MessageBoxIcon]::Warning) | Out-Null
    return
  }
  Set-DynamoQueueJobOpened -Session $script:queueSession -Index $dispatch.Index | Out-Null
  Export-DynamoQueueSession -Session $script:queueSession -OutputDirectory $script:queueSessionDir | Out-Null
  $script:queueStatus.Text = "已用手動模式開啟 $($job.toolName)。做完並關閉 Revit 後，按記錄結果。`r`n$script:queueSessionDir"
  Update-QueueJobList -SelectIndex ($dispatch.Index - 1)
}

function Save-QueueResult {
  if ($null -eq $script:queueSession) {
    Show-QueueNotice '目前沒有等待記錄的工作。請先開啟下一步。' | Out-Null
    return
  }
  $job = $null
  foreach ($record in @($script:queueSession.jobs)) {
    if ($record.status -eq 'opened-manual') { $job = $record; break }
  }
  if ($null -eq $job) {
    Show-QueueNotice '目前沒有等待記錄的工作。請先開啟下一步。' | Out-Null
    return
  }
  $result = Show-QueueResultForm -Job $job
  if ($null -eq $result) { return }
  try {
    Set-DynamoQueueJobResult -Session $script:queueSession -Index $job.index -Status $result.Status -Counts $result.Counts -Errors $result.Errors | Out-Null
    Export-DynamoQueueSession -Session $script:queueSession -OutputDirectory $script:queueSessionDir | Out-Null
  } catch {
    Show-QueueNotice $_.Exception.Message '記錄結果' ([System.Windows.Forms.MessageBoxButtons]::OK) ([System.Windows.Forms.MessageBoxIcon]::Warning) | Out-Null
    return
  }
  $script:queueStatus.Text = "已記錄 $($job.toolName)：$($result.Status)。報告在`r`n$script:queueSessionDir"
  Update-QueueJobList -SelectIndex ($job.index - 1)
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

  Add-Type -AssemblyName System.Windows.Forms
  Add-Type -AssemblyName System.Drawing

  $fontName = 'Segoe UI'
  $installed = New-Object System.Drawing.Text.InstalledFontCollection
  $families = @($installed.Families | ForEach-Object { $_.Name })
  foreach ($candidate in @('Microsoft JhengHei UI', 'Microsoft JhengHei', 'PMingLiU', 'Segoe UI')) {
    if ($families -contains $candidate) { $fontName = $candidate; break }
  }

  $script:catalog = Get-DynamoToolboxCatalog
  $script:journalScript = Join-Path $PSScriptRoot 'poc\New-DynamoJournal.ps1'
  if (-not (Test-Path -LiteralPath $script:journalScript)) {
    throw "Journal writer not found: $script:journalScript"
  }
  $script:queueJobs = New-Object System.Collections.ArrayList
  $script:queueEditors = @{}
  $script:queueDetailIndex = -1
  $script:queueRefresh = $false
  $script:queueConfirmGuard = $false
  $script:queueSession = $null
  $script:queueSessionDir = $null

  $form = New-Object System.Windows.Forms.Form
  $script:toolboxForm = $form
  $form.Text = 'Dynamo toolbox'
  $form.FormBorderStyle = 'FixedDialog'
  $form.MaximizeBox = $false
  $form.StartPosition = 'CenterScreen'
  $form.ClientSize = New-Object System.Drawing.Size(780, 720)
  $form.Font = New-Object System.Drawing.Font($fontName, 10)
  $script:queueTip = New-Object System.Windows.Forms.ToolTip

  $tabs = New-Object System.Windows.Forms.TabControl
  $tabs.Location = New-Object System.Drawing.Point(8, 8)
  $tabs.Size = New-Object System.Drawing.Size(764, 704)
  $form.Controls.Add($tabs)

  $single = New-Object System.Windows.Forms.TabPage
  $single.Text = '單次開啟'
  $tabs.TabPages.Add($single)

  $intro = New-Object System.Windows.Forms.Label
  $intro.Location = New-Object System.Drawing.Point(16, 12)
  $intro.Size = New-Object System.Drawing.Size(720, 40)
  $intro.Text = 'Pick one tool and an existing .rvt. Revit 2025 must be closed. The graph loads in manual mode and does not run.'
  $single.Controls.Add($intro)

  $toolLabel = New-Object System.Windows.Forms.Label
  $toolLabel.Location = New-Object System.Drawing.Point(16, 56)
  $toolLabel.Size = New-Object System.Drawing.Size(720, 20)
  $toolLabel.Text = 'Tool'
  $single.Controls.Add($toolLabel)

  $script:toolList = New-Object System.Windows.Forms.ListBox
  $script:toolList.Location = New-Object System.Drawing.Point(16, 80)
  $script:toolList.Size = New-Object System.Drawing.Size(720, 180)
  $script:toolList.IntegralHeight = $false
  foreach ($tool in $script:catalog) {
    [void]$script:toolList.Items.Add($tool.Name)
  }
  $script:toolList.SelectedIndex = 0
  $single.Controls.Add($script:toolList)

  $projectLabel = New-Object System.Windows.Forms.Label
  $projectLabel.Location = New-Object System.Drawing.Point(16, 272)
  $projectLabel.Size = New-Object System.Drawing.Size(720, 20)
  $projectLabel.Text = 'Existing project (.rvt)'
  $single.Controls.Add($projectLabel)

  $script:projectBox = New-Object System.Windows.Forms.TextBox
  $script:projectBox.Location = New-Object System.Drawing.Point(16, 296)
  $script:projectBox.Size = New-Object System.Drawing.Size(560, 24)
  $single.Controls.Add($script:projectBox)

  $browse = New-Object System.Windows.Forms.Button
  $browse.Location = New-Object System.Drawing.Point(588, 294)
  $browse.Size = New-Object System.Drawing.Size(140, 28)
  $browse.Text = '&Browse...'
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
  $single.Controls.Add($browse)

  $hint = New-Object System.Windows.Forms.Label
  $hint.Location = New-Object System.Drawing.Point(16, 336)
  $hint.Size = New-Object System.Drawing.Size(720, 48)
  $hint.Text = 'Templates (.rte) are not opened. If Revit 2025 is already running, close it before Launch.'
  $single.Controls.Add($hint)

  $launch = New-Object System.Windows.Forms.Button
  $launch.Location = New-Object System.Drawing.Point(16, 400)
  $launch.Size = New-Object System.Drawing.Size(140, 32)
  $launch.Text = '&Launch'
  $launch.Add_Click({
    $index = $script:toolList.SelectedIndex
    if ($index -lt 0 -or $index -ge @($script:catalog).Count) {
      [System.Windows.Forms.MessageBox]::Show($script:toolboxForm, 'Pick one tool.', 'Dynamo toolbox', [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Warning) | Out-Null
      return
    }
    $project = $script:projectBox.Text.Trim().Trim('"')
    $extension = [System.IO.Path]::GetExtension($project)
    $isRvt = $extension -and $extension.Equals('.rvt', [System.StringComparison]::OrdinalIgnoreCase)
    if (-not $isRvt -or -not (Test-Path -LiteralPath $project -PathType Leaf)) {
      [System.Windows.Forms.MessageBox]::Show($script:toolboxForm, 'Choose an existing .rvt file. Templates (.rte) are not opened.', 'Dynamo toolbox', [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Warning) | Out-Null
      return
    }
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
  $single.Controls.Add($launch)

  $close = New-Object System.Windows.Forms.Button
  $close.Location = New-Object System.Drawing.Point(168, 400)
  $close.Size = New-Object System.Drawing.Size(140, 32)
  $close.Text = '&Close'
  $close.Add_Click({ $script:toolboxForm.Close() })
  $single.Controls.Add($close)
  $form.AcceptButton = $launch
  $form.CancelButton = $close

  $queue = New-Object System.Windows.Forms.TabPage
  $queue.Text = '批次佇列'
  $tabs.TabPages.Add($queue)

  $queueIntro = New-Object System.Windows.Forms.Label
  $queueIntro.Location = New-Object System.Drawing.Point(16, 8)
  $queueIntro.Size = New-Object System.Drawing.Size(730, 40)
  $queueIntro.Text = '勾選要依序處理的工具。每一筆都用手動模式開啟，執行按鈕要你在 Dynamo 裡按。寫入開關預設是 False。'
  $queue.Controls.Add($queueIntro)

  $script:queueChecks = New-Object System.Windows.Forms.CheckedListBox
  $script:queueChecks.Location = New-Object System.Drawing.Point(16, 52)
  $script:queueChecks.Size = New-Object System.Drawing.Size(730, 108)
  $script:queueChecks.CheckOnClick = $true
  $script:queueChecks.IntegralHeight = $false
  foreach ($tool in $script:catalog) {
    [void]$script:queueChecks.Items.Add($tool.Name)
  }
  $queue.Controls.Add($script:queueChecks)

  $queueProjectLabel = New-Object System.Windows.Forms.Label
  $queueProjectLabel.Location = New-Object System.Drawing.Point(16, 166)
  $queueProjectLabel.Size = New-Object System.Drawing.Size(360, 20)
  $queueProjectLabel.Text = '宿主專案 (.rvt)'
  $queue.Controls.Add($queueProjectLabel)

  $script:queueProjectBox = New-Object System.Windows.Forms.TextBox
  $script:queueProjectBox.Location = New-Object System.Drawing.Point(16, 188)
  $script:queueProjectBox.Size = New-Object System.Drawing.Size(560, 24)
  $queue.Controls.Add($script:queueProjectBox)

  $queueBrowse = New-Object System.Windows.Forms.Button
  $queueBrowse.Location = New-Object System.Drawing.Point(584, 186)
  $queueBrowse.Size = New-Object System.Drawing.Size(160, 28)
  $queueBrowse.Text = '選宿主...'
  $queueBrowse.Add_Click({
    $dialog = New-Object System.Windows.Forms.OpenFileDialog
    $dialog.Filter = 'Revit project (*.rvt)|*.rvt'
    $dialog.Title = 'Select an existing Revit project'
    $dialog.CheckFileExists = $true
    if ($dialog.ShowDialog($script:toolboxForm) -eq [System.Windows.Forms.DialogResult]::OK) {
      $script:queueProjectBox.Text = $dialog.FileName
    }
  })
  $queue.Controls.Add($queueBrowse)

  $folderLabel = New-Object System.Windows.Forms.Label
  $folderLabel.Location = New-Object System.Drawing.Point(16, 220)
  $folderLabel.Size = New-Object System.Drawing.Size(420, 20)
  $folderLabel.Text = '目標資料夾（只填還沒填的工作）'
  $queue.Controls.Add($folderLabel)

  $script:queueFolderBox = New-Object System.Windows.Forms.TextBox
  $script:queueFolderBox.Location = New-Object System.Drawing.Point(16, 242)
  $script:queueFolderBox.Size = New-Object System.Drawing.Size(420, 24)
  $queue.Controls.Add($script:queueFolderBox)

  $folderBrowse = New-Object System.Windows.Forms.Button
  $folderBrowse.Location = New-Object System.Drawing.Point(444, 240)
  $folderBrowse.Size = New-Object System.Drawing.Size(80, 28)
  $folderBrowse.Text = '資料夾'
  $folderBrowse.Add_Click({
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    if ($dialog.ShowDialog($script:toolboxForm) -eq [System.Windows.Forms.DialogResult]::OK) {
      $script:queueFolderBox.Text = $dialog.SelectedPath
    }
  })
  $queue.Controls.Add($folderBrowse)

  $script:queueApply = New-Object System.Windows.Forms.Button
  $script:queueApply.Location = New-Object System.Drawing.Point(532, 240)
  $script:queueApply.Size = New-Object System.Drawing.Size(90, 28)
  $script:queueApply.Text = '套用'
  $script:queueApply.Add_Click({
    if (-not (Test-QueueEditable)) {
      Show-QueueNotice '這個工作階段已經開始，不能再改佇列。' | Out-Null
      return
    }
    $folder = $script:queueFolderBox.Text.Trim()
    if ([string]::IsNullOrWhiteSpace($folder)) { return }
    Sync-QueueEditors
    foreach ($job in @($script:queueJobs)) {
      if ($job.inputs.Contains('directory') -and [string]::IsNullOrWhiteSpace([string]$job.inputs['directory'])) {
        $job.inputs['directory'] = $folder
      }
    }
    Show-QueueDetail
  })
  $queue.Controls.Add($script:queueApply)

  $nameLabel = New-Object System.Windows.Forms.Label
  $nameLabel.Location = New-Object System.Drawing.Point(16, 276)
  $nameLabel.Size = New-Object System.Drawing.Size(120, 24)
  $nameLabel.Text = '工作階段名稱'
  $queue.Controls.Add($nameLabel)

  $script:sessionNameBox = New-Object System.Windows.Forms.TextBox
  $script:sessionNameBox.Location = New-Object System.Drawing.Point(140, 272)
  $script:sessionNameBox.Size = New-Object System.Drawing.Size(180, 24)
  $script:sessionNameBox.Text = 'batch'
  $queue.Controls.Add($script:sessionNameBox)

  $script:queueLoad = New-Object System.Windows.Forms.Button
  $script:queueLoad.Location = New-Object System.Drawing.Point(336, 270)
  $script:queueLoad.Size = New-Object System.Drawing.Size(100, 28)
  $script:queueLoad.Text = '載入設定'
  $script:queueLoad.Add_Click({
    if (-not (Test-QueueEditable)) {
      Show-QueueNotice '這個工作階段已經開始，不能再改佇列。' | Out-Null
      return
    }
    $dialog = New-Object System.Windows.Forms.OpenFileDialog
    $dialog.Filter = 'Task config (*.json)|*.json'
    $dialog.CheckFileExists = $true
    if ($dialog.ShowDialog($script:toolboxForm) -ne [System.Windows.Forms.DialogResult]::OK) { return }
    try {
      $config = Read-DynamoTaskConfig -Path $dialog.FileName
      if (Test-DynamoTaskConfigRequestsWrite -Catalog $script:catalog -Config $config) {
        $answer = Show-QueueNotice "這份任務設定允許寫入模型。`r`n圖形仍以手動模式開啟。確定要載入寫入模式？`r`n選否會把所有工作改回試跑。" '確認寫入' ([System.Windows.Forms.MessageBoxButtons]::YesNo) ([System.Windows.Forms.MessageBoxIcon]::Warning)
        if ($answer -ne [System.Windows.Forms.DialogResult]::Yes) {
          Reset-DynamoTaskConfigToDryRun -Catalog $script:catalog -Config $config | Out-Null
        }
      }
      $plan = Resolve-DynamoTaskQueue -Catalog $script:catalog -Config $config
      Set-QueueFromPlan -Plan $plan
      $script:queueStatus.Text = '已載入任務設定。寫入開關為 False 的工作會以試跑開啟。'
    } catch {
      Show-QueueNotice $_.Exception.Message '任務設定' ([System.Windows.Forms.MessageBoxButtons]::OK) ([System.Windows.Forms.MessageBoxIcon]::Warning) | Out-Null
    }
  })
  $queue.Controls.Add($script:queueLoad)

  $script:queueSave = New-Object System.Windows.Forms.Button
  $script:queueSave.Location = New-Object System.Drawing.Point(444, 270)
  $script:queueSave.Size = New-Object System.Drawing.Size(100, 28)
  $script:queueSave.Text = '儲存設定'
  $script:queueSave.Add_Click({
    if ($script:queueJobs.Count -lt 1) {
      Show-QueueNotice '佇列是空的，沒有可以儲存的工作。' | Out-Null
      return
    }
    try {
      $config = Get-QueueTaskConfig
      Resolve-DynamoTaskQueue -Catalog $script:catalog -Config $config | Out-Null
      $dialog = New-Object System.Windows.Forms.SaveFileDialog
      $dialog.Filter = 'Task config (*.json)|*.json'
      $dialog.FileName = 'task-config.json'
      if ($dialog.ShowDialog($script:toolboxForm) -ne [System.Windows.Forms.DialogResult]::OK) { return }
      Write-DynamoUtf8Text -Path $dialog.FileName -Text ((ConvertTo-DynamoJson -Value $config) + "`r`n")
      $script:queueStatus.Text = '已儲存任務設定：' + $dialog.FileName
    } catch {
      Show-QueueNotice $_.Exception.Message '任務設定' ([System.Windows.Forms.MessageBoxButtons]::OK) ([System.Windows.Forms.MessageBoxIcon]::Warning) | Out-Null
    }
  })
  $queue.Controls.Add($script:queueSave)

  $script:queueAdd = New-Object System.Windows.Forms.Button
  $script:queueAdd.Location = New-Object System.Drawing.Point(16, 308)
  $script:queueAdd.Size = New-Object System.Drawing.Size(110, 28)
  $script:queueAdd.Text = '加入勾選'
  $script:queueAdd.Add_Click({
    if (-not (Test-QueueEditable)) {
      Show-QueueNotice '這個工作階段已經開始，不能再改佇列。' | Out-Null
      return
    }
    $ids = New-Object System.Collections.Generic.List[string]
    for ($i = 0; $i -lt $script:queueChecks.Items.Count; $i++) {
      if ($script:queueChecks.GetItemChecked($i)) { $ids.Add([string]$script:catalog[$i].Id) }
    }
    if ($ids.Count -lt 1) {
      Show-QueueNotice '先勾選至少一個工具。' | Out-Null
      return
    }
    try {
      $ordered = Get-DynamoCatalogToolOrder -Catalog $script:catalog -ToolIds $ids.ToArray()
      foreach ($toolId in $ordered) {
        [void]$script:queueJobs.Add((New-DynamoJobDraft -Catalog $script:catalog -ToolId $toolId))
      }
      Reset-QueueIndexes
      Update-QueueJobList -SelectIndex ($script:queueJobs.Count - 1)
    } catch {
      Show-QueueNotice $_.Exception.Message | Out-Null
    }
  })
  $queue.Controls.Add($script:queueAdd)

  $script:queueRemove = New-Object System.Windows.Forms.Button
  $script:queueRemove.Location = New-Object System.Drawing.Point(134, 308)
  $script:queueRemove.Size = New-Object System.Drawing.Size(80, 28)
  $script:queueRemove.Text = '移除'
  $script:queueRemove.Add_Click({
    if (-not (Test-QueueEditable)) {
      Show-QueueNotice '這個工作階段已經開始，不能再改佇列。' | Out-Null
      return
    }
    $index = $script:queueJobList.SelectedIndex + 1
    if ($index -lt 1) { return }
    $kept = Remove-DynamoQueueEntry -Entries $script:queueJobs -Index $index
    $script:queueJobs = New-Object System.Collections.ArrayList
    foreach ($entry in $kept) { [void]$script:queueJobs.Add($entry) }
    $next = $index - 2
    if ($next -lt 0) { $next = 0 }
    Update-QueueJobList -SelectIndex $next
  })
  $queue.Controls.Add($script:queueRemove)

  $script:queueUp = New-Object System.Windows.Forms.Button
  $script:queueUp.Location = New-Object System.Drawing.Point(222, 308)
  $script:queueUp.Size = New-Object System.Drawing.Size(70, 28)
  $script:queueUp.Text = '上移'
  $script:queueUp.Add_Click({
    if (-not (Test-QueueEditable)) { return }
    $index = $script:queueJobList.SelectedIndex + 1
    if ($index -lt 2) { return }
    $moved = Move-DynamoQueueEntries -Entries $script:queueJobs -Index $index -Offset -1
    $script:queueJobs = New-Object System.Collections.ArrayList
    foreach ($entry in $moved) { [void]$script:queueJobs.Add($entry) }
    Update-QueueJobList -SelectIndex ($index - 2)
  })
  $queue.Controls.Add($script:queueUp)

  $script:queueDown = New-Object System.Windows.Forms.Button
  $script:queueDown.Location = New-Object System.Drawing.Point(300, 308)
  $script:queueDown.Size = New-Object System.Drawing.Size(70, 28)
  $script:queueDown.Text = '下移'
  $script:queueDown.Add_Click({
    if (-not (Test-QueueEditable)) { return }
    $index = $script:queueJobList.SelectedIndex + 1
    if ($index -lt 1 -or $index -ge $script:queueJobs.Count) { return }
    $moved = Move-DynamoQueueEntries -Entries $script:queueJobs -Index $index -Offset 1
    $script:queueJobs = New-Object System.Collections.ArrayList
    foreach ($entry in $moved) { [void]$script:queueJobs.Add($entry) }
    Update-QueueJobList -SelectIndex $index
  })
  $queue.Controls.Add($script:queueDown)

  $jobLabel = New-Object System.Windows.Forms.Label
  $jobLabel.Location = New-Object System.Drawing.Point(16, 344)
  $jobLabel.Size = New-Object System.Drawing.Size(320, 20)
  $jobLabel.Text = '佇列順序'
  $queue.Controls.Add($jobLabel)

  $detailLabel = New-Object System.Windows.Forms.Label
  $detailLabel.Location = New-Object System.Drawing.Point(360, 344)
  $detailLabel.Size = New-Object System.Drawing.Size(380, 20)
  $detailLabel.Text = '手動輸入（對照 Dynamo）'
  $queue.Controls.Add($detailLabel)

  $script:queueJobList = New-Object System.Windows.Forms.ListBox
  $script:queueJobList.Location = New-Object System.Drawing.Point(16, 366)
  $script:queueJobList.Size = New-Object System.Drawing.Size(330, 150)
  $script:queueJobList.IntegralHeight = $false
  $script:queueJobList.Add_SelectedIndexChanged({
    if ($script:queueRefresh) { return }
    Sync-QueueEditors
    Show-QueueDetail
  })
  $queue.Controls.Add($script:queueJobList)

  $script:queueDetail = New-Object System.Windows.Forms.Panel
  $script:queueDetail.Location = New-Object System.Drawing.Point(356, 366)
  $script:queueDetail.Size = New-Object System.Drawing.Size(390, 150)
  $script:queueDetail.AutoScroll = $true
  $script:queueDetail.BorderStyle = 'FixedSingle'
  $queue.Controls.Add($script:queueDetail)

  $script:queueConfirm = New-Object System.Windows.Forms.CheckBox
  $script:queueConfirm.Location = New-Object System.Drawing.Point(16, 526)
  $script:queueConfirm.Size = New-Object System.Drawing.Size(730, 36)
  $script:queueConfirm.Text = '我確認這次佇列可以寫入模型。沒勾選時，所有寫入開關維持 False。'
  $script:queueConfirm.Add_CheckedChanged({
    if ($script:queueConfirmGuard) { return }
    if ($script:queueConfirm.Checked) {
      $answer = Show-QueueNotice "確認之後，才可以把個別工作的寫入開關改成 True。`r`n啟動器仍只會以手動模式開啟圖形，執行按鈕要你在 Dynamo 裡按。`r`n確定要允許寫入？" '確認寫入' ([System.Windows.Forms.MessageBoxButtons]::YesNo) ([System.Windows.Forms.MessageBoxIcon]::Warning)
      if ($answer -ne [System.Windows.Forms.DialogResult]::Yes) {
        $script:queueConfirmGuard = $true
        $script:queueConfirm.Checked = $false
        $script:queueConfirmGuard = $false
        return
      }
    } else {
      foreach ($job in @($script:queueJobs)) {
        if ($job.dryRunInput) {
          $job.inputs[$job.dryRunInput] = $false
          $job.run = $false
        }
      }
      if ($null -ne $script:queueEditors) {
        foreach ($key in @($script:queueEditors.Keys)) {
          $control = $script:queueEditors[$key]
          if ($control -is [System.Windows.Forms.CheckBox]) { $control.Checked = $false }
        }
      }
    }
    Update-QueueJobList -SelectIndex $script:queueJobList.SelectedIndex
  })
  $queue.Controls.Add($script:queueConfirm)

  $script:queueStatus = New-Object System.Windows.Forms.Label
  $script:queueStatus.Location = New-Object System.Drawing.Point(16, 566)
  $script:queueStatus.Size = New-Object System.Drawing.Size(730, 36)
  $script:queueStatus.Text = '預設試跑。開啟下一步之前，Revit 2025 必須是關閉的。'
  $queue.Controls.Add($script:queueStatus)

  $script:queueOpen = New-Object System.Windows.Forms.Button
  $script:queueOpen.Location = New-Object System.Drawing.Point(16, 610)
  $script:queueOpen.Size = New-Object System.Drawing.Size(140, 32)
  $script:queueOpen.Text = '開啟下一步'
  $script:queueOpen.Add_Click({
    try { Start-QueueNextJob } catch {
      Show-QueueNotice $_.Exception.Message '批次佇列' ([System.Windows.Forms.MessageBoxButtons]::OK) ([System.Windows.Forms.MessageBoxIcon]::Warning) | Out-Null
    }
  })
  $queue.Controls.Add($script:queueOpen)

  $record = New-Object System.Windows.Forms.Button
  $record.Location = New-Object System.Drawing.Point(168, 610)
  $record.Size = New-Object System.Drawing.Size(140, 32)
  $record.Text = '記錄結果'
  $record.Add_Click({
    try { Save-QueueResult } catch {
      Show-QueueNotice $_.Exception.Message '記錄結果' ([System.Windows.Forms.MessageBoxButtons]::OK) ([System.Windows.Forms.MessageBoxIcon]::Warning) | Out-Null
    }
  })
  $queue.Controls.Add($record)

  $report = New-Object System.Windows.Forms.Button
  $report.Location = New-Object System.Drawing.Point(320, 610)
  $report.Size = New-Object System.Drawing.Size(140, 32)
  $report.Text = '開啟報告'
  $report.Add_Click({
    if ([string]::IsNullOrWhiteSpace($script:queueSessionDir)) {
      Show-QueueNotice '還沒有這次工作階段的報告。先按開啟下一步。' | Out-Null
      return
    }
    $html = Join-Path $script:queueSessionDir 'report.html'
    if (-not (Test-Path -LiteralPath $html)) {
      Show-QueueNotice '還沒有這次工作階段的報告。先按開啟下一步。' | Out-Null
      return
    }
    Start-Process -FilePath $html
  })
  $queue.Controls.Add($report)

  $clear = New-Object System.Windows.Forms.Button
  $clear.Location = New-Object System.Drawing.Point(472, 610)
  $clear.Size = New-Object System.Drawing.Size(140, 32)
  $clear.Text = '清除佇列'
  $clear.Add_Click({
    if (-not (Test-QueueEditable)) {
      Show-QueueNotice '這個工作階段已經開始。已寫下的紀錄留在原來的資料夾。' | Out-Null
      return
    }
    $script:queueJobs = New-Object System.Collections.ArrayList
    $script:queueSession = $null
    $script:queueSessionDir = $null
    $script:queueStatus.Text = '佇列已清除。'
    Update-QueueJobList
  })
  $queue.Controls.Add($clear)

  $tabs.Add_SelectedIndexChanged({
    if ($tabs.SelectedIndex -eq 0) { $form.AcceptButton = $launch }
    else { $form.AcceptButton = $null }
  })

  [void]$form.ShowDialog()
}

if ($MyInvocation.InvocationName -ne '.') {
  Show-DynamoToolboxForm
}
