# Arma instaladores\Instalador_AgenteBorrado.zip con:
#   Instalar.bat, Desinstalar.bat, instalar.ps1, desinstalar.ps1 (de instaladores\agente_borrado\)
#   agente_borrado.ps1 y LEEME.md (de agente_borrado\, la version actual del proyecto)
# Volver a correrlo cada vez que cambie el agente:
#   powershell -NoProfile -ExecutionPolicy Bypass -File instaladores\construir.ps1

$ErrorActionPreference = 'Stop'
$aqui = $PSScriptRoot
$proyecto = Split-Path $aqui -Parent
$temporal = Join-Path ([System.IO.Path]::GetTempPath()) ('agente_zip_' + [guid]::NewGuid().ToString('N'))
$paquete = Join-Path $temporal 'AgenteBorrado'
New-Item -ItemType Directory -Force -Path $paquete | Out-Null
try {
    Copy-Item (Join-Path $aqui 'agente_borrado\*') $paquete
    Copy-Item (Join-Path $proyecto 'agente_borrado\agente_borrado.ps1') $paquete
    Copy-Item (Join-Path $proyecto 'agente_borrado\LEEME.md') $paquete
    $zip = Join-Path $aqui 'Instalador_AgenteBorrado.zip'
    if (Test-Path $zip) { Remove-Item $zip -Force }
    Compress-Archive -Path $paquete -DestinationPath $zip
    Write-Host "Creado: $zip"
    Get-ChildItem $paquete | ForEach-Object { Write-Host "  $($_.Name)" }
} finally {
    Remove-Item $temporal -Recurse -Force -ErrorAction SilentlyContinue
}
