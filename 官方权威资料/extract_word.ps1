# Read-only conversion of official legacy Word attachments to UTF-8 text.
# Word runs hidden, macros disabled; original files are never edited.
param([switch]$OnlyMissing)
$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
$taskWord = New-Object -ComObject Word.Application
$taskWord.Visible = $false
$taskWord.DisplayAlerts = 0
$taskWord.AutomationSecurity = 3
try {
    New-Item -ItemType Directory -Path (Join-Path $taskRoot 'text') -Force | Out-Null
    $taskFiles = Get-ChildItem -LiteralPath (Join-Path $taskRoot 'originals') -File | Where-Object { $_.Extension -in '.doc','.docx' }
    foreach ($taskFile in $taskFiles) {
        if ($OnlyMissing -and (Test-Path -LiteralPath (Join-Path $taskRoot ('text\' + $taskFile.BaseName + '.txt'))) -and (Test-Path -LiteralPath (Join-Path $taskRoot ('text\' + $taskFile.BaseName + '.tables.json')))) { continue }
        $taskDocument = $null
        try {
            $taskDocument = $taskWord.Documents.Open($taskFile.FullName, $false, $true)
            $taskContent = $taskDocument.Content.Text
            $taskContent = ($taskContent -split '[\r\n\x07]' | Where-Object { $_.Trim() } | ForEach-Object { $_.TrimEnd() }) -join "`n"
            [IO.File]::WriteAllText((Join-Path $taskRoot ('text\' + $taskFile.BaseName + '.txt')), $taskContent + "`n", [Text.UTF8Encoding]::new($false))
            $taskTables = @()
            $taskTableNumber = 0
            foreach ($taskTable in $taskDocument.Tables) {
                $taskTableNumber++
                $taskCells = @()
                foreach ($taskCell in $taskTable.Range.Cells) {
                    $taskCellText = ($taskCell.Range.Text -replace '[\r\x07]+$', '').Trim()
                    $taskCells += [PSCustomObject]@{ row = $taskCell.RowIndex; column = $taskCell.ColumnIndex; text = $taskCellText }
                }
                $taskTables += [PSCustomObject]@{ table = $taskTableNumber; cells = $taskCells }
            }
            [IO.File]::WriteAllText((Join-Path $taskRoot ('text\' + $taskFile.BaseName + '.tables.json')), (ConvertTo-Json -InputObject @($taskTables) -Depth 8), [Text.UTF8Encoding]::new($false))
            Write-Output ($taskFile.BaseName + ' ' + $taskContent.Length)
        } finally {
            if ($null -ne $taskDocument) { $taskDocument.Close(0); [void][Runtime.InteropServices.Marshal]::ReleaseComObject($taskDocument) }
        }
    }
} finally {
    $taskWord.Quit()
    [void][Runtime.InteropServices.Marshal]::ReleaseComObject($taskWord)
}
