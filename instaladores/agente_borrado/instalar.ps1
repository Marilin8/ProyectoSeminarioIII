# Instalador del agente de borrado - Clinica de Imagenes
#
# Copia el agente a %LOCALAPPDATA%\ClinicaAgente (no requiere administrador),
# crea agente.json con el token de esta PC y la carpeta de RadiAnt, hace una
# prueba en modo simulacion y programa la tarea "ClinicaAgenteBorrado" cada
# 5 minutos para el usuario actual (corre oculta, sin ventanas).
#
# Normalmente se abre con doble clic en Instalar.bat. Tambien acepta parametros
# para instalarlo sin preguntas:
#   instalar.ps1 -Token XXX [-Carpeta ruta] [-Modo papelera|borrar] [-Url https://...]
#                [-Destino ruta] [-SinTarea] [-Silencioso]

param(
    [string]$Token,
    [string]$Carpeta,
    [ValidateSet('papelera', 'borrar')][string]$Modo = 'papelera',
    [string]$Url = 'https://clinica.cimeimagenes.com',
    [string]$Destino = (Join-Path $env:LOCALAPPDATA 'ClinicaAgente'),
    [switch]$SinTarea,
    [switch]$Silencioso
)

$ErrorActionPreference = 'Stop'
$NombreTarea = 'ClinicaAgenteBorrado'
$Origen = $PSScriptRoot
trap {
    Write-Host ''
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host 'La instalacion no se completo.' -ForegroundColor Red
    exit 1
}

function Titulo([string]$t) { Write-Host ''; Write-Host "== $t ==" -ForegroundColor Cyan }
function Preguntar([string]$texto, [string]$porDefecto) {
    if ($Silencioso) { return $porDefecto }
    $sufijo = if ($porDefecto) { " [$porDefecto]" } else { '' }
    $r = Read-Host "$texto$sufijo"
    if ([string]::IsNullOrWhiteSpace($r)) { return $porDefecto } else { return $r.Trim().Trim('"') }
}

function Buscar-CarpetaRadiAnt {
    # Ubicacion habitual de la base local de RadiAnt (archivos importados con "Copy files").
    $candidatas = @(
        (Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'RadiAntDB\RadiAnt.rdvdata\storage'),
        (Join-Path $env:USERPROFILE 'Documents\RadiAntDB\RadiAnt.rdvdata\storage')
    )
    foreach ($c in $candidatas) { if (Test-Path -LiteralPath $c) { return $c } }
    return ''
}

Titulo 'Agente de borrado - Clinica de Imagenes'
Write-Host 'Borra de esta PC (a la Papelera) los estudios que el sistema confirma que ya'
Write-Host 'recibio. Lo que no se subio, o se subio distinto, no se toca.'

if (-not (Test-Path -LiteralPath (Join-Path $Origen 'agente_borrado.ps1'))) {
    throw "No se encontro agente_borrado.ps1 junto al instalador ($Origen)."
}

# --- Token
Titulo '1. Token de esta PC'
if (-not $Token) {
    Write-Host 'Pidaselo al administrador del sistema (manage.py token_agente crear "<nombre de la PC>").'
    $seguro = Read-Host 'Pegue el token (no se muestra en pantalla)' -AsSecureString
    $Token = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($seguro)).Trim()
}
if ($Token.Length -lt 20) { throw 'El token es demasiado corto: revise que lo haya copiado completo.' }

# --- Carpeta
Titulo '2. Carpeta donde RadiAnt guarda los estudios'
if (-not $Carpeta) {
    $detectada = Buscar-CarpetaRadiAnt
    if ($detectada) { Write-Host "Se encontro la base de RadiAnt en: $detectada" }
    else { Write-Host 'No se encontro la base de RadiAnt en la ubicacion habitual.' }
    $Carpeta = Preguntar 'Carpeta a vigilar (Enter para aceptar)' $detectada
}
if (-not $Carpeta -or -not (Test-Path -LiteralPath $Carpeta)) { throw "La carpeta no existe: '$Carpeta'" }
$Carpeta = (Resolve-Path -LiteralPath $Carpeta).Path
$raiz = [System.IO.Path]::GetPathRoot($Carpeta).TrimEnd('\')
$prohibidas = @($raiz, $env:USERPROFILE, [Environment]::GetFolderPath('MyDocuments'),
                [Environment]::GetFolderPath('Desktop'), $env:WINDIR, $env:ProgramFiles) |
    ForEach-Object { if ($_) { $_.TrimEnd('\') } }
if ($prohibidas -contains $Carpeta.TrimEnd('\')) {
    throw "Por seguridad no se puede vigilar '$Carpeta' completa: elija la carpeta de estudios de RadiAnt."
}

# --- Copiar y configurar
Titulo '3. Instalando'
New-Item -ItemType Directory -Force -Path $Destino | Out-Null
Copy-Item -LiteralPath (Join-Path $Origen 'agente_borrado.ps1') -Destination $Destino -Force
Copy-Item -LiteralPath (Join-Path $Origen 'desinstalar.ps1') -Destination $Destino -Force -ErrorAction SilentlyContinue
$config = [ordered]@{
    url_sistema = $Url.TrimEnd('/')
    token = $Token
    carpetas = @($Carpeta)
    modo = $Modo
    minutos_sin_cambios = 5
    borrar_carpetas_vacias = $true
}
$rutaConfig = Join-Path $Destino 'agente.json'
[System.IO.File]::WriteAllText($rutaConfig, ($config | ConvertTo-Json), (New-Object System.Text.UTF8Encoding($false)))

# Lanzador oculto: la tarea programada usa wscript para no abrir una consola cada 5 minutos.
$vbs = @"
CreateObject("WScript.Shell").Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""$Destino\agente_borrado.ps1""", 0, False
"@
Set-Content -LiteralPath (Join-Path $Destino 'ejecutar_oculto.vbs') -Value $vbs -Encoding ASCII
Write-Host "Agente copiado a $Destino"

# --- Prueba
Titulo '4. Prueba (simulacion, no borra nada)'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Destino 'agente_borrado.ps1') -Simular
$codigo = $LASTEXITCODE
if ($codigo -ne 0) {
    Write-Host ''
    Write-Host 'La prueba fallo: revise el token, la conexion a internet y el archivo agente_borrado.log.' -ForegroundColor Red
    Write-Host "Log: $(Join-Path $Destino 'agente_borrado.log')"
    throw 'No se programo la tarea porque la prueba no paso.'
}
Write-Host 'Conexion con el sistema OK.' -ForegroundColor Green

# --- Tarea programada
if (-not $SinTarea) {
    Titulo '5. Tarea programada'
    $accion = "wscript.exe `"$Destino\ejecutar_oculto.vbs`""
    & schtasks.exe /Create /TN $NombreTarea /SC MINUTE /MO 5 /TR $accion /F | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear la tarea programada.' }
    Write-Host "Tarea '$NombreTarea' creada: corre cada 5 minutos mientras este usuario tenga la sesion iniciada."
}

Titulo 'Listo'
Write-Host "Modo: $Modo   Carpeta: $Carpeta"
Write-Host "Registro de lo que hace: $(Join-Path $Destino 'agente_borrado.log')"
Write-Host 'Para quitarlo: Desinstalar.bat (o desinstalar.ps1 en la carpeta del agente).'
