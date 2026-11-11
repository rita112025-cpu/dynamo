#Requires -Version 5.1
<#
.SYNOPSIS
  Task queue, tool contract, and run log for the Dynamo toolbox.

.DESCRIPTION
  Pure PowerShell. This file does not start Revit and does not execute a Dynamo
  graph. The desktop menu calls launcher/poc/New-DynamoJournal.ps1, which still
  loads each graph in manual mode.

  Dot-source this file. Windows PowerShell 5.1 and PowerShell 7 can both run it.
#>

$ErrorActionPreference = 'Stop'

$script:DynamoQueueInputTypes = @(
  'string', 'boolean', 'integer', 'number', 'directory', 'file', 'string-list'
)
$script:DynamoQueueCountNames = @('files', 'changed', 'skipped', 'failed')
$script:DynamoQueueResultStatuses = @('dry-run', 'written', 'failed', 'skipped')

function Get-DynamoInvariantCulture {
  return [System.Globalization.CultureInfo]::InvariantCulture
}

function Get-DynamoTimestamp {
  param([datetime]$When = (Get-Date))
  return $When.ToString('yyyy-MM-ddTHH:mm:ss', (Get-DynamoInvariantCulture))
}

function Get-DynamoManualNote {
  return '圖形以手動模式開啟，啟動器不會執行。請在 Dynamo 核對輸入後自行按執行。'
}

function Read-DynamoUtf8Text {
  param([Parameter(Mandatory)][string]$Path)
  $utf8 = New-Object System.Text.UTF8Encoding $false
  return [System.IO.File]::ReadAllText($Path, $utf8)
}

function Write-DynamoUtf8Text {
  param(
    [Parameter(Mandatory)][string]$Path,
    [Parameter(Mandatory)][string]$Text,
    [switch]$Bom
  )
  $utf8 = New-Object System.Text.UTF8Encoding $Bom
  [System.IO.File]::WriteAllText($Path, $Text, $utf8)
}

function ConvertTo-DynamoJsonString {
  param([string]$Text)
  if ($null -eq $Text) { return 'null' }
  $sb = New-Object System.Text.StringBuilder
  [void]$sb.Append('"')
  foreach ($ch in $Text.ToCharArray()) {
    $code = [int]$ch
    if ($code -eq 34) { [void]$sb.Append('\"'); continue }
    if ($code -eq 92) { [void]$sb.Append('\\'); continue }
    if ($code -eq 8) { [void]$sb.Append('\b'); continue }
    if ($code -eq 12) { [void]$sb.Append('\f'); continue }
    if ($code -eq 10) { [void]$sb.Append('\n'); continue }
    if ($code -eq 13) { [void]$sb.Append('\r'); continue }
    if ($code -eq 9) { [void]$sb.Append('\t'); continue }
    if ($code -lt 32) {
      [void]$sb.AppendFormat('\u{0:x4}', $code)
      continue
    }
    [void]$sb.Append($ch)
  }
  [void]$sb.Append('"')
  return $sb.ToString()
}

function ConvertTo-DynamoJsonNumber {
  param($Value)
  $culture = Get-DynamoInvariantCulture
  if ($Value -is [decimal]) {
    return $Value.ToString($culture)
  }
  return [System.Convert]::ToString($Value, $culture)
}

function ConvertTo-DynamoJson {
  param($Value, [int]$Depth = 0)
  $pad = '  ' * $Depth
  $inner = '  ' * ($Depth + 1)
  if ($null -eq $Value) { return 'null' }
  if ($Value -is [bool]) {
    if ($Value) { return 'true' }
    return 'false'
  }
  if ($Value -is [string]) { return (ConvertTo-DynamoJsonString $Value) }
  if ($Value -is [byte] -or $Value -is [int16] -or $Value -is [int] -or $Value -is [long] -or
      $Value -is [decimal] -or $Value -is [double] -or $Value -is [float]) {
    return (ConvertTo-DynamoJsonNumber $Value)
  }
  if ($Value -is [System.Collections.IDictionary]) {
    $keys = @($Value.Keys)
    if ($keys.Count -eq 0) { return '{}' }
    $lines = New-Object System.Collections.Generic.List[string]
    foreach ($key in $keys) {
      $encoded = ConvertTo-DynamoJson -Value $Value[$key] -Depth ($Depth + 1)
      $lines.Add($inner + (ConvertTo-DynamoJsonString ([string]$key)) + ': ' + $encoded)
    }
    return "{`n" + ($lines -join ",`n") + "`n" + $pad + '}'
  }
  if ($Value -is [System.Collections.IEnumerable]) {
    $items = @($Value)
    if ($items.Count -eq 0) { return '[]' }
    $lines = New-Object System.Collections.Generic.List[string]
    foreach ($item in $items) {
      $lines.Add($inner + (ConvertTo-DynamoJson -Value $item -Depth ($Depth + 1)))
    }
    return "[`n" + ($lines -join ",`n") + "`n" + $pad + ']'
  }
  throw "無法轉成 JSON 的型別：$($Value.GetType().FullName)"
}

function ConvertFrom-DynamoJsonElement {
  param($Element)
  $kind = $Element.ValueKind.ToString()
  if ($kind -eq 'Object') {
    $mapped = [ordered]@{}
    foreach ($prop in $Element.EnumerateObject()) {
      $mapped[$prop.Name] = ConvertFrom-DynamoJsonElement -Element $prop.Value
    }
    return $mapped
  }
  if ($kind -eq 'Array') {
    $list = New-Object System.Collections.Generic.List[object]
    foreach ($item in $Element.EnumerateArray()) {
      $list.Add((ConvertFrom-DynamoJsonElement -Element $item))
    }
    $items = $list.ToArray()
    return ,$items
  }
  if ($kind -eq 'String') { return $Element.GetString() }
  if ($kind -eq 'Number') {
    $raw = $Element.GetRawText()
    $culture = Get-DynamoInvariantCulture
    if ($raw -match '[.eE]') {
      return [double]::Parse($raw, $culture)
    }
    return [int64]::Parse($raw, $culture)
  }
  if ($kind -eq 'True') { return $true }
  if ($kind -eq 'False') { return $false }
  if ($kind -eq 'Null') { return $null }
  throw "不支援的 JSON 型別：$kind"
}

function ConvertFrom-DynamoJsonText {
  param([Parameter(Mandatory)][string]$Text)
  try {
    if ($PSVersionTable.PSEdition -eq 'Core') {
      $doc = [System.Text.Json.JsonDocument]::Parse($Text)
      try {
        return ConvertFrom-DynamoJsonElement -Element $doc.RootElement
      } finally {
        $doc.Dispose()
      }
    }
    Add-Type -AssemblyName System.Web.Extensions -ErrorAction Stop
    $serializer = New-Object System.Web.Script.Serialization.JavaScriptSerializer
    $serializer.MaxJsonLength = [int]::MaxValue
    $serializer.RecursionLimit = 64
    return ConvertTo-DynamoData -Value $serializer.DeserializeObject($Text)
  } catch {
    throw "不是合法的 JSON。$($_.Exception.Message)"
  }
}

function ConvertTo-DynamoData {
  param($Value)
  if ($null -eq $Value) { return $null }
  if ($Value -is [string] -or $Value -is [bool]) { return $Value }
  if ($Value -is [datetime]) {
    return $Value.ToString('yyyy-MM-ddTHH:mm:ss', (Get-DynamoInvariantCulture))
  }
  if ($Value -is [byte] -or $Value -is [int16] -or $Value -is [int] -or $Value -is [long] -or
      $Value -is [decimal] -or $Value -is [double] -or $Value -is [float]) {
    return $Value
  }
  if ($Value -is [System.Collections.IDictionary]) {
    $mapped = [ordered]@{}
    foreach ($key in @($Value.Keys)) {
      $mapped[[string]$key] = ConvertTo-DynamoData -Value $Value[$key]
    }
    return $mapped
  }
  if ($Value -is [System.Management.Automation.PSCustomObject]) {
    $mapped = [ordered]@{}
    foreach ($prop in $Value.PSObject.Properties) {
      $mapped[$prop.Name] = ConvertTo-DynamoData -Value $prop.Value
    }
    return $mapped
  }
  if ($Value -is [System.Collections.IEnumerable]) {
    $list = New-Object System.Collections.Generic.List[object]
    foreach ($item in $Value) {
      $list.Add((ConvertTo-DynamoData -Value $item))
    }
    $items = $list.ToArray()
    return ,$items
  }
  return $Value
}

function Copy-DynamoValue {
  param($Value)
  if ($null -eq $Value) { return $null }
  if ($Value -is [string] -or $Value -is [bool]) { return $Value }
  if ($Value -is [byte] -or $Value -is [int16] -or $Value -is [int] -or $Value -is [long] -or
      $Value -is [decimal] -or $Value -is [double] -or $Value -is [float]) {
    return $Value
  }
  if ($Value -is [System.Collections.IDictionary]) {
    $mapped = [ordered]@{}
    foreach ($key in @($Value.Keys)) {
      $mapped[[string]$key] = Copy-DynamoValue -Value $Value[$key]
    }
    return $mapped
  }
  if ($Value -is [System.Collections.IEnumerable]) {
    $list = New-Object System.Collections.Generic.List[object]
    foreach ($item in @($Value)) {
      $list.Add((Copy-DynamoValue -Value $item))
    }
    $items = $list.ToArray()
    return ,$items
  }
  return $Value
}

function Test-DynamoWholeNumber {
  param($Value)
  if ($Value -is [byte] -or $Value -is [int16] -or $Value -is [int] -or $Value -is [long]) {
    return $true
  }
  if ($Value -is [decimal] -or $Value -is [double] -or $Value -is [float]) {
    $asDecimal = [decimal]$Value
    return ($asDecimal -eq [decimal]::Truncate($asDecimal))
  }
  return $false
}

function ConvertTo-DynamoInt64 {
  param($Value)
  if (-not (Test-DynamoWholeNumber $Value)) {
    throw "需要整數，收到：$Value"
  }
  return [int64]$Value
}

function Test-DynamoNonNegativeInteger {
  param($Value)
  if (-not (Test-DynamoWholeNumber $Value)) { return $false }
  return ([int64]$Value -ge 0)
}

function Assert-DynamoAllowedKeys {
  param($Object, [string[]]$Allowed, [string]$Label)
  foreach ($key in @($Object.Keys)) {
    if ($Allowed -notcontains [string]$key) {
      throw "$Label 有未知的欄位 '$key'。"
    }
  }
}

function Assert-DynamoObject {
  param($Value, [string]$Label)
  if ($null -eq $Value -or -not ($Value -is [System.Collections.IDictionary])) {
    throw "$Label 必須是物件。"
  }
}

function Get-DynamoObjectArray {
  param($Value, [string]$Label)
  if ($null -eq $Value) {
    throw "$Label 必須是清單。"
  }
  if ($Value -is [string] -or $Value -is [System.Collections.IDictionary]) {
    throw "$Label 必須是清單。"
  }
  if ($Value -is [System.Collections.IEnumerable]) {
    return @($Value)
  }
  throw "$Label 必須是清單。"
}

function Find-DynamoTool {
  param($Catalog, [string]$ToolId)
  foreach ($tool in @($Catalog)) {
    if ([string]$tool.Id -eq $ToolId) { return $tool }
  }
  return $null
}

function Get-DynamoKnownToolIds {
  param($Catalog)
  $ids = New-Object System.Collections.Generic.List[string]
  foreach ($tool in @($Catalog)) { $ids.Add([string]$tool.Id) }
  return ($ids -join ', ')
}

function New-DynamoInputSpec {
  param($Raw, [string]$ToolId)
  Assert-DynamoObject -Value $Raw -Label "工具 '$ToolId' 的輸入"
  Assert-DynamoAllowedKeys -Object $Raw -Allowed @(
    'name', 'type', 'label', 'required', 'default', 'enum', 'writesModel', 'help'
  ) -Label "工具 '$ToolId' 的輸入"
  $name = [string]$Raw.name
  if ($name -notmatch '^[A-Za-z][A-Za-z0-9]*$') {
    throw "工具 '$ToolId' 的輸入名稱 '$name' 必須是英數識別名稱。"
  }
  $typeName = [string]$Raw.type
  if ($script:DynamoQueueInputTypes -notcontains $typeName) {
    throw "工具 '$ToolId' 的輸入 '$name' 型別 '$typeName' 不在契約內。"
  }
  $label = [string]$Raw.label
  if ([string]::IsNullOrWhiteSpace($label)) {
    throw "工具 '$ToolId' 的輸入 '$name' 需要 label。"
  }
  $required = $false
  if ($Raw.Contains('required')) {
    if ($Raw.required -isnot [bool]) {
      throw "工具 '$ToolId' 的輸入 '$name' 的 required 必須是布林值。"
    }
    $required = [bool]$Raw.required
  }
  $writesModel = $false
  if ($Raw.Contains('writesModel')) {
    if ($Raw.writesModel -isnot [bool]) {
      throw "工具 '$ToolId' 的輸入 '$name' 的 writesModel 必須是布林值。"
    }
    $writesModel = [bool]$Raw.writesModel
  }
  $enumValues = $null
  if ($Raw.Contains('enum')) {
    if ($typeName -ne 'string') {
      throw "工具 '$ToolId' 的輸入 '$name' 只有 string 可以帶 enum。"
    }
    $enumValues = @(Get-DynamoObjectArray -Value $Raw.enum -Label "工具 '$ToolId' 的輸入 '$name' 的 enum")
    if ($enumValues.Count -lt 1) {
      throw "工具 '$ToolId' 的輸入 '$name' 的 enum 是空的。"
    }
    foreach ($item in $enumValues) {
      if ($item -isnot [string] -or [string]::IsNullOrWhiteSpace($item)) {
        throw "工具 '$ToolId' 的輸入 '$name' 的 enum 只能放非空白文字。"
      }
    }
  }
  $spec = [ordered]@{
    name        = $name
    type        = $typeName
    label       = $label
    required    = $required
    writesModel = $writesModel
    help        = ''
    enum        = $enumValues
    hasDefault  = $false
    default     = $null
  }
  if ($Raw.Contains('help')) {
    if ($Raw.help -isnot [string]) {
      throw "工具 '$ToolId' 的輸入 '$name' 的 help 必須是文字。"
    }
    $spec.help = [string]$Raw.help
  }
  if ($Raw.Contains('default')) {
    $spec.hasDefault = $true
    $spec.default = Copy-DynamoValue -Value $Raw.default
    Assert-DynamoInputValue -Spec $spec -Value $spec.default -ToolId $ToolId -AllowEmpty:$false
  } elseif (-not $required) {
    throw "工具 '$ToolId' 的選填輸入 '$name' 必須有 default。"
  }
  if ($writesModel -and $typeName -ne 'boolean') {
    throw "工具 '$ToolId' 的輸入 '$name' 只有布林值可以標記 writesModel。"
  }
  return $spec
}

function Assert-DynamoInputValue {
  param($Spec, $Value, [string]$ToolId, [switch]$AllowEmpty)
  $name = [string]$Spec.name
  $typeName = [string]$Spec.type
  if ($null -eq $Value) {
    throw "工具 '$ToolId' 的輸入 '$name' 不能是 null。"
  }
  if ($typeName -eq 'string' -or $typeName -eq 'directory' -or $typeName -eq 'file') {
    if ($Value -isnot [string]) {
      throw "工具 '$ToolId' 的輸入 '$name' 必須是文字。"
    }
    if (-not $AllowEmpty -and [string]::IsNullOrWhiteSpace($Value) -and $Spec.required) {
      throw "工具 '$ToolId' 缺少必填輸入 '$name'。"
    }
    if ($typeName -eq 'string' -and $Spec.enum -and -not [string]::IsNullOrWhiteSpace($Value)) {
      $ok = $false
      foreach ($item in @($Spec.enum)) {
        if ($item -eq $Value) { $ok = $true; break }
      }
      if (-not $ok) {
        throw "工具 '$ToolId' 的輸入 '$name' 必須是：$((@($Spec.enum) -join ', '))。"
      }
    }
    return
  }
  if ($typeName -eq 'boolean') {
    if ($Value -isnot [bool]) {
      throw "工具 '$ToolId' 的輸入 '$name' 必須是布林值 true 或 false。"
    }
    return
  }
  if ($typeName -eq 'integer') {
    if (-not (Test-DynamoWholeNumber $Value)) {
      throw "工具 '$ToolId' 的輸入 '$name' 必須是整數。"
    }
    return
  }
  if ($typeName -eq 'number') {
    $numeric = $Value -is [byte] -or $Value -is [int16] -or $Value -is [int] -or $Value -is [long] -or
      $Value -is [decimal] -or $Value -is [double] -or $Value -is [float]
    if (-not $numeric) {
      throw "工具 '$ToolId' 的輸入 '$name' 必須是數字。"
    }
    return
  }
  if ($typeName -eq 'string-list') {
    $items = @(Get-DynamoObjectArray -Value $Value -Label "工具 '$ToolId' 的輸入 '$name'")
    foreach ($item in $items) {
      if ($item -isnot [string]) {
        throw "工具 '$ToolId' 的輸入 '$name' 的清單只能放文字。"
      }
    }
    if ($Spec.required -and $items.Count -lt 1) {
      throw "工具 '$ToolId' 缺少必填輸入 '$name'。"
    }
    return
  }
  throw "工具 '$ToolId' 的輸入 '$name' 型別無法檢查。"
}

function New-DynamoToolObject {
  param($Raw)
  Assert-DynamoObject -Value $Raw -Label '工具項目'
  Assert-DynamoAllowedKeys -Object $Raw -Allowed @(
    'id', 'name', 'dyn', 'supportsDryRun', 'dryRunInput', 'inputs'
  ) -Label '工具項目'
  $id = [string]$Raw.id
  if ($id -notmatch '^[a-z0-9]+(-[a-z0-9]+)*$') {
    throw "工具 id '$id' 必須是小寫英數，可用連字號。"
  }
  $name = [string]$Raw.name
  $dyn = [string]$Raw.dyn
  if ([string]::IsNullOrWhiteSpace($name) -or [string]::IsNullOrWhiteSpace($dyn)) {
    throw "工具 '$id' 需要 name 與 dyn。"
  }
  if ($dyn -match '^[A-Za-z]:' -or $dyn.StartsWith('/') -or $dyn.StartsWith('\') -or $dyn -match '\.\.') {
    throw "工具 '$id' 的 dyn 必須是儲存庫內的相對路徑。"
  }
  if (-not $dyn.EndsWith('.dyn')) {
    throw "工具 '$id' 的 dyn 必須以 .dyn 結尾。"
  }
  $supportsDryRun = $false
  if ($Raw.Contains('supportsDryRun')) {
    if ($Raw.supportsDryRun -isnot [bool]) {
      throw "工具 '$id' 的 supportsDryRun 必須是布林值。"
    }
    $supportsDryRun = [bool]$Raw.supportsDryRun
  }
  $dryRunInput = $null
  if ($Raw.Contains('dryRunInput')) {
    $dryRunInput = [string]$Raw.dryRunInput
  }
  if ($supportsDryRun -and [string]::IsNullOrWhiteSpace($dryRunInput)) {
    throw "工具 '$id' 宣告支援試跑，必須指定 dryRunInput。"
  }
  if (-not $supportsDryRun -and -not [string]::IsNullOrWhiteSpace($dryRunInput)) {
    throw "工具 '$id' 沒有支援試跑，不能指定 dryRunInput。"
  }
  $inputs = @()
  if ($Raw.Contains('inputs')) {
    $rawInputs = @(Get-DynamoObjectArray -Value $Raw.inputs -Label "工具 '$id' 的 inputs")
    $built = New-Object System.Collections.Generic.List[object]
    $seen = @{}
    foreach ($item in $rawInputs) {
      $spec = New-DynamoInputSpec -Raw $item -ToolId $id
      if ($seen.ContainsKey($spec.name)) {
        throw "工具 '$id' 的輸入 '$($spec.name)' 重複。"
      }
      $seen[$spec.name] = $true
      $built.Add($spec)
    }
    $inputs = $built.ToArray()
  }
  if ($supportsDryRun) {
    $matched = $null
    foreach ($spec in @($inputs)) {
      if ($spec.name -eq $dryRunInput) { $matched = $spec; break }
    }
    if ($null -eq $matched) {
      throw "工具 '$id' 的 dryRunInput '$dryRunInput' 不在 inputs 裡。"
    }
    if ($matched.type -ne 'boolean' -or -not $matched.writesModel) {
      throw "工具 '$id' 的試跑輸入 '$dryRunInput' 必須是布林值，而且 writesModel 為 true。"
    }
    if (-not $matched.hasDefault -or $matched.default -ne $false) {
      throw "工具 '$id' 的試跑輸入 '$dryRunInput' 預設必須是 false。"
    }
  }
  foreach ($spec in @($inputs)) {
    if ($spec.writesModel -and $spec.name -ne $dryRunInput) {
      throw "工具 '$id' 只有試跑開關可以標記 writesModel。"
    }
  }
  return [pscustomobject]@{
    Id              = $id
    Name            = $name
    Dyn             = $dyn
    SupportsDryRun  = $supportsDryRun
    DryRunInput     = $dryRunInput
    Inputs          = $inputs
  }
}

function Read-DynamoToolboxCatalog {
  param([string]$Path, [string]$Json)
  if ([string]::IsNullOrWhiteSpace($Json)) {
    if ([string]::IsNullOrWhiteSpace($Path)) { throw '需要工具清單的路徑或 JSON。' }
    if (-not (Test-Path -LiteralPath $Path)) { throw "tools.json 不存在：$Path" }
    $Json = Read-DynamoUtf8Text -Path $Path
  }
  $root = ConvertFrom-DynamoJsonText -Text $Json
  Assert-DynamoObject -Value $root -Label 'tools.json'
  Assert-DynamoAllowedKeys -Object $root -Allowed @('_note', 'tools') -Label 'tools.json'
  if (-not $root.Contains('tools')) { throw 'tools.json 沒有 tools。' }
  $rawTools = @(Get-DynamoObjectArray -Value $root.tools -Label 'tools')
  if ($rawTools.Count -lt 1) { throw 'tools.json 沒有列出工具。' }
  $catalog = New-Object System.Collections.Generic.List[object]
  $seen = @{}
  foreach ($raw in $rawTools) {
    $tool = New-DynamoToolObject -Raw $raw
    if ($seen.ContainsKey($tool.Id)) {
      throw "tools.json 重複列出工具 '$($tool.Id)'。"
    }
    $seen[$tool.Id] = $true
    $catalog.Add($tool)
  }
  $tools = $catalog.ToArray()
  return ,$tools
}

function Get-DynamoToolboxCatalog {
  $path = Join-Path (Split-Path -Parent $PSScriptRoot) 'tools.json'
  return Read-DynamoToolboxCatalog -Path $path
}

function Read-DynamoTaskConfig {
  param([string]$Path, [string]$Json, $Config)
  if ($null -ne $Config) {
    $root = ConvertTo-DynamoData -Value $Config
  } else {
    if ([string]::IsNullOrWhiteSpace($Json)) {
      if ([string]::IsNullOrWhiteSpace($Path)) { throw '需要任務設定的路徑或 JSON。' }
      $Json = Read-DynamoUtf8Text -Path $Path
    }
    $root = ConvertFrom-DynamoJsonText -Text $Json
  }
  Assert-DynamoObject -Value $root -Label '任務設定'
  Assert-DynamoAllowedKeys -Object $root -Allowed @(
    'version', 'sessionName', 'hostProject', 'confirmWrite', 'jobs'
  ) -Label '任務設定'
  if (-not $root.Contains('version') -or -not (Test-DynamoWholeNumber $root.version) -or [int64]$root.version -ne 1) {
    throw '任務設定的版本必須是 1。'
  }
  $sessionName = 'batch'
  if ($root.Contains('sessionName')) {
    if ($root.sessionName -isnot [string] -or [string]::IsNullOrWhiteSpace($root.sessionName)) {
      throw '任務設定的 sessionName 必須是非空白文字。'
    }
    $sessionName = [string]$root.sessionName.Trim()
  }
  if (-not $root.Contains('hostProject') -or $root.hostProject -isnot [string]) {
    throw '任務設定的 hostProject 必須是既有 .rvt 的路徑文字。'
  }
  $hostProject = [string]$root.hostProject.Trim()
  $extension = [System.IO.Path]::GetExtension($hostProject)
  if ([string]::IsNullOrWhiteSpace($extension) -or
      -not $extension.Equals('.rvt', [System.StringComparison]::OrdinalIgnoreCase)) {
    throw '宿主專案必須是 .rvt。這個佇列不開啟 .rte 樣板。'
  }
  $confirmWrite = $false
  if ($root.Contains('confirmWrite')) {
    if ($root.confirmWrite -isnot [bool]) {
      throw '任務設定的 confirmWrite 必須是布林值 true 或 false。'
    }
    $confirmWrite = [bool]$root.confirmWrite
  }
  if (-not $root.Contains('jobs')) { throw '任務設定至少要有一個工作。' }
  $rawJobs = @(Get-DynamoObjectArray -Value $root.jobs -Label '任務設定的 jobs')
  if ($rawJobs.Count -lt 1) { throw '任務設定至少要有一個工作。' }
  $jobs = New-Object System.Collections.Generic.List[object]
  foreach ($rawJob in $rawJobs) {
    Assert-DynamoObject -Value $rawJob -Label '工作'
    Assert-DynamoAllowedKeys -Object $rawJob -Allowed @('toolId', 'inputs') -Label '工作'
    $toolId = [string]$rawJob.toolId
    if ([string]::IsNullOrWhiteSpace($toolId)) { throw '工作缺少 toolId。' }
    $inputs = [ordered]@{}
    if ($rawJob.Contains('inputs') -and $null -ne $rawJob.inputs) {
      Assert-DynamoObject -Value $rawJob.inputs -Label "工作 '$toolId' 的 inputs"
      foreach ($key in @($rawJob.inputs.Keys)) {
        $item = $rawJob.inputs[$key]
        Assert-DynamoJsonLeaf -Value $item -Label "工作 '$toolId' 的輸入 '$key'"
        $inputs[[string]$key] = Copy-DynamoValue -Value $item
      }
    }
    $jobs.Add([ordered]@{
      toolId = $toolId.Trim()
      inputs = $inputs
    })
  }
  return [ordered]@{
    version      = 1
    sessionName  = $sessionName
    hostProject  = $hostProject
    confirmWrite = $confirmWrite
    jobs         = $jobs.ToArray()
  }
}

function Assert-DynamoJsonLeaf {
  param($Value, [string]$Label)
  if ($null -eq $Value) { throw "$Label 不能是 null。" }
  if ($Value -is [string] -or $Value -is [bool]) { return }
  if ($Value -is [byte] -or $Value -is [int16] -or $Value -is [int] -or $Value -is [long] -or
      $Value -is [decimal] -or $Value -is [double] -or $Value -is [float]) {
    return
  }
  if ($Value -is [System.Collections.IDictionary]) {
    throw "$Label 不能是巢狀物件。"
  }
  if ($Value -is [System.Collections.IEnumerable]) {
    foreach ($item in @($Value)) {
      if ($null -eq $item -or $item -isnot [string]) {
        throw "$Label 的清單只能放文字。"
      }
    }
    return
  }
  throw "$Label 的值不在契約內。"
}

function Get-DynamoCatalogToolOrder {
  param($Catalog, [string[]]$ToolIds)
  $indexOf = @{}
  $position = 0
  foreach ($tool in @($Catalog)) {
    $indexOf[[string]$tool.Id] = $position
    $position++
  }
  $picked = New-Object System.Collections.Generic.List[string]
  $seen = @{}
  foreach ($toolId in @($ToolIds)) {
    if (-not $indexOf.ContainsKey($toolId)) {
      throw "未知的工具 '$toolId'。已知的工具：$(Get-DynamoKnownToolIds $Catalog)。"
    }
    if ($seen.ContainsKey($toolId)) { continue }
    $seen[$toolId] = $true
    $picked.Add($toolId)
  }
  $ordered = @($picked.ToArray() | Sort-Object { $indexOf[$_] })
  return ,$ordered
}

function New-DynamoCountBag {
  return [ordered]@{
    files   = $null
    changed = $null
    skipped = $null
    failed  = $null
  }
}

function Get-DynamoJobInputFiles {
  param([string]$HostProject, $Tool, $Inputs)
  $files = New-Object System.Collections.Generic.List[string]
  if (-not [string]::IsNullOrWhiteSpace($HostProject)) {
    $files.Add($HostProject)
  }
  foreach ($spec in @($Tool.Inputs)) {
    if ($spec.type -ne 'directory' -and $spec.type -ne 'file') { continue }
    if (-not $Inputs.Contains($spec.name)) { continue }
    $text = [string]$Inputs[$spec.name]
    if ([string]::IsNullOrWhiteSpace($text)) { continue }
    if (-not $files.Contains($text)) { $files.Add($text) }
  }
  return $files.ToArray()
}

function Resolve-DynamoTaskQueue {
  param($Catalog, $Config)
  if ($Config -is [string]) {
    $Config = Read-DynamoTaskConfig -Json $Config
  } else {
    $Config = Read-DynamoTaskConfig -Config $Config
  }
  $resolved = New-Object System.Collections.Generic.List[object]
  $index = 1
  foreach ($job in @($Config.jobs)) {
    $tool = Find-DynamoTool -Catalog $Catalog -ToolId $job.toolId
    if ($null -eq $tool) {
      throw "未知的工具 '$($job.toolId)'。已知的工具：$(Get-DynamoKnownToolIds $Catalog)。"
    }
    $provided = [ordered]@{}
    foreach ($key in @($job.inputs.Keys)) {
      $provided[[string]$key] = $job.inputs[$key]
    }
    $inputs = [ordered]@{}
    foreach ($spec in @($tool.Inputs)) {
      $value = $null
      $hasValue = $false
      if ($provided.Contains($spec.name)) {
        $value = $provided[$spec.name]
        $hasValue = $true
        $provided.Remove($spec.name)
      } elseif ($spec.hasDefault) {
        $value = Copy-DynamoValue -Value $spec.default
        $hasValue = $true
      }
      if (-not $hasValue) {
        throw "工具 '$($tool.Id)' 缺少必填輸入 '$($spec.name)'。"
      }
      if (($spec.type -eq 'string' -or $spec.type -eq 'directory' -or $spec.type -eq 'file') -and $value -is [string]) {
        $value = $value.Trim()
      }
      $allowEmpty = -not $spec.required
      Assert-DynamoInputValue -Spec $spec -Value $value -ToolId $tool.Id -AllowEmpty:$allowEmpty
      if ($spec.required -and ($spec.type -eq 'string' -or $spec.type -eq 'directory' -or $spec.type -eq 'file') -and
          [string]::IsNullOrWhiteSpace([string]$value)) {
        throw "工具 '$($tool.Id)' 缺少必填輸入 '$($spec.name)'。"
      }
      if ($spec.type -eq 'integer') {
        $inputs[$spec.name] = ConvertTo-DynamoInt64 $value
      } else {
        $inputs[$spec.name] = $value
      }
    }
    foreach ($key in @($provided.Keys)) {
      throw "工具 '$($tool.Id)' 有未知的輸入 '$key'。"
    }
    $run = $false
    if ($tool.SupportsDryRun) {
      $run = [bool]$inputs[$tool.DryRunInput]
      if ($run -and -not $Config.confirmWrite) {
        throw "工具 '$($tool.Id)' 的寫入開關是 true，但任務設定的 confirmWrite 不是 true。預設必須試跑；寫入需要明確確認。"
      }
    }
    $resolved.Add([ordered]@{
      index                   = $index
      toolId                  = [string]$tool.Id
      toolName                = [string]$tool.Name
      dyn                     = [string]$tool.Dyn
      run                     = [bool]$run
      inputs                  = $inputs
      inputFiles              = @(Get-DynamoJobInputFiles -HostProject $Config.hostProject -Tool $tool -Inputs $inputs)
      manualMode              = $true
      graphExecutedByLauncher = $false
      note                    = (Get-DynamoManualNote)
    })
    $index++
  }
  return [ordered]@{
    version      = 1
    sessionName  = [string]$Config.sessionName
    hostProject  = [string]$Config.hostProject
    confirmWrite = [bool]$Config.confirmWrite
    jobs         = $resolved.ToArray()
  }
}

function Test-DynamoTaskConfigRequestsWrite {
  param($Catalog, $Config)
  if ($Config -is [string]) { $Config = Read-DynamoTaskConfig -Json $Config }
  if ($Config.confirmWrite) { return $true }
  foreach ($job in @($Config.jobs)) {
    $tool = Find-DynamoTool -Catalog $Catalog -ToolId $job.toolId
    if ($null -eq $tool -or -not $tool.SupportsDryRun) { continue }
    if ($job.inputs.Contains($tool.DryRunInput) -and $job.inputs[$tool.DryRunInput] -eq $true) {
      return $true
    }
  }
  return $false
}

function Reset-DynamoTaskConfigToDryRun {
  param($Catalog, $Config)
  $Config.confirmWrite = $false
  $jobs = New-Object System.Collections.Generic.List[object]
  foreach ($job in @($Config.jobs)) {
    $tool = Find-DynamoTool -Catalog $Catalog -ToolId $job.toolId
    if ($null -ne $tool -and $tool.SupportsDryRun) {
      $job.inputs[$tool.DryRunInput] = $false
    }
    $jobs.Add($job)
  }
  $Config.jobs = $jobs.ToArray()
  return $Config
}

function New-DynamoJobDraft {
  param($Catalog, [Parameter(Mandatory)][string]$ToolId)
  $tool = Find-DynamoTool -Catalog $Catalog -ToolId $ToolId
  if ($null -eq $tool) {
    throw "未知的工具 '$ToolId'。已知的工具：$(Get-DynamoKnownToolIds $Catalog)。"
  }
  $inputs = [ordered]@{}
  foreach ($spec in @($tool.Inputs)) {
    if ($spec.hasDefault) {
      $inputs[$spec.name] = Copy-DynamoValue -Value $spec.default
    } elseif ($spec.type -eq 'string' -or $spec.type -eq 'directory' -or $spec.type -eq 'file') {
      $inputs[$spec.name] = ''
    } elseif ($spec.type -eq 'string-list') {
      $inputs[$spec.name] = @()
    } elseif ($spec.type -eq 'boolean') {
      $inputs[$spec.name] = $false
    }
  }
  $run = $false
  if ($tool.SupportsDryRun) { $inputs[$tool.DryRunInput] = $false }
  return [ordered]@{
    index          = 0
    toolId         = [string]$tool.Id
    toolName       = [string]$tool.Name
    dyn            = [string]$tool.Dyn
    supportsDryRun = [bool]$tool.SupportsDryRun
    dryRunInput    = $tool.DryRunInput
    schema         = (Copy-DynamoValue -Value $tool.Inputs)
    inputs         = $inputs
    run            = $run
  }
}

function ConvertTo-DynamoTaskConfig {
  param(
    [string]$SessionName = 'batch',
    [Parameter(Mandatory)][string]$HostProject,
    [bool]$ConfirmWrite = $false,
    $Drafts
  )
  $jobs = New-Object System.Collections.Generic.List[object]
  foreach ($draft in @($Drafts)) {
    $inputs = Copy-DynamoValue -Value $draft.inputs
    $jobs.Add([ordered]@{
      toolId = [string]$draft.toolId
      inputs = $inputs
    })
  }
  return [ordered]@{
    version      = 1
    sessionName  = $SessionName
    hostProject  = $HostProject
    confirmWrite = [bool]$ConfirmWrite
    jobs         = $jobs.ToArray()
  }
}

function ConvertTo-DynamoSessionJob {
  param($ResolvedJob)
  $counts = New-DynamoCountBag
  return [ordered]@{
    index                   = [int]$ResolvedJob.index
    toolId                  = [string]$ResolvedJob.toolId
    toolName                = [string]$ResolvedJob.toolName
    dyn                     = [string]$ResolvedJob.dyn
    status                  = 'planned'
    run                     = [bool]$ResolvedJob.run
    inputs                  = (Copy-DynamoValue -Value $ResolvedJob.inputs)
    inputFiles              = (Copy-DynamoValue -Value $ResolvedJob.inputFiles)
    startedAt               = $null
    endedAt                 = $null
    counts                  = $counts
    errors                  = @()
    manualMode              = $true
    graphExecutedByLauncher = $false
    note                    = (Get-DynamoManualNote)
  }
}

function Get-DynamoSessionSlug {
  param([string]$SessionName)
  if ([string]::IsNullOrWhiteSpace($SessionName)) { return 'batch' }
  $sb = New-Object System.Text.StringBuilder
  foreach ($ch in $SessionName.ToCharArray()) {
    if ([string]$ch -match '^[A-Za-z0-9-]$') { [void]$sb.Append($ch) }
  }
  $slug = $sb.ToString().Trim('-')
  if ([string]::IsNullOrWhiteSpace($slug)) { return 'batch' }
  return $slug
}

function New-DynamoSessionId {
  param([string]$SessionName, [string]$Stamp)
  if ([string]::IsNullOrWhiteSpace($Stamp)) {
    $Stamp = (Get-Date).ToString('yyyyMMdd_HHmmss', (Get-DynamoInvariantCulture))
  }
  if ($Stamp -notmatch '^\d{8}_\d{6}$') {
    throw '工作階段時間戳必須是 yyyyMMdd_HHmmss。'
  }
  $id = '{0}_{1}' -f (Get-DynamoSessionSlug $SessionName), $Stamp
  if ($id -notmatch '^[A-Za-z0-9][A-Za-z0-9_-]*$') {
    throw '工作階段代號只能用英數、底線與連字號。'
  }
  return $id
}

function New-DynamoQueueSession {
  param($Plan, [string]$SessionId, [string]$CreatedAt)
  if ([string]::IsNullOrWhiteSpace($SessionId)) {
    $SessionId = New-DynamoSessionId -SessionName $Plan.sessionName
  }
  if ($SessionId -notmatch '^[A-Za-z0-9][A-Za-z0-9_-]*$') {
    throw '工作階段代號只能用英數、底線與連字號。'
  }
  if ([string]::IsNullOrWhiteSpace($CreatedAt)) { $CreatedAt = Get-DynamoTimestamp }
  $jobs = New-Object System.Collections.Generic.List[object]
  foreach ($job in @($Plan.jobs)) {
    $jobs.Add((ConvertTo-DynamoSessionJob $job))
  }
  if ($jobs.Count -lt 1) { throw '任務設定至少要有一個工作。' }
  return [ordered]@{
    version      = 1
    sessionId    = $SessionId
    sessionName  = [string]$Plan.sessionName
    hostProject  = [string]$Plan.hostProject
    confirmWrite = [bool]$Plan.confirmWrite
    createdAt    = $CreatedAt
    updatedAt    = $CreatedAt
    jobs         = $jobs.ToArray()
  }
}

function Update-DynamoQueueSessionPlan {
  param($Session, $Plan)
  foreach ($job in @($Session.jobs)) {
    if ($job.status -ne 'planned') {
      throw '工作階段已經開始，不能改佇列。'
    }
  }
  $Session.sessionName = [string]$Plan.sessionName
  $Session.hostProject = [string]$Plan.hostProject
  $Session.confirmWrite = [bool]$Plan.confirmWrite
  $jobs = New-Object System.Collections.Generic.List[object]
  foreach ($job in @($Plan.jobs)) {
    $jobs.Add((ConvertTo-DynamoSessionJob $job))
  }
  if ($jobs.Count -lt 1) { throw '任務設定至少要有一個工作。' }
  $Session.jobs = $jobs.ToArray()
  return $Session
}

function Get-DynamoQueueJob {
  param($Session, [int]$Index)
  foreach ($job in @($Session.jobs)) {
    if ([int]$job.index -eq $Index) { return $job }
  }
  throw "佇列沒有第 $Index 個工作。"
}

function Get-DynamoQueueCursor {
  param($Session)
  $open = New-Object System.Collections.Generic.List[object]
  foreach ($job in @($Session.jobs)) {
    if ($job.status -eq 'opened-manual') { $open.Add($job) }
  }
  if ($open.Count -gt 1) { throw '紀錄裡有多於一個已開啟的工作。' }
  if ($open.Count -eq 1) {
    return [ordered]@{
      Next      = $null
      Blocked   = $true
      Reason    = '請先記錄已開啟的工作結果，再開啟下一步。'
      OpenIndex = [int]$open[0].index
    }
  }
  foreach ($job in @($Session.jobs)) {
    if ($job.status -eq 'planned') {
      return [ordered]@{
        Next      = $job
        Blocked   = $false
        Reason    = ''
        OpenIndex = $null
      }
    }
  }
  return [ordered]@{
    Next      = $null
    Blocked   = $false
    Reason    = '佇列已經沒有待執行的工作。'
    OpenIndex = $null
  }
}

function Get-DynamoQueueDispatchPlan {
  param($Session)
  Assert-DynamoSessionManual -Session $Session
  $cursor = Get-DynamoQueueCursor -Session $Session
  if ($cursor.Blocked -or $null -eq $cursor.Next) {
    throw $cursor.Reason
  }
  $job = $cursor.Next
  if ($job.run -and -not $Session.confirmWrite) {
    throw "工具 '$($job.toolId)' 的寫入開關是 true，但任務設定的 confirmWrite 不是 true。預設必須試跑；寫入需要明確確認。"
  }
  $plan = [ordered]@{
    Index        = [int]$job.index
    ToolId       = [string]$job.toolId
    Project      = [string]$Session.hostProject
    Launch       = $true
    ManualMode   = $true
    ExecuteGraph = $false
    Inputs       = (Copy-DynamoValue -Value $job.inputs)
    ArgumentList = @('-ToolId', [string]$job.toolId, '-Project', [string]$Session.hostProject, '-Launch')
  }
  if ($plan.ExecuteGraph -or -not $plan.ManualMode -or -not $plan.Launch) {
    throw '拒絕開啟：佇列只能以手動模式載入圖形。'
  }
  return $plan
}

function Set-DynamoQueueJobOpened {
  param($Session, [int]$Index, [string]$StartedAt)
  Assert-DynamoSessionManual -Session $Session
  $cursor = Get-DynamoQueueCursor -Session $Session
  if ($cursor.Blocked -or $null -eq $cursor.Next -or [int]$cursor.Next.index -ne $Index) {
    throw '只能開啟佇列中下一個待執行的工作。'
  }
  if ([string]::IsNullOrWhiteSpace($StartedAt)) { $StartedAt = Get-DynamoTimestamp }
  Assert-DynamoTimestamp -Text $StartedAt -Label 'startedAt'
  $job = Get-DynamoQueueJob -Session $Session -Index $Index
  $job.status = 'opened-manual'
  $job.startedAt = $StartedAt
  $job.manualMode = $true
  $job.graphExecutedByLauncher = $false
  $Session.updatedAt = $StartedAt
  return $job
}

function Set-DynamoQueueJobResult {
  param(
    $Session,
    [int]$Index,
    [Parameter(Mandatory)][string]$Status,
    $Counts,
    $Errors,
    [string]$EndedAt
  )
  Assert-DynamoSessionManual -Session $Session
  if ($script:DynamoQueueResultStatuses -notcontains $Status) {
    throw "無法記錄狀態 '$Status'。"
  }
  $job = Get-DynamoQueueJob -Session $Session -Index $Index
  if ($job.status -ne 'opened-manual') {
    throw '請先開啟這個工作，再記錄結果。'
  }
  if ($Status -eq 'written' -and (-not $Session.confirmWrite -or -not $job.run)) {
    throw '這個工作不是已確認的寫入，不能記錄成已寫入。'
  }
  $bag = New-DynamoCountBag
  if ($null -ne $Counts) {
    Assert-DynamoObject -Value $Counts -Label '計數'
    foreach ($key in @($Counts.Keys)) {
      if ($script:DynamoQueueCountNames -notcontains [string]$key) {
        throw "未知的計數 '$key'。"
      }
      $value = $Counts[$key]
      if ($null -eq $value -or ($value -is [string] -and [string]::IsNullOrWhiteSpace($value))) {
        continue
      }
      if (-not (Test-DynamoNonNegativeInteger $value)) {
        throw "計數 '$key' 必須是 0 以上的整數。"
      }
      $bag[[string]$key] = (ConvertTo-DynamoInt64 $value)
    }
  }
  $cleaned = New-Object System.Collections.Generic.List[string]
  if ($null -ne $Errors) {
    $incoming = $Errors
    if ($incoming -is [string]) { $incoming = @($incoming) }
    foreach ($item in @($incoming)) {
      if ($null -eq $item) { continue }
      $text = [string]$item
      if ([string]::IsNullOrWhiteSpace($text)) { continue }
      $cleaned.Add($text.Trim())
    }
  }
  if ([string]::IsNullOrWhiteSpace($EndedAt)) { $EndedAt = Get-DynamoTimestamp }
  Assert-DynamoTimestamp -Text $EndedAt -Label 'endedAt'
  $job.status = $Status
  $job.endedAt = $EndedAt
  $job.counts = $bag
  $job.errors = $cleaned.ToArray()
  $job.graphExecutedByLauncher = $false
  $job.manualMode = $true
  $Session.updatedAt = $EndedAt
  return $job
}

function Assert-DynamoTimestamp {
  param([string]$Text, [string]$Label)
  if ($Text -notmatch '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$') {
    throw "$Label 必須是 yyyy-MM-ddTHH:mm:ss。"
  }
}

function Assert-DynamoSessionManual {
  param($Session)
  foreach ($job in @($Session.jobs)) {
    if ($job.Contains('graphExecutedByLauncher') -and $job.graphExecutedByLauncher) {
      throw '拒絕寫入紀錄：啟動器不會執行 Dynamo 圖形。'
    }
    if ($job.Contains('manualMode') -and -not $job.manualMode) {
      throw '拒絕寫入紀錄：圖形必須維持手動模式。'
    }
  }
}

function Move-DynamoQueueEntries {
  param($Entries, [int]$Index, [int]$Offset)
  $list = New-Object System.Collections.ArrayList
  foreach ($entry in @($Entries)) { [void]$list.Add($entry) }
  if ($Index -lt 1 -or $Index -gt $list.Count) { throw "佇列沒有第 $Index 個工作。" }
  $target = $Index + $Offset
  if ($target -lt 1 -or $target -gt $list.Count) { throw '不能把工作移出佇列。' }
  $item = $list[$Index - 1]
  $list.RemoveAt($Index - 1)
  $list.Insert($target - 1, $item)
  $out = New-Object System.Collections.Generic.List[object]
  $number = 1
  foreach ($entry in $list) {
    if ($entry -is [System.Collections.IDictionary]) { $entry.index = $number }
    $out.Add($entry)
    $number++
  }
  $items = $out.ToArray()
  return ,$items
}

function Remove-DynamoQueueEntry {
  param($Entries, [int]$Index)
  $list = New-Object System.Collections.ArrayList
  foreach ($entry in @($Entries)) { [void]$list.Add($entry) }
  if ($Index -lt 1 -or $Index -gt $list.Count) { throw "佇列沒有第 $Index 個工作。" }
  $list.RemoveAt($Index - 1)
  $out = New-Object System.Collections.Generic.List[object]
  $number = 1
  foreach ($entry in $list) {
    if ($entry -is [System.Collections.IDictionary]) { $entry.index = $number }
    $out.Add($entry)
    $number++
  }
  $items = $out.ToArray()
  return ,$items
}

function Format-DynamoInputValue {
  param($Value)
  if ($null -eq $Value) { return '（無）' }
  if ($Value -is [bool]) {
    if ($Value) { return 'True' }
    return 'False'
  }
  if ($Value -is [System.Collections.IEnumerable] -and $Value -isnot [string]) {
    $items = @($Value)
    if ($items.Count -eq 0) { return '（空清單）' }
    return ($items -join ', ')
  }
  return [string]$Value
}

function Format-DynamoJobCard {
  param($Session, $Job, $Catalog)
  $tool = Find-DynamoTool -Catalog $Catalog -ToolId $Job.toolId
  $labels = @{}
  $help = @{}
  if ($null -ne $tool) {
    foreach ($spec in @($tool.Inputs)) {
      $labels[$spec.name] = [string]$spec.label
      $help[$spec.name] = [string]$spec.help
    }
  }
  $lines = New-Object System.Collections.Generic.List[string]
  $lines.Add([string]$Job.toolName)
  $lines.Add('工具：' + [string]$Job.toolId)
  $lines.Add('圖形：' + [string]$Job.dyn)
  $lines.Add('宿主專案：' + [string]$Session.hostProject)
  $lines.Add('')
  $lines.Add('請在 Dynamo 手動填入這些值，然後自己按執行。')
  $lines.Add('啟動器只把圖形開在手動模式。')
  $lines.Add('')
  foreach ($key in @($Job.inputs.Keys)) {
    $label = $key
    if ($labels.ContainsKey([string]$key)) { $label = $labels[[string]$key] }
    $lines.Add('- ' + $label + '：' + (Format-DynamoInputValue $Job.inputs[$key]))
    if ($help.ContainsKey([string]$key) -and -not [string]::IsNullOrWhiteSpace($help[[string]$key])) {
      $lines.Add('  ' + $help[[string]$key])
    }
  }
  $lines.Add('')
  if ($Job.run) {
    $lines.Add('這一步是寫入。你已確認要寫入模型。在 Dynamo 把 Run 改成 True 後再按執行。')
  } else {
    $lines.Add('這一步是試跑。Run 維持 False。')
  }
  return ($lines -join "`r`n") + "`r`n"
}

function Export-DynamoJobCard {
  param($Session, $Job, $Catalog, [Parameter(Mandatory)][string]$OutputDirectory)
  [void][System.IO.Directory]::CreateDirectory($OutputDirectory)
  $text = Format-DynamoJobCard -Session $Session -Job $Job -Catalog $Catalog
  $name = 'job-{0:d2}-card.txt' -f [int]$Job.index
  $path = Join-Path $OutputDirectory $name
  Write-DynamoUtf8Text -Path $path -Text $text
  return $path
}

function ConvertTo-DynamoCsvField {
  param([string]$Text)
  if ($null -eq $Text) { return '' }
  if ($Text.IndexOfAny(@([char]34, [char]44, [char]10, [char]13)) -ge 0) {
    return '"' + ($Text.Replace('"', '""')) + '"'
  }
  return $Text
}

function ConvertTo-DynamoCsv {
  param($Session)
  $header = @(
    'index', 'toolId', 'toolName', 'status', 'startedAt', 'endedAt', 'hostProject',
    'inputFiles', 'run', 'countFiles', 'countChanged', 'countSkipped', 'countFailed',
    'errors', 'graphExecutedByLauncher'
  )
  $lines = New-Object System.Collections.Generic.List[string]
  $lines.Add(($header -join ','))
  foreach ($job in @($Session.jobs)) {
    $files = @($job.inputFiles) -join ' | '
    $errors = @($job.errors) -join ' | '
    $runText = 'false'
    if ($job.run) { $runText = 'true' }
    $executed = 'false'
    if ($job.graphExecutedByLauncher) { $executed = 'true' }
    $row = @(
      [string]$job.index,
      [string]$job.toolId,
      [string]$job.toolName,
      [string]$job.status,
      [string]$job.startedAt,
      [string]$job.endedAt,
      [string]$Session.hostProject,
      $files,
      $runText,
      (Format-DynamoCountCell $job.counts.files),
      (Format-DynamoCountCell $job.counts.changed),
      (Format-DynamoCountCell $job.counts.skipped),
      (Format-DynamoCountCell $job.counts.failed),
      $errors,
      $executed
    )
    $encoded = New-Object System.Collections.Generic.List[string]
    foreach ($cell in $row) { $encoded.Add((ConvertTo-DynamoCsvField $cell)) }
    $lines.Add(($encoded -join ','))
  }
  return ($lines -join "`r`n") + "`r`n"
}

function Format-DynamoCountCell {
  param($Value)
  if ($null -eq $Value) { return '' }
  return [string]$Value
}

function ConvertTo-DynamoMarkdownCell {
  param([string]$Text)
  if ([string]::IsNullOrEmpty($Text)) { return '' }
  return (($Text -replace '\|', '\|') -replace '\r?\n', ' ')
}

function ConvertTo-DynamoHtmlText {
  param([string]$Text)
  if ($null -eq $Text) { return '' }
  return (((($Text -replace '&', '&amp;') -replace '<', '&lt;') -replace '>', '&gt;') -replace '"', '&quot;')
}

function Format-DynamoRunMode {
  param([bool]$Run)
  if ($Run) { return '寫入' }
  return '試跑'
}

function Format-DynamoStatusText {
  param([string]$Status)
  switch ($Status) {
    'planned' { return '待執行' }
    'opened-manual' { return '已開啟（手動）' }
    'dry-run' { return '試跑已記錄' }
    'written' { return '已寫入' }
    'failed' { return '失敗' }
    'skipped' { return '略過' }
    default { return $Status }
  }
}

function Format-DynamoCountText {
  param($Counts)
  $parts = New-Object System.Collections.Generic.List[string]
  foreach ($key in $script:DynamoQueueCountNames) {
    $value = $Counts[$key]
    if ($null -ne $value) { $parts.Add("$key=$value") }
  }
  if ($parts.Count -eq 0) { return '尚未記錄' }
  return ($parts -join ', ')
}

function Format-DynamoErrorText {
  param($Errors)
  $items = @($Errors | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) })
  if ($items.Count -eq 0) { return '無' }
  return ($items -join '；')
}

function New-DynamoRunReportMarkdown {
  param($Session)
  $confirm = '否（預設試跑）'
  if ($Session.confirmWrite) { $confirm = '是' }
  $lines = New-Object System.Collections.Generic.List[string]
  $lines.Add('# BIM 批次修改指令中心 — 執行報告')
  $lines.Add('')
  $lines.Add('啟動器只負責開啟圖形。執行按鈕在 Dynamo 裡，由你按下。計數與錯誤是操作者記錄的結果。')
  $lines.Add('')
  $lines.Add('- 工作階段：' + (ConvertTo-DynamoMarkdownCell $Session.sessionName))
  $lines.Add('- 代號：' + (ConvertTo-DynamoMarkdownCell $Session.sessionId))
  $lines.Add('- 宿主專案：' + (ConvertTo-DynamoMarkdownCell $Session.hostProject))
  $lines.Add('- 允許寫入：' + $confirm)
  $lines.Add('- 建立時間：' + (ConvertTo-DynamoMarkdownCell $Session.createdAt))
  $lines.Add('- 更新時間：' + (ConvertTo-DynamoMarkdownCell $Session.updatedAt))
  $lines.Add('')
  $lines.Add('| # | 工具 | 狀態 | 模式 | 開始 | 結束 | 輸入檔 | 計數 | 錯誤 |')
  $lines.Add('| --- | --- | --- | --- | --- | --- | --- | --- | --- |')
  foreach ($job in @($Session.jobs)) {
    $cells = @(
      [string]$job.index,
      (ConvertTo-DynamoMarkdownCell $job.toolName),
      (ConvertTo-DynamoMarkdownCell (Format-DynamoStatusText $job.status)),
      (Format-DynamoRunMode $job.run),
      (ConvertTo-DynamoMarkdownCell $job.startedAt),
      (ConvertTo-DynamoMarkdownCell $job.endedAt),
      (ConvertTo-DynamoMarkdownCell ((@($job.inputFiles) -join ', '))),
      (ConvertTo-DynamoMarkdownCell (Format-DynamoCountText $job.counts)),
      (ConvertTo-DynamoMarkdownCell (Format-DynamoErrorText $job.errors))
    )
    $lines.Add('| ' + ($cells -join ' | ') + ' |')
  }
  $lines.Add('')
  foreach ($job in @($Session.jobs)) {
    $lines.Add('## ' + $job.index + '. ' + (ConvertTo-DynamoMarkdownCell $job.toolName))
    $lines.Add('')
    $lines.Add('- 工具 id：' + (ConvertTo-DynamoMarkdownCell $job.toolId))
    $lines.Add('- 圖形：' + (ConvertTo-DynamoMarkdownCell $job.dyn))
    $lines.Add('- 狀態：' + (Format-DynamoStatusText $job.status))
    $lines.Add('- 模式：' + (Format-DynamoRunMode $job.run))
    $lines.Add('- 輸入：')
    foreach ($key in @($job.inputs.Keys)) {
      $lines.Add('  - ' + (ConvertTo-DynamoMarkdownCell $key) + '：' + (ConvertTo-DynamoMarkdownCell (Format-DynamoInputValue $job.inputs[$key])))
    }
    $lines.Add('- 計數：' + (Format-DynamoCountText $job.counts))
    $lines.Add('- 錯誤：' + (ConvertTo-DynamoMarkdownCell (Format-DynamoErrorText $job.errors)))
    $lines.Add('')
  }
  return ($lines -join "`r`n") + "`r`n"
}

function New-DynamoRunReportHtml {
  param($Session)
  $confirm = '否（預設試跑）'
  if ($Session.confirmWrite) { $confirm = '是' }
  $sb = New-Object System.Text.StringBuilder
  [void]$sb.AppendLine('<!DOCTYPE html>')
  [void]$sb.AppendLine('<html lang="zh-Hant">')
  [void]$sb.AppendLine('<head>')
  [void]$sb.AppendLine('<meta charset="utf-8">')
  [void]$sb.AppendLine('<title>BIM 批次修改指令中心 — 執行報告</title>')
  [void]$sb.AppendLine('<style>')
  [void]$sb.AppendLine('body{font-family:"Microsoft JhengHei UI","Microsoft JhengHei",sans-serif;margin:24px;color:#1c1917;background:#faf7f2;}')
  [void]$sb.AppendLine('h1{font-size:22px;} table{border-collapse:collapse;width:100%;background:#fff;}')
  [void]$sb.AppendLine('th,td{border:1px solid #d6d3d1;padding:6px 8px;vertical-align:top;text-align:left;}')
  [void]$sb.AppendLine('th{background:#44403c;color:#faf7f2;} .banner{background:#fff7ed;border:1px solid #fdba74;padding:12px 14px;}')
  [void]$sb.AppendLine('</style>')
  [void]$sb.AppendLine('</head>')
  [void]$sb.AppendLine('<body>')
  [void]$sb.AppendLine('<h1>BIM 批次修改指令中心 — 執行報告</h1>')
  [void]$sb.AppendLine('<p class="banner">啟動器只負責開啟圖形。執行按鈕在 Dynamo 裡，由你按下。計數與錯誤是操作者記錄的結果。</p>')
  [void]$sb.AppendLine('<ul>')
  [void]$sb.AppendLine('<li>工作階段：' + (ConvertTo-DynamoHtmlText $Session.sessionName) + '</li>')
  [void]$sb.AppendLine('<li>代號：' + (ConvertTo-DynamoHtmlText $Session.sessionId) + '</li>')
  [void]$sb.AppendLine('<li>宿主專案：' + (ConvertTo-DynamoHtmlText $Session.hostProject) + '</li>')
  [void]$sb.AppendLine('<li>允許寫入：' + $confirm + '</li>')
  [void]$sb.AppendLine('<li>建立時間：' + (ConvertTo-DynamoHtmlText $Session.createdAt) + '</li>')
  [void]$sb.AppendLine('<li>更新時間：' + (ConvertTo-DynamoHtmlText $Session.updatedAt) + '</li>')
  [void]$sb.AppendLine('</ul>')
  [void]$sb.AppendLine('<table>')
  [void]$sb.AppendLine('<thead><tr><th>#</th><th>工具</th><th>狀態</th><th>模式</th><th>開始</th><th>結束</th><th>輸入檔</th><th>計數</th><th>錯誤</th></tr></thead>')
  [void]$sb.AppendLine('<tbody>')
  foreach ($job in @($Session.jobs)) {
    [void]$sb.AppendLine('<tr>')
    [void]$sb.AppendLine('<td>' + $job.index + '</td>')
    [void]$sb.AppendLine('<td>' + (ConvertTo-DynamoHtmlText $job.toolName) + '</td>')
    [void]$sb.AppendLine('<td>' + (ConvertTo-DynamoHtmlText (Format-DynamoStatusText $job.status)) + '</td>')
    [void]$sb.AppendLine('<td>' + (Format-DynamoRunMode $job.run) + '</td>')
    [void]$sb.AppendLine('<td>' + (ConvertTo-DynamoHtmlText $job.startedAt) + '</td>')
    [void]$sb.AppendLine('<td>' + (ConvertTo-DynamoHtmlText $job.endedAt) + '</td>')
    [void]$sb.AppendLine('<td>' + (ConvertTo-DynamoHtmlText ((@($job.inputFiles) -join ', '))) + '</td>')
    [void]$sb.AppendLine('<td>' + (ConvertTo-DynamoHtmlText (Format-DynamoCountText $job.counts)) + '</td>')
    [void]$sb.AppendLine('<td>' + (ConvertTo-DynamoHtmlText (Format-DynamoErrorText $job.errors)) + '</td>')
    [void]$sb.AppendLine('</tr>')
  }
  [void]$sb.AppendLine('</tbody></table>')
  foreach ($job in @($Session.jobs)) {
    [void]$sb.AppendLine('<h2>' + $job.index + '. ' + (ConvertTo-DynamoHtmlText $job.toolName) + '</h2>')
    [void]$sb.AppendLine('<ul>')
    [void]$sb.AppendLine('<li>工具 id：' + (ConvertTo-DynamoHtmlText $job.toolId) + '</li>')
    [void]$sb.AppendLine('<li>圖形：' + (ConvertTo-DynamoHtmlText $job.dyn) + '</li>')
    [void]$sb.AppendLine('<li>狀態：' + (ConvertTo-DynamoHtmlText (Format-DynamoStatusText $job.status)) + '</li>')
    [void]$sb.AppendLine('<li>模式：' + (Format-DynamoRunMode $job.run) + '</li>')
    [void]$sb.AppendLine('<li>輸入：<ul>')
    foreach ($key in @($job.inputs.Keys)) {
      [void]$sb.AppendLine('<li>' + (ConvertTo-DynamoHtmlText $key) + '：' + (ConvertTo-DynamoHtmlText (Format-DynamoInputValue $job.inputs[$key])) + '</li>')
    }
    [void]$sb.AppendLine('</ul></li>')
    [void]$sb.AppendLine('<li>計數：' + (ConvertTo-DynamoHtmlText (Format-DynamoCountText $job.counts)) + '</li>')
    [void]$sb.AppendLine('<li>錯誤：' + (ConvertTo-DynamoHtmlText (Format-DynamoErrorText $job.errors)) + '</li>')
    [void]$sb.AppendLine('</ul>')
  }
  [void]$sb.AppendLine('</body></html>')
  return $sb.ToString()
}

function Export-DynamoQueueSession {
  param($Session, [Parameter(Mandatory)][string]$OutputDirectory, [string]$UpdatedAt)
  Assert-DynamoSessionManual -Session $Session
  if ([string]::IsNullOrWhiteSpace($UpdatedAt)) { $UpdatedAt = Get-DynamoTimestamp }
  Assert-DynamoTimestamp -Text $UpdatedAt -Label 'updatedAt'
  $Session.updatedAt = $UpdatedAt
  [void][System.IO.Directory]::CreateDirectory($OutputDirectory)
  $jsonPath = Join-Path $OutputDirectory 'run-log.json'
  $csvPath = Join-Path $OutputDirectory 'run-log.csv'
  $markdownPath = Join-Path $OutputDirectory 'report.md'
  $htmlPath = Join-Path $OutputDirectory 'report.html'
  Write-DynamoUtf8Text -Path $jsonPath -Text ((ConvertTo-DynamoJson -Value $Session) + "`r`n")
  Write-DynamoUtf8Text -Path $csvPath -Text (ConvertTo-DynamoCsv -Session $Session) -Bom
  Write-DynamoUtf8Text -Path $markdownPath -Text (New-DynamoRunReportMarkdown -Session $Session)
  Write-DynamoUtf8Text -Path $htmlPath -Text (New-DynamoRunReportHtml -Session $Session)
  return [ordered]@{
    Directory = $OutputDirectory
    Json      = $jsonPath
    Csv       = $csvPath
    Markdown  = $markdownPath
    Html      = $htmlPath
  }
}

function Import-DynamoQueueSession {
  param([Parameter(Mandatory)][string]$Path)
  $root = ConvertFrom-DynamoJsonText -Text (Read-DynamoUtf8Text -Path $Path)
  Assert-DynamoObject -Value $root -Label '執行紀錄'
  if (-not (Test-DynamoWholeNumber $root.version) -or [int64]$root.version -ne 1) {
    throw '執行紀錄的版本必須是 1。'
  }
  $jobs = @(Get-DynamoObjectArray -Value $root.jobs -Label '執行紀錄的 jobs')
  $normalized = New-Object System.Collections.Generic.List[object]
  foreach ($job in $jobs) {
    Assert-DynamoObject -Value $job -Label '執行紀錄的工作'
    if ($job.Contains('graphExecutedByLauncher') -and [bool]$job.graphExecutedByLauncher) {
      throw '拒絕寫入紀錄：啟動器不會執行 Dynamo 圖形。'
    }
    if ($job.Contains('manualMode') -and -not [bool]$job.manualMode) {
      throw '拒絕寫入紀錄：圖形必須維持手動模式。'
    }
    $job.manualMode = $true
    $job.graphExecutedByLauncher = $false
    if (-not $job.Contains('errors') -or $null -eq $job.errors) { $job.errors = @() }
    else { $job.errors = @(Get-DynamoObjectArray -Value $job.errors -Label '錯誤') }
    if (-not $job.Contains('inputFiles') -or $null -eq $job.inputFiles) { $job.inputFiles = @() }
    else { $job.inputFiles = @(Get-DynamoObjectArray -Value $job.inputFiles -Label '輸入檔') }
    if (-not $job.Contains('counts') -or $null -eq $job.counts) {
      $job.counts = New-DynamoCountBag
    }
    $normalized.Add($job)
  }
  $root.jobs = $normalized.ToArray()
  Assert-DynamoSessionManual -Session $root
  return $root
}

function Get-DynamoDefaultSessionRoot {
  if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
    throw '找不到 LOCALAPPDATA。請在 Windows 上執行啟動器。'
  }
  return (Join-Path (Join-Path $env:LOCALAPPDATA 'DynamoToolbox') 'sessions')
}
