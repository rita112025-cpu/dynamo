#Requires -Version 5.1
BeforeAll {
  . (Join-Path $PSScriptRoot 'Invoke-QueueTests.ps1')
}

Describe 'Dynamo batch queue' {
  It 'parses task config, keeps queue order, and writes the run log' {
    Invoke-DynamoQueueTestSuite
  }
}
