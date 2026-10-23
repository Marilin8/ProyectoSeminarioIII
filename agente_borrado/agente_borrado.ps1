# Agente de borrado - Clinica de Imagenes
#
# Revisa las carpetas configuradas (p. ej. la de RadiAnt), calcula el SHA-256 de
# cada archivo y le pregunta al sistema cuales ya estan guardados. SOLO borra
# (o manda a la Papelera) los que el sistema confirma. Si el sistema no responde,
# no borra nada.
#
# Uso:  powershell -NoProfile -ExecutionPolicy Bypass -File agente_borrado.ps1 [-Config ruta.json] [-Simular]
#   -Simular  muestra que borraria, sin borrar nada (para probar la configuracion).
#
# Pensado para correr cada pocos minutos como tarea programada (ver LEEME.md).
# Solo usa lo que trae Windows (PowerShell 5.1): no hace falta instalar nada.

param(
    [string]$Config = (Join-Path $PSScriptRoot 'agente.json'),
    [switch]$Simular
)

$ErrorActionPreference = 'Stop'
$IgnorarNombres = @('desktop.ini', 'thumbs.db', '.ds_store')
$LoteMaximo = 500

function Escribir-Log([string]$texto) {
    $linea = '{0}  {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $texto
    Add-Content -Path $script:ArchivoLog -Value $linea -Encoding UTF8
    Write-Output $linea
}

function Leer-Json([string]$ruta) {
    if (-not (Test-Path -LiteralPath $ruta)) { return $null }
    $texto = [System.IO.File]::ReadAllText($ruta, [System.Text.Encoding]::UTF8)
    if (-not $texto.Trim()) { return $null }
    return $texto | ConvertFrom-Json
}

function Huella([string]$ruta) {
    return (Get-FileHash -LiteralPath $ruta -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Confirmar-Huellas([string[]]$huellas) {
    $url = $script:Cfg.url_sistema.TrimEnd('/') + '/api/agente/huellas/'
    $cuerpo = @{ huellas = @($huellas) } | ConvertTo-Json -Compress
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($cuerpo)
    $respuesta = Invoke-RestMethod -Uri $url -Method Post -Body $bytes `
        -ContentType 'application/json; charset=utf-8' `
        -Headers @{ Authorization = 'Bearer ' + $script:Cfg.token } -TimeoutSec 60 -UseBasicParsing
    return @($respuesta.confirmadas)
}

function Borrar([string]$ruta) {
    if ($script:Cfg.modo -eq 'borrar') {
        Remove-Item -LiteralPath $ruta -Force
    } else {
        [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile(
            $ruta, 'OnlyErrorDialogs', 'SendToRecycleBin')
    }
}

# ------------------------------------------------------------------ configuracion
$script:Cfg = Leer-Json $Config
if ($null -eq $script:Cfg) { throw "No se encontro la configuracion: $Config" }
if (-not $script:Cfg.url_sistema -or -not $script:Cfg.token) { throw 'Faltan url_sistema o token en la configuracion.' }
if (-not $script:Cfg.modo) { $script:Cfg | Add-Member modo 'papelera' }
if ($script:Cfg.modo -notin @('papelera', 'borrar')) { throw 'modo debe ser "papelera" o "borrar".' }
$minutosQuietos = if ($null -ne $script:Cfg.minutos_sin_cambios) { [double]$script:Cfg.minutos_sin_cambios } else { 5 }
$script:ArchivoLog = if ($script:Cfg.archivo_log) { $script:Cfg.archivo_log } else { Join-Path $PSScriptRoot 'agente_borrado.log' }
$archivoCache = Join-Path $PSScriptRoot 'cache_huellas.json'

Add-Type -AssemblyName Microsoft.VisualBasic
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# Evita dos ejecuciones a la vez (si una tanda tarda mas que el intervalo).
$candado = New-Object System.Threading.Mutex($false, 'Local\ClinicaAgenteBorrado')
if (-not $candado.WaitOne(0)) { exit 0 }

try {
    # Cache de huellas: no recalcular el SHA-256 de archivos que no cambiaron.
    $cache = @{}
    $previo = Leer-Json $archivoCache
    if ($null -ne $previo) { $previo.PSObject.Properties | ForEach-Object { $cache[$_.Name] = $_.Value } }

    $limite = (Get-Date).AddMinutes(-$minutosQuietos)
    $candidatos = @{}   # huella -> lista de rutas
    $vigentes = @{}
    foreach ($carpeta in @($script:Cfg.carpetas)) {
        if (-not (Test-Path -LiteralPath $carpeta)) { Escribir-Log "AVISO: no existe la carpeta $carpeta"; continue }
        Get-ChildItem -LiteralPath $carpeta -Recurse -File -Force -ErrorAction SilentlyContinue | ForEach-Object {
            $f = $_
            if ($IgnorarNombres -contains $f.Name.ToLowerInvariant()) { return }
            if ($f.LastWriteTime -gt $limite) { return }   # todavia se esta copiando / recien llegado
            $clave = '{0}|{1}|{2}' -f $f.FullName, $f.Length, $f.LastWriteTimeUtc.Ticks
            try {
                $h = if ($cache.ContainsKey($clave)) { $cache[$clave] } else { Huella $f.FullName }
            } catch { Escribir-Log "AVISO: no se pudo leer $($f.FullName)"; return }
            $vigentes[$clave] = $h
            if (-not $candidatos.ContainsKey($h)) { $candidatos[$h] = New-Object System.Collections.ArrayList }
            [void]$candidatos[$h].Add($f.FullName)
        }
    }

    $huellas = @($candidatos.Keys)
    $confirmadas = New-Object System.Collections.Generic.HashSet[string]
    for ($i = 0; $i -lt $huellas.Count; $i += $LoteMaximo) {
        $lote = $huellas[$i..([Math]::Min($i + $LoteMaximo, $huellas.Count) - 1)]
        foreach ($c in (Confirmar-Huellas $lote)) { [void]$confirmadas.Add([string]$c) }
    }

    $borrados = 0
    foreach ($h in $confirmadas) {
        foreach ($ruta in $candidatos[$h]) {
            if ($Simular) { Escribir-Log "SIMULACION: borraria $ruta"; continue }
            try { Borrar $ruta; $borrados++; Escribir-Log "Borrado ($($script:Cfg.modo)): $ruta" }
            catch { Escribir-Log "ERROR al borrar ${ruta}: $($_.Exception.Message)" }
        }
    }

    # Carpetas que quedaron vacias (nunca la carpeta configurada en si).
    if (-not $Simular -and $script:Cfg.borrar_carpetas_vacias -ne $false) {
        foreach ($carpeta in @($script:Cfg.carpetas)) {
            if (-not (Test-Path -LiteralPath $carpeta)) { continue }
            Get-ChildItem -LiteralPath $carpeta -Recurse -Directory -Force -ErrorAction SilentlyContinue |
                Sort-Object { $_.FullName.Length } -Descending | ForEach-Object {
                    if (-not (Get-ChildItem -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue)) {
                        Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue
                    }
                }
        }
    }

    # Guardar solo las huellas de archivos que siguen existiendo.
    $vigentes | ConvertTo-Json -Compress | Set-Content -LiteralPath $archivoCache -Encoding UTF8
    if ($huellas.Count -gt 0 -or $borrados -gt 0) {
        Escribir-Log ("Revisados {0} archivos distintos, confirmados {1}, borrados {2}." -f $huellas.Count, $confirmadas.Count, $borrados)
    }
} catch {
    Escribir-Log "ERROR: $($_.Exception.Message) (no se borro nada en esta pasada)"
    exit 1
} finally {
    $candado.ReleaseMutex()
}
