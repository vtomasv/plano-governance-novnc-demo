param(
    [switch]$Purge
)

$ErrorActionPreference = "Stop"
$RootDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ComposeFile = Join-Path $RootDir "docker-compose.yml"
$ProjectName = if ($env:PLANO_COMPOSE_PROJECT_NAME) { $env:PLANO_COMPOSE_PROJECT_NAME } else { Split-Path $RootDir -Leaf }
Set-Location $RootDir

& docker info *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Docker Desktop/Engine no responde. Inícielo y vuelva a ejecutar este script."
}

$args = @("compose", "--project-directory", $RootDir, "--project-name", $ProjectName, "-f", $ComposeFile, "down", "--remove-orphans")
if ($Purge) { $args += "--volumes" }

& docker @args
if ($LASTEXITCODE -ne 0) { throw "No fue posible detener la pila." }

if ($Purge) {
    Write-Host "Pila detenida y volúmenes eliminados."
} else {
    Write-Host "Pila detenida; perfiles y CA conservados en volúmenes Docker."
}
