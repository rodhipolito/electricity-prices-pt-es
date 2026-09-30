# Carrega as variaveis de dbt\.env para a sessao atual do PowerShell
$envFile = Join-Path $PSScriptRoot ".env"

if (-not (Test-Path $envFile)) {
    Write-Error "Ficheiro .env nao encontrado em $envFile"
    return
}

Get-Content $envFile | ForEach-Object {
    $line = $_.Trim()
    if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
        $name, $value = $line.Split("=", 2)
        Set-Item -Path "env:$($name.Trim())" -Value $value.Trim()
    }
}

Write-Output "Variaveis DBT_PG_* carregadas (host: $env:DBT_PG_HOST, schema: $env:DBT_PG_SCHEMA)"
