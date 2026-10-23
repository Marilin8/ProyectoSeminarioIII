# Desinstalador del agente de borrado - Clinica de Imagenes
# Quita la tarea programada y la carpeta del agente (incluido el token de esta PC).
# No toca los estudios ni la Papelera.

param(
    [string]$Destino = (Join-Path $env:LOCALAPPDATA 'ClinicaAgente'),
    [switch]$Silencioso
)

$NombreTarea = 'ClinicaAgenteBorrado'

& schtasks.exe /Query /TN $NombreTarea 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) {
    & schtasks.exe /Delete /TN $NombreTarea /F | Out-Null
    Write-Host "Tarea '$NombreTarea' eliminada."
} else {
    Write-Host "No habia tarea '$NombreTarea'."
}

if (Test-Path -LiteralPath $Destino) {
    $ok = $Silencioso
    if (-not $ok) { $ok = (Read-Host "Borrar la carpeta $Destino (configuracion, token y log)? [s/N]") -match '^[sS]' }
    if ($ok) {
        # Si se ejecuta desde la propia carpeta, se borra el resto y el archivo queda para el final.
        Get-ChildItem -LiteralPath $Destino -Force | Where-Object { $_.FullName -ne $PSCommandPath } |
            Remove-Item -Recurse -Force
        if ($PSCommandPath -notlike "$Destino*") { Remove-Item -LiteralPath $Destino -Recurse -Force }
        Write-Host 'Carpeta del agente borrada.'
    }
}
Write-Host 'Recuerde revocar el token de esta PC en el servidor: manage.py token_agente revocar "<nombre>".'
