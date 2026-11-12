#Requires -Version 5.1
<#
.SYNOPSIS
  Config, queue order, and run-log tests. No Revit process is started.

.DESCRIPTION
  The script file is ASCII so Windows PowerShell 5.1 can parse it on any
  ANSI code page. Fixture JSON is UTF-8. Traditional Chinese expected text is
  decoded from hex at runtime.
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
  $fixtures = Join-Path $testsDir 'fixtures'
  . (Join-Path $launcher 'queue\DynamoQueue.ps1')

  $script:failures = New-Object System.Collections.Generic.List[string]
  $script:passed = 0

  function U([string]$Hex) {
    $sb = New-Object System.Text.StringBuilder
    for ($i = 0; $i -lt $Hex.Length; $i += 4) {
      [void]$sb.Append([char][Convert]::ToInt32($Hex.Substring($i, 4), 16))
    }
    return $sb.ToString()
  }

  function Read-Fixture([string]$Name) {
    $path = Join-Path $fixtures $Name
    $utf8 = New-Object System.Text.UTF8Encoding $false
    return [System.IO.File]::ReadAllText($path, $utf8)
  }

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
    if ($message.IndexOf($Like) -lt 0) { throw "message [$message] does not contain [$Like]" }
  }

  $unknownTool = U '672a77e576845de55177'
  $booleanWord = U '5e036797'
  $needJob = U '81f35c11898167094e00500b5de54f5c'
  $badJsonWord = U '4e0d662f54086cd57684'
  $defaultFalse = U '98108a2d5fc59808662f'
  $integerWord = U '65746578'
  $relativePath = U '76f85c0d8def5f91'
  $recordFirst = U '8acb51488a189304'
  $cannotWrite = U '4e0d80fd8a18930462105df25beb5165'
  $unknownCount = U '672a77e576848a086578'
  $openFirst = U '8acb5148958b555f'
  $nextWord = U '4e0b4e00500b'
  $willNotRun = U '4e0d670357f7884c'
  $manualMode = U '624b52d56a215f0f'
  $pressRun = U '81ea5df1630957f7884c'
  $fillName = U '62796b21586b5beb002000530043004100440041002053c36578'
  $sampleBatch = U '7bc44f8b62796b21'
  $modelWord = U '6a21578b'
  $sampleHost = U '7bc44f8b5bbf4e3b'
  $cannotMove = U '4e0d80fd628a5de54f5c79fb51fa4f475217'
  $nonNegative = '0 ' + (U '4ee54e0a')

  $catalog = Get-DynamoToolboxCatalog
  $examplePath = Join-Path $launcher 'examples\task-config.example.json'
  $example = Read-DynamoTaskConfig -Path $examplePath
  $plan = Resolve-DynamoTaskQueue -Catalog $catalog -Config $example

  Test-Case 'shipped tools keep their ids, order, and dyn paths' {
    $expected = @((Read-Fixture 'expected-dyn.txt') -split '\r?\n' | Where-Object { $_.Trim() -ne '' })
    Assert-Equal $catalog.Length 6 'tool count'
    Assert-Equal $catalog[1].Name $fillName 'fill tool name'
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
    $resolved = Resolve-DynamoTaskQueue -Catalog $catalog -Config (Read-Fixture 'omitted-run.json')
    Assert-Equal $resolved.jobs[0].inputs.value 'SCADA' 'default value'
    Assert-True (-not $resolved.jobs[0].run) 'default run'
    Assert-True (-not $resolved.jobs[0].inputs.run) 'default run input'
  }

  Test-Case 'write without confirmation is rejected' {
    $json = Read-Fixture 'write-unconfirmed.json'
    Assert-Throws { Resolve-DynamoTaskQueue -Catalog $catalog -Config $json } 'confirmWrite'
  }

  Test-Case 'confirmed write stays true' {
    $resolved = Resolve-DynamoTaskQueue -Catalog $catalog -Config (Read-Fixture 'write-confirmed.json')
    Assert-True $resolved.jobs[0].run 'confirmed run'
    Assert-True $resolved.confirmWrite 'confirm flag'
  }

  Test-Case 'string false is not a boolean' {
    $json = Read-Fixture 'string-false.json'
    Assert-Throws { Resolve-DynamoTaskQueue -Catalog $catalog -Config $json } $booleanWord
  }

  Test-Case 'unknown tool, unknown input, missing input, bad host, and bad version' {
    $unknownToolJson = Read-Fixture 'unknown-tool.json'
    $unknownInput = Read-Fixture 'unknown-input.json'
    $missingInput = Read-Fixture 'missing-input.json'
    $templateHost = Read-Fixture 'rte-host.json'
    $badVersion = Read-Fixture 'bad-version.json'
    $badConfirm = Read-Fixture 'bad-confirm.json'
    $emptyJobs = Read-Fixture 'empty-jobs.json'
    $broken = Read-Fixture 'broken.json'
    Assert-Throws { Resolve-DynamoTaskQueue -Catalog $catalog -Config $unknownToolJson } $unknownTool
    Assert-Throws { Resolve-DynamoTaskQueue -Catalog $catalog -Config $unknownInput } (U '672a77e576848f385165')
    Assert-Throws { Resolve-DynamoTaskQueue -Catalog $catalog -Config $missingInput } (U '7f3a5c115fc5586b8f385165')
    Assert-Throws { Read-DynamoTaskConfig -Json $templateHost } '.rvt'
    Assert-Throws { Read-DynamoTaskConfig -Json $badVersion } (U '7248672c')
    Assert-Throws { Read-DynamoTaskConfig -Json $badConfirm } 'confirmWrite'
    Assert-Throws { Read-DynamoTaskConfig -Json $emptyJobs } $needJob
    Assert-Throws { Read-DynamoTaskConfig -Json $broken } $badJsonWord
  }

  Test-Case 'duplicate tools keep the listed order' {
    $resolved = Resolve-DynamoTaskQueue -Catalog $catalog -Config (Read-Fixture 'duplicate-jobs.json')
    $ids = @($resolved.jobs | ForEach-Object { $_.toolId })
    Assert-Equal ($ids -join ',') 'fill-scada-params,copy-view-templates,fill-scada-params' 'duplicate order'
  }

  Test-Case 'checkbox selection follows catalog order and drops duplicates' {
    $order = Get-DynamoCatalogToolOrder -Catalog $catalog -ToolIds @('excel-sync', 'copy-view-templates', 'excel-sync')
    Assert-Equal $order.Length 2 'selection count'
    Assert-Equal $order[0] 'copy-view-templates' 'first'
    Assert-Equal $order[1] 'excel-sync' 'second'
    Assert-Throws { Get-DynamoCatalogToolOrder -Catalog $catalog -ToolIds @('not-a-tool') } $unknownTool
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
    Assert-Throws { Move-DynamoQueueEntries -Entries $entries -Index 1 -Offset -1 } $cannotMove
  }

  Test-Case 'legacy tools.json without contract fields still loads' {
    $legacy = Read-DynamoToolboxCatalog -Json (Read-Fixture 'legacy-tools.json')
    Assert-Equal $legacy.Length 1 'legacy count'
    Assert-True (-not $legacy[0].SupportsDryRun) 'legacy dry-run'
    $resolved = Resolve-DynamoTaskQueue -Catalog $legacy -Config (Read-Fixture 'legacy-job.json')
    Assert-True (-not $resolved.jobs[0].run) 'legacy run'
    $legacyRun = Read-Fixture 'legacy-run.json'
    Assert-Throws { Resolve-DynamoTaskQueue -Catalog $legacy -Config $legacyRun } (U '672a77e576848f385165')
  }

  Test-Case 'future inspector and DWG importer follow the contract' {
    $future = Read-DynamoToolboxCatalog -Json (Read-Fixture 'future-tools.json')
    $readOnly = Resolve-DynamoTaskQueue -Catalog $future -Config (Read-Fixture 'inspector-job.json')
    Assert-Equal $readOnly.jobs[0].inputs.scope 'all' 'inspector default'
    Assert-True (-not $readOnly.jobs[0].run) 'inspector does not write'
    $dry = Resolve-DynamoTaskQueue -Catalog $future -Config (Read-Fixture 'dwg-dry.json')
    Assert-True (-not $dry.jobs[0].run) 'dwg dry run'
    Assert-Equal ([int64]$dry.jobs[0].inputs.copies) 1 'integer default'
    if ([Math]::Abs(([double]$dry.jobs[0].inputs.scale) - 1.5) -gt 0.0001) {
      throw "scale actual [$($dry.jobs[0].inputs.scale)]"
    }
    $dwgWrite = Read-Fixture 'dwg-unconfirmed.json'
    $dwgFraction = Read-Fixture 'dwg-fraction.json'
    Assert-Throws { Resolve-DynamoTaskQueue -Catalog $future -Config $dwgWrite } 'confirmWrite'
    Assert-Throws { Resolve-DynamoTaskQueue -Catalog $future -Config $dwgFraction } $integerWord
    $write = Resolve-DynamoTaskQueue -Catalog $future -Config (Read-Fixture 'dwg-confirmed.json')
    Assert-True $write.jobs[0].run 'dwg write'
  }

  Test-Case 'catalog rejects a dry-run default of true and an absolute dyn path' {
    $badDefault = Read-Fixture 'bad-default.json'
    $absoluteDyn = Read-Fixture 'absolute-dyn.json'
    Assert-Throws { Read-DynamoToolboxCatalog -Json $badDefault } $defaultFalse
    Assert-Throws { Read-DynamoToolboxCatalog -Json $absoluteDyn } $relativePath
  }

  $session = New-DynamoQueueSession -Plan $plan -SessionId 'sample-batch_20261111_060000' -CreatedAt '2026-11-11T06:00:00'
  $work = Join-Path ([System.IO.Path]::GetTempPath()) ('dynamo-queue-' + [guid]::NewGuid().ToString('N'))

  Test-Case 'run log, csv, markdown, and html round-trip' {
    $chinese = Resolve-DynamoTaskQueue -Catalog $catalog -Config (Read-Fixture 'chinese-job.json')
    $logged = New-DynamoQueueSession -Plan $chinese -SessionId 'batch_20261111_060000' -CreatedAt '2026-11-11T06:00:00'
    Assert-Equal $logged.sessionId 'batch_20261111_060000' 'slug'
    Assert-Equal $logged.sessionName $sampleBatch 'session name'
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
    $expectedHost = 'C:/' + $modelWord + '/' + $sampleHost + '.rvt'
    Assert-Equal $imported.hostProject $expectedHost 'chinese host'
    Assert-True (-not $imported.jobs[0].graphExecutedByLauncher) 'not executed'
    $markdown = [System.IO.File]::ReadAllText($paths.Markdown)
    $html = [System.IO.File]::ReadAllText($paths.Html)
    Assert-True ($markdown.Contains($fillName)) 'markdown tool'
    Assert-True ($html.Contains($fillName)) 'html tool'
    Assert-True ($markdown.Contains($sampleHost)) 'markdown path'

    $dispatch = Get-DynamoQueueDispatchPlan -Session $logged
    Assert-True (-not $dispatch.ExecuteGraph) 'dispatch does not execute'
    Assert-True $dispatch.ManualMode 'dispatch manual'
    $expectedArgs = '-ToolId fill-scada-params -Project ' + $expectedHost + ' -Launch'
    Assert-Equal ($dispatch.ArgumentList -join ' ') $expectedArgs 'journal arguments'
    Assert-True ((Get-Command Get-DynamoQueueDispatchPlan).Parameters.Keys -notcontains 'Execute') 'no execute parameter'

    Set-DynamoQueueJobOpened -Session $logged -Index 1 -StartedAt '2026-11-11T06:01:00' | Out-Null
    Assert-Throws { Get-DynamoQueueDispatchPlan -Session $logged } $recordFirst
    Assert-Throws {
      Set-DynamoQueueJobResult -Session $logged -Index 1 -Status 'written' -EndedAt '2026-11-11T06:02:00'
    } $cannotWrite
    $marked = 'bad, ' + [char]60 + 'bad' + [char]62
    Set-DynamoQueueJobResult -Session $logged -Index 1 -Status 'dry-run' -Counts @{ files = 2; changed = 0 } -Errors @($marked) -EndedAt '2026-11-11T06:02:00' | Out-Null
    Assert-Equal $logged.jobs[0].counts.files 2 'count files'
    Assert-Equal $logged.jobs[0].counts.changed 0 'count changed'
    Assert-True ($null -eq $logged.jobs[0].counts.skipped) 'count skipped stays empty'
    $paths = Export-DynamoQueueSession -Session $logged -OutputDirectory $work -UpdatedAt '2026-11-11T06:02:01'
    $csv = [System.IO.File]::ReadAllText($paths.Csv)
    $lines = @($csv.TrimEnd().Split("`n") | Where-Object { $_.Trim() -ne '' })
    Assert-Equal $lines.Count 2 'csv has one data row'
    Assert-True ($csv.Contains('"' + $marked + '"')) 'csv quotes comma'
    $html = [System.IO.File]::ReadAllText($paths.Html)
    $escaped = [char]38 + 'lt;bad' + [char]38 + 'gt;'
    Assert-True ($html.Contains($escaped)) 'html escapes markup'
    Assert-True (-not $html.Contains($marked)) 'html has no raw tag'
    $card = Format-DynamoJobCard -Session $logged -Job $logged.jobs[0] -Catalog $catalog
    Assert-True ($card.Contains($manualMode)) 'card manual'
    Assert-True ($card.Contains($pressRun)) 'card run by hand'
    Assert-True ($card.Contains('False')) 'card stays false'
    $batchDir = 'C:/' + $modelWord + '/' + $sampleBatch
    Assert-True ($card.Contains($batchDir)) 'card directory'
  }

  Test-Case 'a second export replaces the row instead of appending' {
    $again = Export-DynamoQueueSession -Session $session -OutputDirectory (Join-Path $work 'second') -UpdatedAt '2026-11-11T07:00:00'
    $csv = [System.IO.File]::ReadAllText($again.Csv)
    $lines = @($csv.TrimEnd().Split("`n") | Where-Object { $_.Trim() -ne '' })
    Assert-Equal $lines.Count ($session.jobs.Length + 1) 'header plus jobs'
  }

  Test-Case 'written is stored only after confirmation and an open job' {
    $writePlan = Resolve-DynamoTaskQueue -Catalog $catalog -Config (Read-Fixture 'confirmed-queue.json')
    $writeSession = New-DynamoQueueSession -Plan $writePlan -SessionId 'sample-batch_20261111_070000' -CreatedAt '2026-11-11T07:00:00'
    Assert-Throws { Set-DynamoQueueJobResult -Session $writeSession -Index 2 -Status 'dry-run' } $openFirst
    Set-DynamoQueueJobOpened -Session $writeSession -Index 1 -StartedAt '2026-11-11T07:01:00' | Out-Null
    Assert-Throws { Set-DynamoQueueJobOpened -Session $writeSession -Index 2 -StartedAt '2026-11-11T07:02:00' } $nextWord
    Set-DynamoQueueJobResult -Session $writeSession -Index 1 -Status 'dry-run' -EndedAt '2026-11-11T07:03:00' | Out-Null
    Set-DynamoQueueJobOpened -Session $writeSession -Index 2 -StartedAt '2026-11-11T07:04:00' | Out-Null
    Assert-Throws {
      Set-DynamoQueueJobResult -Session $writeSession -Index 2 -Status 'written' -Counts @{ other = 1 } -EndedAt '2026-11-11T07:04:30'
    } $unknownCount
    Assert-Throws {
      Set-DynamoQueueJobResult -Session $writeSession -Index 2 -Status 'written' -Counts @{ files = -1 } -EndedAt '2026-11-11T07:05:00'
    } $nonNegative
    Set-DynamoQueueJobResult -Session $writeSession -Index 2 -Status 'written' -Counts @{ files = 1; changed = 4; skipped = 0; failed = 0 } -Errors @() -EndedAt '2026-11-11T07:05:00' | Out-Null
    Assert-Equal $writeSession.jobs[1].status 'written' 'written status'
    $cursor = Get-DynamoQueueCursor -Session $writeSession
    Assert-True ($null -eq $cursor.Next) 'queue finished'
    Assert-Throws {
      Set-DynamoQueueJobResult -Session $writeSession -Index 2 -Status 'written' -Counts @{ other = 1 }
    } $openFirst
  }

  Test-Case 'tampered execute flag is refused' {
    $logged = New-DynamoQueueSession -Plan (Resolve-DynamoTaskQueue -Catalog $catalog -Config $example) -SessionId 'sample-batch_20261111_080000' -CreatedAt '2026-11-11T08:00:00'
    $logged.jobs[0].graphExecutedByLauncher = $true
    Assert-Throws { Export-DynamoQueueSession -Session $logged -OutputDirectory (Join-Path $work 'bad') } $willNotRun
    $badPath = Join-Path $work 'bad-log.json'
    $utf8 = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText($badPath, (Read-Fixture 'bad-log.json'), $utf8)
    Assert-Throws { Import-DynamoQueueSession -Path $badPath } $willNotRun
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
    Assert-True ($ui.Contains('ExecuteGraph')) 'ui checks execute flag'
    Assert-True ($ui.Contains('-ToolId $dispatch.ToolId -Project $dispatch.Project -Launch')) 'queue uses the journal launcher'
    Assert-True ($ui.Contains('-ToolId $script:catalog[$index].Id -Project $project -Launch')) 'single tool still launches'
    Assert-True ($library.Contains($willNotRun)) 'library states it does not run graphs'
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
    $writePlan = Resolve-DynamoTaskQueue -Catalog $catalog -Config (Read-Fixture 'excel-card.json')
    $writeSession = New-DynamoQueueSession -Plan $writePlan -SessionId 'sample-batch_20261111_090000' -CreatedAt '2026-11-11T09:00:00'
    $card = Format-DynamoJobCard -Session $writeSession -Job $writeSession.jobs[0] -Catalog $catalog
    Assert-True ($card.Contains('True')) 'write card'
    Assert-True (($writeSession.jobs[0].inputFiles -join '|').Contains('sample-parameters.xlsx')) 'workbook is an input file'
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
