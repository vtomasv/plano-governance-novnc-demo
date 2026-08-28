$ErrorActionPreference = "Stop"

$RootDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ComposeFile = Join-Path $RootDir "docker-compose.yml"
$ProjectName = if ($env:PLANO_COMPOSE_PROJECT_NAME) { $env:PLANO_COMPOSE_PROJECT_NAME } else { Split-Path $RootDir -Leaf }
Set-Location $RootDir

function Invoke-Compose {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    & docker compose --project-directory $RootDir --project-name $ProjectName -f $ComposeFile @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose falló: $($Arguments -join ' ')"
    }
}

function Read-DotEnv {
    param([string]$Path)
    $values = @{}
    if (-not (Test-Path $Path)) { return $values }
    foreach ($line in Get-Content $Path) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) { continue }
        if ($trimmed -match '^([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
            $value = $Matches[2].Trim()
            if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
                $value = $value.Substring(1, $value.Length - 2)
            }
            $values[$Matches[1]] = $value
        }
    }
    return $values
}

function Get-Setting {
    param([hashtable]$Values, [string]$Name, [string]$Default)
    $processValue = [Environment]::GetEnvironmentVariable($Name, "Process")
    if ($processValue) { return $processValue }
    if ($Values.ContainsKey($Name) -and $Values[$Name]) { return $Values[$Name] }
    return $Default
}

try {
    & docker info *> $null
    if ($LASTEXITCODE -ne 0) { throw "Docker Desktop/Engine no responde." }
} catch {
    throw "Docker Desktop/Engine no responde. Inícielo y vuelva a ejecutar este script."
}

$envFile = Join-Path $RootDir ".env"
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $RootDir ".env.example") $envFile
    Write-Host "Se creó .env desde .env.example"
}
$settings = Read-DotEnv $envFile

if ($env:COMPOSE_FILE) {
    Write-Warning "COMPOSE_FILE=$($env:COMPOSE_FILE) será ignorado; se usará exclusivamente $ComposeFile"
}

Invoke-Compose -Arguments @("config", "--quiet")
Invoke-Compose -Arguments @("up", "--build", "--detach", "--remove-orphans", "--force-recreate")

$checks = @(
    @{ Service = "control-center"; Target = 10000; Host = [int](Get-Setting $settings "CONTROL_CENTER_PORT" "10000") },
    @{ Service = "desktop-chatgpt"; Target = 6080; Host = [int](Get-Setting $settings "CHATGPT_NOVNC_PORT" "6080") },
    @{ Service = "desktop-claude"; Target = 6080; Host = [int](Get-Setting $settings "CLAUDE_NOVNC_PORT" "6081") },
    @{ Service = "desktop-grok"; Target = 6080; Host = [int](Get-Setting $settings "GROK_NOVNC_PORT" "6082") },
    @{ Service = "plano"; Target = 12000; Host = [int](Get-Setting $settings "PLANO_PORT" "12000") },
    @{ Service = "plano"; Target = 8001; Host = [int](Get-Setting $settings "PLANO_AGENT_PORT" "8001") },
    @{ Service = "plano"; Target = 9901; Host = [int](Get-Setting $settings "PLANO_ADMIN_PORT" "19901") },
    @{ Service = "policy-guard"; Target = 10500; Host = [int](Get-Setting $settings "POLICY_GUARD_PORT" "10500") },
    @{ Service = "provider-sim"; Target = 10501; Host = [int](Get-Setting $settings "PROVIDER_SIM_PORT" "10501") },
    @{ Service = "provider-web-sim"; Target = 8443; Host = [int](Get-Setting $settings "PROVIDER_TLS_PORT" "18443") },
    @{ Service = "governed-agent"; Target = 10600; Host = [int](Get-Setting $settings "GOVERNED_AGENT_PORT" "10600") },
    @{ Service = "jaeger"; Target = 16686; Host = [int](Get-Setting $settings "JAEGER_UI_PORT" "16686") },
    @{ Service = "jaeger"; Target = 4317; Host = [int](Get-Setting $settings "OTLP_GRPC_PORT" "4317") },
    @{ Service = "jaeger"; Target = 4318; Host = [int](Get-Setting $settings "OTLP_HTTP_PORT" "4318") },
    @{ Service = "proxy-interceptor"; Target = 8081; Host = [int](Get-Setting $settings "MITMPROXY_UI_PORT" "8081") }
)

$bindingFailures = 0
foreach ($check in $checks) {
    $mapping = (& docker compose --project-directory $RootDir --project-name $ProjectName -f $ComposeFile port $check.Service $check.Target 2>$null | Out-String).Trim()
    if ($mapping -and $mapping.EndsWith(":" + $check.Host)) {
        Write-Host ("OK    {0}:{1} -> {2}" -f $check.Service, $check.Target, $mapping) -ForegroundColor Green
    } else {
        Write-Host ("ERROR {0}:{1}; esperado host :{2}; recibido '{3}'" -f $check.Service, $check.Target, $check.Host, $mapping) -ForegroundColor Red
        $bindingFailures++
    }
}
if ($bindingFailures -gt 0) {
    throw "Docker creó la pila sin $bindingFailures bindings. Ejecute: .\scripts\down.ps1 y luego .\scripts\up.ps1"
}

$bindAddress = Get-Setting $settings "BIND_ADDRESS" "127.0.0.1"
$accessHost = if ($bindAddress -eq "0.0.0.0") { "127.0.0.1" } else { $bindAddress }
$urls = @(
    "http://${accessHost}:$(Get-Setting $settings 'CONTROL_CENTER_PORT' '10000')/health",
    "http://${accessHost}:$(Get-Setting $settings 'PLANO_PORT' '12000')/healthz",
    "http://${accessHost}:$(Get-Setting $settings 'PLANO_ADMIN_PORT' '19901')/ready",
    "http://${accessHost}:$(Get-Setting $settings 'CHATGPT_NOVNC_PORT' '6080')/vnc.html",
    "http://${accessHost}:$(Get-Setting $settings 'CLAUDE_NOVNC_PORT' '6081')/vnc.html",
    "http://${accessHost}:$(Get-Setting $settings 'GROK_NOVNC_PORT' '6082')/vnc.html"
)
foreach ($url in $urls) {
    $ready = $false
    for ($attempt = 1; $attempt -le 90; $attempt++) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 5
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400) { $ready = $true; break }
        } catch { Start-Sleep -Seconds 2 }
    }
    if (-not $ready) { throw "Servicio no disponible: $url" }
}

$controlPort = Get-Setting $settings "CONTROL_CENTER_PORT" "10000"
$chatgptPort = Get-Setting $settings "CHATGPT_NOVNC_PORT" "6080"
$claudePort = Get-Setting $settings "CLAUDE_NOVNC_PORT" "6081"
$grokPort = Get-Setting $settings "GROK_NOVNC_PORT" "6082"
$vncPassword = Get-Setting $settings "VNC_PASSWORD" "plano-demo"
$mitmPassword = Get-Setting $settings "MITMWEB_PASSWORD" "plano-demo"

Write-Host ""
Write-Host "Demo operativa:" -ForegroundColor Cyan
Write-Host "  Control Center: http://${accessHost}:${controlPort}/"
Write-Host "  ChatGPT noVNC: http://${accessHost}:${chatgptPort}/vnc.html?autoconnect=1&resize=remote"
Write-Host "  Claude noVNC:  http://${accessHost}:${claudePort}/vnc.html?autoconnect=1&resize=remote"
Write-Host "  Grok noVNC:    http://${accessHost}:${grokPort}/vnc.html?autoconnect=1&resize=remote"
Write-Host "  Contraseña noVNC: $vncPassword"
Write-Host "  Contraseña mitmweb: $mitmPassword"
