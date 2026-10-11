param([int]$Port = 8000, [switch]$Install)
$ErrorActionPreference = 'Stop'
$workspacePath = [System.IO.Path]::GetFullPath($PSScriptRoot)
Set-Location -LiteralPath $workspacePath
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw '请先安装 Python 3.11 或更高版本。' }
if ($Install) {
    & python -m pip install -r (Join-Path $workspacePath 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw '依赖安装失败，请检查 pip 输出。' }
}
& python -c 'import fastapi, pydantic, uvicorn, jsonschema, networkx'
if ($LASTEXITCODE -ne 0) { throw '依赖缺失。运行：python -m pip install -r requirements.txt' }
foreach ($pair in @(@('权威资料','官方权威资料'), @('教资','教资原始资料'))) {
    $aliasPath = Join-Path $workspacePath $pair[0]
    $sourcePath = Join-Path $workspacePath $pair[1]
    if (-not (Test-Path -LiteralPath $aliasPath)) {
        if (-not (Test-Path -LiteralPath $sourcePath -PathType Container)) { throw "资料目录缺失：$sourcePath" }
        New-Item -ItemType Junction -Path $aliasPath -Target $sourcePath | Out-Null
    }
}
Write-Host "知序网页：http://127.0.0.1:$Port"
Write-Host '在网页的“模型与设置”填写 DeepSeek API Key。Ctrl+C 停止服务。'
& python -m uvicorn services.app:app --host 127.0.0.1 --port $Port
if ($LASTEXITCODE -ne 0) { throw '服务未能启动，请检查端口是否占用。' }
