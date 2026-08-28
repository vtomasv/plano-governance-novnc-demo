$ErrorActionPreference = "Stop"

$RootDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ComposeFile = Join-Path $RootDir "docker-compose.yml"
$ProjectName = if ($env:PLANO_COMPOSE_PROJECT_NAME) { $env:PLANO_COMPOSE_PROJECT_NAME } else { Split-Path $RootDir -Leaf }
Set-Location $RootDir

& docker info *> $null
if ($LASTEXITCODE -ne 0) { throw "Docker Desktop/Engine no responde." }

Write-Host "`n=== Compose efectivo ===" -ForegroundColor Cyan
Write-Host "Archivo forzado: $ComposeFile"
if ($env:COMPOSE_FILE) { Write-Warning "COMPOSE_FILE=$($env:COMPOSE_FILE) existe, pero estos scripts lo ignoran." }
& docker compose --project-directory $RootDir --project-name $ProjectName -f $ComposeFile config --quiet
if ($LASTEXITCODE -ne 0) { throw "El Compose principal no es válido." }

Write-Host "`n=== Contenedores ===" -ForegroundColor Cyan
& docker compose --project-directory $RootDir --project-name $ProjectName -f $ComposeFile ps -a

$checks = @(
    @{ Service = "control-center"; Target = 10000 },
    @{ Service = "desktop-chatgpt"; Target = 6080 },
    @{ Service = "desktop-claude"; Target = 6080 },
    @{ Service = "desktop-grok"; Target = 6080 },
    @{ Service = "plano"; Target = 12000 },
    @{ Service = "plano"; Target = 8001 },
    @{ Service = "plano"; Target = 9901 },
    @{ Service = "policy-guard"; Target = 10500 },
    @{ Service = "provider-sim"; Target = 10501 },
    @{ Service = "provider-web-sim"; Target = 8443 },
    @{ Service = "governed-agent"; Target = 10600 },
    @{ Service = "jaeger"; Target = 16686 },
    @{ Service = "jaeger"; Target = 4317 },
    @{ Service = "jaeger"; Target = 4318 },
    @{ Service = "proxy-interceptor"; Target = 8081 }
)

Write-Host "`n=== Bindings reales ===" -ForegroundColor Cyan
$missing = 0
foreach ($check in $checks) {
    $mapping = (& docker compose --project-directory $RootDir --project-name $ProjectName -f $ComposeFile port $check.Service $check.Target 2>$null | Out-String).Trim()
    if ($mapping) {
        Write-Host ("OK    {0}:{1} -> {2}" -f $check.Service, $check.Target, $mapping) -ForegroundColor Green
    } else {
        Write-Host ("FALTA {0}:{1}" -f $check.Service, $check.Target) -ForegroundColor Red
        $missing++
    }
}

$planoId = (& docker compose --project-directory $RootDir --project-name $ProjectName -f $ComposeFile ps -q plano 2>$null | Out-String).Trim()
if ($planoId) {
    Write-Host "`n=== Origen registrado por Docker ===" -ForegroundColor Cyan
    & docker inspect $planoId --format 'project={{index .Config.Labels "com.docker.compose.project"}} files={{index .Config.Labels "com.docker.compose.project.config_files"}} working_dir={{index .Config.Labels "com.docker.compose.project.working_dir"}}'
}

if ($missing -gt 0) {
    Write-Host "`nDocker creó la pila con $missing bindings ausentes." -ForegroundColor Red
    Write-Host "Recuperación: .\scripts\down.ps1 ; .\scripts\up.ps1"
    exit 1
}

Write-Host "`nTodos los bindings están publicados." -ForegroundColor Green
Write-Host "Control Center: http://127.0.0.1:10000/"
Write-Host "ChatGPT noVNC: http://127.0.0.1:6080/vnc.html?autoconnect=1&resize=remote"
Write-Host "Claude noVNC:  http://127.0.0.1:6081/vnc.html?autoconnect=1&resize=remote"
Write-Host "Grok noVNC:    http://127.0.0.1:6082/vnc.html?autoconnect=1&resize=remote"
