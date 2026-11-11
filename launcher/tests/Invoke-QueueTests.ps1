#Requires -Version 5.1
<#
.SYNOPSIS
  Config, queue order, and run-log tests. No Revit process is started.

.DESCRIPTION
  Run with Windows PowerShell 5.1 or PowerShell 7:
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\launcher\tests\Invoke-QueueTests.ps1

  These tests do not open a .rvt, do not write a journal, and do not check the
  WinForms queue page on a real desktop. That still needs Revit 2025.
#>
$ErrorActionPreference = 'Stop'
$script:QueueTestsDirectory = $PSScriptRoot

function Invoke-DynamoQueueTestSuite {
  $testsDir = $script:QueueTestsDirectory
  if ([string]::IsNullOrWhiteSpace($testsDir)) {
    $testsDir = Split-Path -Parent $PSCommandPath
  }
  $launcher = Split-Path -Parent $testsDir
  $repo = Split-Path -Parent $launcher
  . (Join-Path $launcher 'queue\DynamoQueue.ps1')

  $script:failures = New-Object System.Collections.Generic.List[string]
  $script:passed = 0

  function Test-Case {
    param([string]$Name, [scriptblock]$Body)
    try {
      & $Body
      $script:passed++
      Write-Host "PASS $Name"
    } catch {
      $script:failures.Add("$Name :: $($_.Exception.Message)")
      Write-Host "FAIL $Name :: $($_.Exception.Message)"
    }
  }

  function Assert-Equal {
    param($Actual, $Expected, [string]$Message)
    if ([string]$Actual -ne [string]$Expected) {
      throw "$Message expected [$Expected] actual [$Actual]"
    }
  }

  function Assert-True {
    param($Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
  }

  function Assert-Throws {
    param([scriptblock]$Body, [string]$Like)
    $threw = $false
    $message = ''
    try { & $Body } catch { $threw = $true; $message = $_.Exception.Message }
    if (-not $threw) { throw "expected an error containing [$Like]" }
    if ($message -notlike "*$Like*") { throw "message [$message] does not contain [$Like]" }
  }

  $catalog = Get-DynamoToolboxCatalog
  $examplePath = Join-Path $launcher 'examples\task-config.example.json'
  $example = Read-DynamoTaskConfig -Path $examplePath
  $plan = Resolve-DynamoTaskQueue -Catalog $catalog -Config $example

  Test-Case 'shipped tools keep their ids, order, and dyn paths' {
    $expected = @(
      'copy-view-templates|批次複製視圖樣板/BatchCopyViewTemplates.dyn',
      'fill-scada-params|批次填參數/BatchFillScadaParams.dyn',
      'assign-worksets|批次工作集/BatchWorksets.dyn',
      'param-tools|批次參數工具/BatchParamTools.dyn',
      'excel-sync|Excel參數同步/ExcelRevitSync.dyn',
      'batch-scada-setup|批次SCADA設定/BatchScadaSetup.dyn'
    )
    Assert-Equal $catalog.Length 6 'tool count'
    for ($i = 0; $i -lt $expected.Count; $i++) {
      $parts = $expected[$i].Split('|')
      Assert-Equal $catalog[$i].Id $parts[0] 'id'
      Assert-Equal $catalog[$i].Dyn $parts[1] 'dyn'
      Assert-True $catalog[$i].SupportsDryRun "dry-run flag for $($parts[0])"
      Assert-Equal $catalog[$i].DryRunInput 'run' 'dry-run input'
    }
  }

  Test-Case 'example queue stays in file order and defaults to dry run' {
    $ids = @($plan.jobs | ForEach-Object { $_.toolId })
    Assert-Equal ($ids -join ',') 'batch-scada-setup,fill-scada-params,copy-view-templates,assign-worksets,param-tools,excel-sync' 'order'
    foreach ($job in $plan.jobs) {
      Assert-True (-not $job.run) "run flag for $($job.toolId)"
      Assert-True (-not $job.graphExecutedByLauncher) 'launcher execute flag'
      Assert-True $job.manualMode 'manual mode'
    }
    Assert-True (-not $plan.confirmWrite) 'confirmWrite'
    Assert-Equal $plan.jobs[2].inputs.templateNames[0] 'SampleTemplate' 'template name'
    Assert-Equal $plan.jobs[2].inputs.templateNames.Length 1 'template count'
    Assert-Equal $plan.jobs[3].inputs.rules.Length 0 'empty rules'
  }

  Test-Case 'omitted run flag becomes false' {
    $json = '{"version":1,"hostProject":"C:/Models/sample-host.rvt","confirmWrite":false,"jobs":[{"toolId":"fill-scada-params","inputs":{"directory":"C:/Models/sample-batch"}}]}'
    $resolved = Resolve-DynamoTaskQueue -Catalog $catalog -Config $json
    Assert-Equal $resolved.jobs[0].inputs.value 'SCADA' 'default value'
    Assert-True (-not $resolved.jobs[0].run) 'default run'
    Assert-True (-not $resolved.jobs[0].inputs.run) 'default run input'
  }

  Test-Case 'write without confirmation is rejected' {
    $json = '{"version":1,"hostProject":"C:/Models/sample-host.rvt","confirmWrite":false,"jobs":[{"toolId":"fill-scada-params","inputs":{"directory":"C:/Models/sample-batch","run":true}}]}'
    Assert-Throws { Resolve-DynamoTaskQueue -Catalog $catalog -Config $json } 'confirmWrite'
  }

  Test-Case 'confirmed write stays true' {
    $json = '{"version":1,"hostProject":"C:/Models/sample-host.rvt","confirmWrite":true,"jobs":[{"toolId":"fill-scada-params","inputs":{"directory":"C:/Models/sample-batch","run":true}}]}'
    $resolved = Resolve-DynamoTaskQueue -Catalog $catalog -Config $json
    Assert-True $resolved.jobs[0].run 'confirmed run'
    Assert-True $resolved.confirmWrite 'confirm flag'
  }

  Test-Case 'string false is not a boolean' {
    $json = '{"version":1,"hostProject":"C:/Models/sample-host.rvt","jobs":[{"toolId":"fill-scada-params","inputs":{"directory":"C:/Models/sample-batch","run":"false"}}]}'
    Assert-Throws { Resolve-DynamoTaskQueue -Catalog $catalog -Config $json } '布林'
  }

  Test-Case 'unknown tool, unknown input, missing input, bad host, and bad version' {
    $unknownTool = '{"version":1,"hostProject":"C:/Models/sample-host.rvt","jobs":[{"toolId":"missing-tool","inputs":{}}]}'
    $unknownInput = '{"version":1,"hostProject":"C:/Models/sample-host.rvt","jobs":[{"toolId":"fill-scada-params","inputs":{"directory":"C:/Models/sample-batch","extra":"x"}}]}'
    $missingInput = '{"version":1,"hostProject":"C:/Models/sample-host.rvt","jobs":[{"toolId":"fill-scada-params","inputs":{}}]}'
    $templateHost = '{"version":1,"hostProject":"C:/Models/sample.rte","jobs":[{"toolId":"fill-scada-params"}]}'
    $badVersion = '{"version":2,"hostProject":"C:/Models/sample-host.rvt","jobs":[{"toolId":"fill-scada-params"}]}'
    $badConfirm = '{"version":1,"hostProject":"C:/Models/sample-host.rvt","confirmWrite":"true","jobs":[{"toolId":"fill-scada-params","inputs":{"directory":"C:/Models/x"}}]}'
    $emptyJobs = '{"version":1,"hostProject":"C:/Models/sample-host.rvt","jobs":[]}'
    $broken = '{'
    Assert-Throws { Resolve-DynamoTaskQueue -Catalog $catalog -Config $unknownTool } '未知的工具'
    Assert-Throws { Resolve-DynamoTaskQueue -Catalog $catalog -Config $unknownInput } '未知的輸入'
    Assert-Throws { Resolve-DynamoTaskQueue -Catalog $catalog -Config $missingInput } '缺少必填輸入'
    Assert-Throws { Read-DynamoTaskConfig -Json $templateHost } '.rvt'
    Assert-Throws { Read-DynamoTaskConfig -Json $badVersion } '版本'
    Assert-Throws { Read-DynamoTaskConfig -Json $badConfirm } 'confirmWrite'
    Assert-Throws { Read-DynamoTaskConfig -Json $emptyJobs } '至少要有一個工作'
    Assert-Throws { Read-DynamoTaskConfig -Json $broken } '不是合法的 JSON'
  }

  Test-Case 'duplicate tools keep the listed order' {
    $json = '{"version":1,"hostProject":"C:/Models/sample-host.rvt","jobs":[{"toolId":"fill-scada-params","inputs":{"directory":"C:/Models/a"}},{"toolId":"copy-view-templates","inputs":{"directory":"C:/Models/a"}},{"toolId":"fill-scada-params","inputs":{"directory":"C:/Models/b"}}]}'
    $resolved = Resolve-DynamoTaskQueue -Catalog $catalog -Config $json
    $ids = @($resolved.jobs | ForEach-Object { $_.toolId })
    Assert-Equal ($ids -join ',') 'fill-scada-params,copy-view-templates,fill-scada-params' 'duplicate order'
  }

  Test-Case 'checkbox selection follows catalog order and drops duplicates' {
    $order = Get-DynamoCatalogToolOrder -Catalog $catalog -ToolIds @('excel-sync', 'copy-view-templates', 'excel-sync')
    Assert-Equal $order.Length 2 'selection count'
    Assert-Equal $order[0] 'copy-view-templates' 'first'
    Assert-Equal $order[1] 'excel-sync' 'second'
    Assert-Throws { Get-DynamoCatalogToolOrder -Catalog $catalog -ToolIds @('not-a-tool') } '未知的工具'
  }

  Test-Case 'move and remove reindex the queue' {
    $entries = @(
      [ordered]@{ index = 1; toolId = 'a' },
      [ordered]@{ index = 2; toolId = 'b' },
      [ordered]@{ index = 3; toolId = 'c' }
    )
    $moved = Move-DynamoQueueEntries -Entries $entries -Index 3 -Offset -1
    Assert-Equal (($moved | ForEach-Object { $_.toolId }) -join ',') 'a,c,b' 'moved order'
    Assert-Equal $moved[1].index 2 'reindex'
    $removed = Remove-DynamoQueueEntry -Entries $moved -Index 2
    Assert-Equal (($removed | ForEach-Object { $_.toolId }) -join ',') 'a,b' 'removed'
    Assert-Equal $removed.Length 2 'remaining'
    Assert-Throws { Move-DynamoQueueEntries -Entries $entries -Index 1 -Offset -1 } '不能把工作移出佇列'
  }

  Test-Case 'legacy tools.json without contract fields still loads' {
    $legacy = Read-DynamoToolboxCatalog -Json '{"tools":[{"id":"legacy-tool","name":"Legacy","dyn":"legacy/Legacy.dyn"}]}'
    Assert-Equal $legacy.Length 1 'legacy count'
    Assert-True (-not $legacy[0].SupportsDryRun) 'legacy dry-run'
    $legacyJob = '{"version":1,"hostProject":"C:/Models/sample-host.rvt","jobs":[{"toolId":"legacy-tool","inputs":{}}]}'
    $legacyRun = '{"version":1,"hostProject":"C:/Models/sample-host.rvt","jobs":[{"toolId":"legacy-tool","inputs":{"run":false}}]}'
    $resolved = Resolve-DynamoTaskQueue -Catalog $legacy -Config $legacyJob
    Assert-True (-not $resolved.jobs[0].run) 'legacy run'
    Assert-Throws { Resolve-DynamoTaskQueue -Catalog $legacy -Config $legacyRun } '未知的輸入'
  }

  Test-Case 'future inspector and DWG importer follow the contract' {
    $future = Read-DynamoToolboxCatalog -Json @'
{"tools":[
  {"id":"model-inspector","name":"模型檢查","dyn":"模型檢查/ModelInspector.dyn","supportsDryRun":false,"inputs":[{"name":"scope","type":"string","label":"檢查範圍","required":false,"default":"all"}]},
  {"id":"dwg-import","name":"DWG 匯入 Revit","dyn":"DWG匯入/DwgImport.dyn","supportsDryRun":true,"dryRunInput":"run","inputs":[
    {"name":"dwg","type":"file","label":"DWG 檔","required":true},
    {"name":"copies","type":"integer","label":"份數","required":false,"default":1},
    {"name":"scale","type":"number","label":"比例","required":false,"default":1.5},
    {"name":"run","type":"boolean","label":"寫入","required":false,"default":false,"writesModel":true}
  ]}
]}
'@
    $inspectorJob = '{"version":1,"hostProject":"C:/Models/sample-host.rvt","jobs":[{"toolId":"model-inspector","inputs":{}}]}'
    $dwgDry = '{"version":1,"hostProject":"C:/Models/sample-host.rvt","jobs":[{"toolId":"dwg-import","inputs":{"dwg":"C:/Models/sample.dwg"}}]}'
    $dwgWrite = '{"version":1,"hostProject":"C:/Models/sample-host.rvt","jobs":[{"toolId":"dwg-import","inputs":{"dwg":"C:/Models/sample.dwg","run":true}}]}'
    $dwgFraction = '{"version":1,"hostProject":"C:/Models/sample-host.rvt","confirmWrite":true,"jobs":[{"toolId":"dwg-import","inputs":{"dwg":"C:/Models/sample.dwg","copies":1.5}}]}'
    $dwgConfirmed = '{"version":1,"hostProject":"C:/Models/sample-host.rvt","confirmWrite":true,"jobs":[{"toolId":"dwg-import","inputs":{"dwg":"C:/Models/sample.dwg","run":true}}]}'
    $readOnly = Resolve-DynamoTaskQueue -Catalog $future -Config $inspectorJob
    Assert-Equal $readOnly.jobs[0].inputs.scope 'all' 'inspector default'
    Assert-True (-not $readOnly.jobs[0].run) 'inspector does not write'
    $dry = Resolve-DynamoTaskQueue -Catalog $future -Config $dwgDry
    Assert-True (-not $dry.jobs[0].run) 'dwg dry run'
    Assert-Equal ([int64]$dry.jobs[0].inputs.copies) 1 'integer default'
    if ([Math]::Abs(([double]$dry.jobs[0].inputs.scale) - 1.5) -gt 0.0001) {
      throw "scale actual [$($dry.jobs[0].inputs.scale)]"
    }
    Assert-Throws { Resolve-DynamoTaskQueue -Catalog $future -Config $dwgWrite } 'confirmWrite'
    Assert-Throws { Resolve-DynamoTaskQueue -Catalog $future -Config $dwgFraction } '整數'
    $write = Resolve-DynamoTaskQueue -Catalog $future -Config $dwgConfirmed
    Assert-True $write.jobs[0].run 'dwg write'
  }

  Test-Case 'catalog rejects a dry-run default of true and an absolute dyn path' {
    $badDefault = '{"tools":[{"id":"bad-tool","name":"Bad","dyn":"bad/Bad.dyn","supportsDryRun":true,"dryRunInput":"run","inputs":[{"name":"run","type":"boolean","label":"寫入","required":false,"default":true,"writesModel":true}]}]}'
    $absoluteDyn = '{"tools":[{"id":"bad-tool","name":"Bad","dyn":"C:/Temp/Bad.dyn"}]}'
    Assert-Throws { Read-DynamoToolboxCatalog -Json $badDefault } '預設必須是 false'
    Assert-Throws { Read-DynamoToolboxCatalog -Json $absoluteDyn } '相對路徑'
  }

  $session = New-DynamoQueueSession -Plan $plan -SessionId 'sample-batch_20261111_060000' -CreatedAt '2026-11-11T06:00:00'
  $work = Join-Path ([System.IO.Path]::GetTempPath()) ('dynamo-queue-' + [guid]::NewGuid().ToString('N'))

  Test-Case 'run log, csv, markdown, and html round-trip' {
    $chinese = Resolve-DynamoTaskQueue -Catalog $catalog -Config '{"version":1,"sessionName":"範例批次","hostProject":"C:/模型/範例宿主.rvt","confirmWrite":false,"jobs":[{"toolId":"fill-scada-params","inputs":{"directory":"C:/模型/範例批次","value":"SAMPLE","run":false}}]}'
    $logged = New-DynamoQueueSession -Plan $chinese -SessionId 'batch_20261111_060000' -CreatedAt '2026-11-11T06:00:00'
    Assert-Equal $logged.sessionId 'batch_20261111_060000' 'slug'
    $paths = Export-DynamoQueueSession -Session $logged -OutputDirectory $work -UpdatedAt '2026-11-11T06:00:01'
    $jsonBytes = [System.IO.File]::ReadAllBytes($paths.Json)
    Assert-Equal $jsonBytes[0] 123 'json has no BOM'
    $csvBytes = [System.IO.File]::ReadAllBytes($paths.Csv)
    Assert-Equal $csvBytes[0] 239 'csv bom'
    Assert-Equal $csvBytes[1] 187 'csv bom'
    Assert-Equal $csvBytes[2] 191 'csv bom'
    $imported = Import-DynamoQueueSession -Path $paths.Json
    Assert-Equal $imported.jobs.Length 1 'one job'
    Assert-Equal $imported.jobs[0].status 'planned' 'planned'
    Assert-Equal $imported.jobs[0].inputFiles.Length 2 'input files'
    Assert-Equal $imported.hostProject 'C:/模型/範例宿主.rvt' 'chinese host'
    Assert-True (-not $imported.jobs[0].graphExecutedByLauncher) 'not executed'
    $markdown = [System.IO.File]::ReadAllText($paths.Markdown)
    $html = [System.IO.File]::ReadAllText($paths.Html)
    Assert-True ($markdown.Contains('批次填寫 SCADA 參數')) 'markdown tool'
    Assert-True ($html.Contains('批次填寫 SCADA 參數')) 'html tool'
    Assert-True ($markdown.Contains('範例宿主.rvt')) 'markdown path'

    $dispatch = Get-DynamoQueueDispatchPlan -Session $logged
    Assert-True (-not $dispatch.ExecuteGraph) 'dispatch does not execute'
    Assert-True $dispatch.ManualMode 'dispatch manual'
    Assert-Equal ($dispatch.ArgumentList -join ' ') '-ToolId fill-scada-params -Project C:/模型/範例宿主.rvt -Launch' 'journal arguments'
    Assert-True ((Get-Command Get-DynamoQueueDispatchPlan).Parameters.Keys -notcontains 'Execute') 'no execute parameter'

    Set-DynamoQueueJobOpened -Session $logged -Index 1 -StartedAt '2026-11-11T06:01:00' | Out-Null
    Assert-Throws { Get-DynamoQueueDispatchPlan -Session $logged } '請先記錄'
    Assert-Throws {
      Set-DynamoQueueJobResult -Session $logged -Index 1 -Status 'written' -EndedAt '2026-11-11T06:02:00'
    } '不能記錄成已寫入'
    Set-DynamoQueueJobResult -Session $logged -Index 1 -Status 'dry-run' -Counts @{ files = 2; changed = 0 } -Errors @('bad, <bad>') -EndedAt '2026-11-11T06:02:00' | Out-Null
    Assert-Equal $logged.jobs[0].counts.files 2 'count files'
    Assert-Equal $logged.jobs[0].counts.changed 0 'count changed'
    Assert-True ($null -eq $logged.jobs[0].counts.skipped) 'count skipped stays empty'
    $paths = Export-DynamoQueueSession -Session $logged -OutputDirectory $work -UpdatedAt '2026-11-11T06:02:01'
    $csv = [System.IO.File]::ReadAllText($paths.Csv)
    $lines = @($csv.TrimEnd().Split("`n") | Where-Object { $_.Trim() -ne '' })
    Assert-Equal $lines.Count 2 'csv has one data row'
    Assert-True ($csv.Contains('"bad, <bad>"')) 'csv quotes comma'
    $html = [System.IO.File]::ReadAllText($paths.Html)
    Assert-True ($html.Contains('&lt;bad&gt;')) 'html escapes markup'
    Assert-True (-not $html.Contains('<bad>')) 'html has no raw tag'
    $card = Format-DynamoJobCard -Session $logged -Job $logged.jobs[0] -Catalog $catalog
    Assert-True ($card.Contains('手動模式')) 'card manual'
    Assert-True ($card.Contains('自己按執行')) 'card run by hand'
    Assert-True ($card.Contains('Run 維持 False')) 'card stays false'
    Assert-True ($card.Contains('C:/模型/範例批次')) 'card directory'
  }

  Test-Case 'a second export replaces the row instead of appending' {
    $again = Export-DynamoQueueSession -Session $session -OutputDirectory (Join-Path $work 'second') -UpdatedAt '2026-11-11T07:00:00'
    $csv = [System.IO.File]::ReadAllText($again.Csv)
    $lines = @($csv.TrimEnd().Split("`n") | Where-Object { $_.Trim() -ne '' })
    Assert-Equal $lines.Count ($session.jobs.Length + 1) 'header plus jobs'
  }

  Test-Case 'written is stored only after confirmation and an open job' {
    $writePlan = Resolve-DynamoTaskQueue -Catalog $catalog -Config '{"version":1,"hostProject":"C:/Models/sample-host.rvt","confirmWrite":true,"jobs":[{"toolId":"assign-worksets","inputs":{"directory":"C:/Models/sample-batch","run":false}},{"toolId":"fill-scada-params","inputs":{"directory":"C:/Models/sample-batch","run":true}}]}'
    $writeSession = New-DynamoQueueSession -Plan $writePlan -SessionId 'sample-batch_20261111_070000' -CreatedAt '2026-11-11T07:00:00'
    Assert-Throws { Set-DynamoQueueJobResult -Session $writeSession -Index 2 -Status 'dry-run' } '請先開啟'
    Set-DynamoQueueJobOpened -Session $writeSession -Index 1 -StartedAt '2026-11-11T07:01:00' | Out-Null
    Assert-Throws { Set-DynamoQueueJobOpened -Session $writeSession -Index 2 -StartedAt '2026-11-11T07:02:00' } '下一個'
    Set-DynamoQueueJobResult -Session $writeSession -Index 1 -Status 'dry-run' -EndedAt '2026-11-11T07:03:00' | Out-Null
    Set-DynamoQueueJobOpened -Session $writeSession -Index 2 -StartedAt '2026-11-11T07:04:00' | Out-Null
    Assert-Throws {
      Set-DynamoQueueJobResult -Session $writeSession -Index 2 -Status 'written' -Counts @{ other = 1 } -EndedAt '2026-11-11T07:04:30'
    } '未知的計數'
    Assert-Throws {
      Set-DynamoQueueJobResult -Session $writeSession -Index 2 -Status 'written' -Counts @{ files = -1 } -EndedAt '2026-11-11T07:05:00'
    } '0 以上'
    Set-DynamoQueueJobResult -Session $writeSession -Index 2 -Status 'written' -Counts @{ files = 1; changed = 4; skipped = 0; failed = 0 } -Errors @() -EndedAt '2026-11-11T07:05:00' | Out-Null
    Assert-Equal $writeSession.jobs[1].status 'written' 'written status'
    $cursor = Get-DynamoQueueCursor -Session $writeSession
    Assert-True ($null -eq $cursor.Next) 'queue finished'
    Assert-Throws {
      Set-DynamoQueueJobResult -Session $writeSession -Index 2 -Status 'written' -Counts @{ other = 1 }
    } '請先開啟'
  }

  Test-Case 'tampered execute flag is refused' {
    $logged = New-DynamoQueueSession -Plan (Resolve-DynamoTaskQueue -Catalog $catalog -Config $example) -SessionId 'sample-batch_20261111_080000' -CreatedAt '2026-11-11T08:00:00'
    $logged.jobs[0].graphExecutedByLauncher = $true
    Assert-Throws { Export-DynamoQueueSession -Session $logged -OutputDirectory (Join-Path $work 'bad') } '不會執行'
    $badPath = Join-Path $work 'bad-log.json'
    [System.IO.File]::WriteAllText($badPath, '{"version":1,"sessionId":"x","sessionName":"x","hostProject":"C:/Models/sample-host.rvt","confirmWrite":false,"createdAt":"2026-11-11T08:00:00","updatedAt":"2026-11-11T08:00:00","jobs":[{"index":1,"toolId":"fill-scada-params","toolName":"t","dyn":"a.dyn","status":"planned","run":false,"inputs":{},"inputFiles":[],"startedAt":null,"endedAt":null,"counts":{"files":null,"changed":null,"skipped":null,"failed":null},"errors":[],"manualMode":true,"graphExecutedByLauncher":true,"note":"x"}]}', (New-Object System.Text.UTF8Encoding $false))
    Assert-Throws { Import-DynamoQueueSession -Path $badPath } '不會執行'
  }

  Test-Case 'journal writer is still manual, BOM-free, and checks cp950' {
    $journal = [System.IO.File]::ReadAllText((Join-Path $launcher 'poc\New-DynamoJournal.ps1'))
    Assert-True ($journal.Contains('dynPathExecute" , "False"')) 'execute false'
    Assert-True ($journal.Contains('dynForceManualRun" , "True"')) 'force manual'
    Assert-True ($journal.Contains('dynAutomation" , "False"')) 'automation false'
    Assert-True ($journal.Contains('dynShowUI" , "True"')) 'show ui'
    Assert-True (-not $journal.Contains('dynPathExecute" , "True"')) 'execute is not true'
    Assert-True ($journal.Contains('Assert-AnsiJournalRoundTrip')) 'ansi round trip'
    Assert-True ($journal.Contains('WriteAllBytes')) 'no-bom writer'
    Assert-True ($journal.Contains('cp950')) 'cp950'
    Assert-True ($journal.Contains('Revit 2025 is already running')) 'close revit message'
  }

  Test-Case 'queue library does not start Revit or execute a graph' {
    $library = [System.IO.File]::ReadAllText((Join-Path $launcher 'queue\DynamoQueue.ps1'))
    Assert-True (-not $library.Contains('Start-Process')) 'no Start-Process'
    Assert-True (-not $library.Contains('dynPathExecute')) 'no journal execute flag'
    $ui = [System.IO.File]::ReadAllText((Join-Path $launcher 'Show-DynamoToolbox.ps1'))
    Assert-True ($ui.Contains('拒絕開啟：佇列只能以手動模式載入圖形。')) 'ui guard'
    Assert-True ($ui.Contains('-ToolId $dispatch.ToolId -Project $dispatch.Project -Launch')) 'queue uses the journal launcher'
    Assert-True ($ui.Contains('-ToolId $script:catalog[$index].Id -Project $project -Launch')) 'single tool still launches'
  }

  Test-Case 'launcher scripts parse' {
    foreach ($relative in @(
      'queue\DynamoQueue.ps1',
      'Show-DynamoToolbox.ps1',
      'Install-DynamoToolbox.ps1',
      'poc\New-DynamoJournal.ps1'
    )) {
      $path = Join-Path $launcher $relative
      $tokens = $null
      $parseErrors = $null
      [void][System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$parseErrors)
      if ($parseErrors -and @($parseErrors).Count -gt 0) {
        throw "$relative :: $($parseErrors[0].ToString())"
      }
    }
  }

  Test-Case 'samples do not contain private paths' {
    $roots = @(
      (Join-Path $launcher 'examples'),
      (Join-Path $launcher 'schemas'),
      (Join-Path $launcher 'docs'),
      (Join-Path $launcher 'README.md'),
      (Join-Path $launcher 'tools.json')
    )
    $forbidden = @('C:\Users', 'C:/Users', 'VT_Test', 'Downloads', 'G:\', 'G:/', 'D:\SCADA')
    foreach ($rootPath in $roots) {
      $files = @()
      if (Test-Path -LiteralPath $rootPath -PathType Leaf) { $files = @($rootPath) }
      else { $files = @(Get-ChildItem -LiteralPath $rootPath -File -Recurse | ForEach-Object { $_.FullName }) }
      foreach ($file in $files) {
        $text = [System.IO.File]::ReadAllText($file)
        foreach ($needle in $forbidden) {
          if ($text.Contains($needle)) { throw "$file contains $needle" }
        }
      }
    }
  }

  Test-Case 'job card for a confirmed write tells the operator to set Run True' {
    $writePlan = Resolve-DynamoTaskQueue -Catalog $catalog -Config '{"version":1,"hostProject":"C:/Models/sample-host.rvt","confirmWrite":true,"sessionName":"sample-batch","jobs":[{"toolId":"excel-sync","inputs":{"mode":"import","workbook":"C:/Models/sample-parameters.xlsx","run":true}}]}'
    $writeSession = New-DynamoQueueSession -Plan $writePlan -SessionId 'sample-batch_20261111_090000' -CreatedAt '2026-11-11T09:00:00'
    $card = Format-DynamoJobCard -Session $writeSession -Job $writeSession.jobs[0] -Catalog $catalog
    Assert-True ($card.Contains('Run 改成 True')) 'write card'
    Assert-True ($writeSession.jobs[0].inputFiles -join '|' ).Contains('sample-parameters.xlsx') 'workbook is an input file'
    Assert-Equal $writeSession.jobs[0].inputFiles[0] 'C:/Models/sample-host.rvt' 'host is first'
  }

  if ($script:failures.Count -gt 0) {
    Write-Host ($script:failures -join [Environment]::NewLine)
    throw ("FAILED " + $script:failures.Count + " test(s)")
  }
  Write-Host ("OK " + $script:passed + " tests")
}

if ($MyInvocation.InvocationName -ne '.') {
  Invoke-DynamoQueueTestSuite
}
