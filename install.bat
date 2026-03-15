@echo off
cd /d "%~dp0"
setlocal EnableDelayedExpansion
chcp 65001 >nul 2>&1

:: =============================================================================
:: Azure Boards Manager - Instalador
:: =============================================================================
:: Este script instala todo lo necesario para ejecutar el proyecto.
:: Solo necesitas tener conexion a internet.
::
:: Pasos:
::   1. Instala uv (gestor de Python) si no esta presente
::   2. Instala Python 3.14 si no esta presente
::   3. Comprueba que el fichero .env existe y esta configurado
::   4. Crea el entorno virtual del proyecto
::   5. Instala todas las dependencias
:: =============================================================================

set PYTHON_VERSION=3.14

set "OK=   [OK]"
set "INFO= [INFO]"
set "WARN= [AVISO]"
set "ERR=  [ERROR]"
set "STEP= --"

set ERRORES=0

call :imprimir_cabecera


:: -----------------------------------------------------------------------------
:: PASO 1 - Comprobar e instalar uv
:: -----------------------------------------------------------------------------
echo.
echo %STEP% Paso 1/5 - Comprobando gestor de instalacion ^(uv^)...
echo.

where uv >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    for /f "tokens=*" %%v in ('uv --version 2^>nul') do set UV_VERSION=%%v
    echo %OK% uv ya esta instalado: !UV_VERSION!
) else (
    echo %INFO% uv no encontrado. Instalando automaticamente...
    echo %INFO% Descargando desde https://astral.sh/uv ...
    echo.

    powershell -ExecutionPolicy Bypass -Command ^
        "irm https://astral.sh/uv/install.ps1 | iex"

    if !ERRORLEVEL! NEQ 0 (
        echo.
        echo %ERR% No se pudo instalar uv automaticamente.
        echo.
        echo       Solucion manual:
        echo       1. Abre PowerShell como administrador
        echo       2. Ejecuta: irm https://astral.sh/uv/install.ps1 ^| iex
        echo       3. Cierra esta ventana y vuelve a ejecutar instalar.bat
        echo.
        set /a ERRORES+=1
        goto :resumen_final
    )

    call :recargar_path

    where uv >nul 2>&1
    if !ERRORLEVEL! NEQ 0 (
        echo %WARN% uv instalado pero no reconocido en esta sesion.
        echo %INFO% Cierra esta ventana, abrela de nuevo y ejecuta instalar.bat.
        set /a ERRORES+=1
        goto :resumen_final
    )

    echo %OK% uv instalado correctamente.
)


:: -----------------------------------------------------------------------------
:: PASO 2 - Instalar Python 3.14
:: -----------------------------------------------------------------------------
echo.
echo %STEP% Paso 2/5 - Comprobando Python %PYTHON_VERSION%...
echo.

uv python find %PYTHON_VERSION% >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    for /f "tokens=*" %%v in ('uv run python --version 2^>nul') do set PY_VERSION=%%v
    echo %OK% Python ya disponible: !PY_VERSION!
) else (
    echo %INFO% Python %PYTHON_VERSION% no encontrado. Instalando...
    echo %INFO% Esto puede tardar unos minutos.
    echo.

    uv python install %PYTHON_VERSION%

    if !ERRORLEVEL! NEQ 0 (
        echo.
        echo %ERR% No se pudo instalar Python %PYTHON_VERSION%.
        echo.
        echo       Posibles causas:
        echo       - Sin conexion a internet
        echo       - Servidor de descarga no disponible temporalmente
        echo.
        echo       Solucion: espera unos minutos y vuelve a ejecutar instalar.bat
        echo.
        set /a ERRORES+=1
        goto :resumen_final
    )

    echo %OK% Python %PYTHON_VERSION% instalado correctamente.
)


:: -----------------------------------------------------------------------------
:: PASO 3 - Verificar que existe el fichero .env
:: -----------------------------------------------------------------------------
echo.
echo %STEP% Paso 3/5 - Comprobando fichero de configuracion ^(.env^)...
echo.

if exist ".env" (
    findstr /i "AZURE_DEVOPS_ORG_URL=$" .env >nul 2>&1
    if !ERRORLEVEL! EQU 0 (
        echo %WARN% El fichero .env existe pero AZURE_DEVOPS_ORG_URL esta vacio.
        echo %INFO% Rellena los campos obligatorios del .env antes de ejecutar.
    ) else (
        echo %OK% Fichero .env encontrado y con contenido.
    )
) else (
    if exist ".env.example" (
        copy ".env.example" ".env" >nul
        echo %WARN% No se encontro el fichero .env.
        echo.
        echo       Se ha creado una copia desde .env.example
        echo.
        echo       ACCION REQUERIDA - Configura el fichero .env:
        echo.
        echo       1. Abre el fichero ".env" con el Bloc de notas
        echo       2. Rellena los campos obligatorios:
        echo            - AZURE_DEVOPS_ORG_URL  ^(URL de tu organizacion en Azure^)
        echo            - AZURE_DEVOPS_PROJECT   ^(Nombre del proyecto en Azure^)
        echo            - SQL_SERVER             ^(Nombre de tu servidor SQL Server^)
        echo            - SQL_DATABASE           ^(Nombre de tu base de datos^)
        echo       3. Guarda el fichero
        echo       4. Vuelve a ejecutar instalar.bat
        echo.
        set /a ERRORES+=1
        goto :resumen_final
    ) else (
        echo %ERR% No se encontro ni .env ni .env.example.
        echo.
        echo       Asegurate de haber descargado el proyecto completo desde GitHub.
        echo.
        set /a ERRORES+=1
        goto :resumen_final
    )
)


:: -----------------------------------------------------------------------------
:: PASO 4 - Crear el entorno virtual
:: -----------------------------------------------------------------------------
echo.
echo %STEP% Paso 4/5 - Preparando entorno virtual del proyecto...
echo.

if exist ".venv\" (
    echo %OK% Entorno virtual ya existe. Se reutilizara.
) else (
    echo %INFO% Creando entorno virtual con Python %PYTHON_VERSION%...

    uv venv --python %PYTHON_VERSION% .venv

    if !ERRORLEVEL! NEQ 0 (
        echo.
        echo %ERR% No se pudo crear el entorno virtual.
        echo.
        echo       Solucion: cierra esta ventana y vuelve a ejecutar instalar.bat.
        echo.
        set /a ERRORES+=1
        goto :resumen_final
    )

    echo %OK% Entorno virtual creado correctamente.
)


:: -----------------------------------------------------------------------------
:: PASO 5 - Instalar dependencias
:: -----------------------------------------------------------------------------
echo.
echo %STEP% Paso 5/5 - Instalando dependencias del proyecto...
echo.
echo %INFO% Esto puede tardar 1-3 minutos en la primera instalacion.
echo.

uv pip install -r requirements.txt --python .venv\Scripts\python.exe

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo %ERR% Error al instalar las dependencias.
    echo.
    echo       Posibles causas:
    echo       - El fichero requirements.txt tiene errores
    echo       - Alguna libreria no esta disponible temporalmente
    echo       - Problema de conexion durante la descarga
    echo.
    echo       Solucion: vuelve a ejecutar instalar.bat.
    echo.
    set /a ERRORES+=1
    goto :resumen_final
)

echo.
echo %OK% Todas las dependencias instaladas correctamente.


:: =============================================================================
:resumen_final
:: =============================================================================
echo.
echo ================================================================
echo.

if %ERRORES% EQU 0 (
    echo   INSTALACION COMPLETADA CON EXITO
    echo.
    echo   El proyecto esta listo para usarse.
    echo   Para ejecutarlo, haz doble clic en:  ejecutar.bat
    echo.
    echo   Si es la primera vez, el sistema pedira tus credenciales
    echo   de Azure y SQL Server y las guardara de forma segura.
) else (
    echo   LA INSTALACION NO SE COMPLETO
    echo.
    echo   Revisa los mensajes [ERROR] que aparecen arriba,
    echo   sigue las instrucciones y vuelve a ejecutar instalar.bat.
    echo.
    echo   Si el problema persiste, abre un issue en GitHub adjuntando
    echo   una captura de pantalla de esta ventana.
)

echo.
echo ================================================================
echo.
echo   Pulsa cualquier tecla para cerrar esta ventana...
pause >nul
exit /b %ERRORES%


:: =============================================================================
:: FUNCIONES AUXILIARES
:: =============================================================================

:imprimir_cabecera
echo.
echo ================================================================
echo.
echo   Azure Boards Manager - Instalador
echo.
echo   Este script configurara todo lo necesario para ejecutar
echo   el proyecto en este equipo.
echo.
echo   No cierres esta ventana hasta que aparezca el resumen final.
echo.
echo ================================================================
goto :eof

:recargar_path
for /f "tokens=2*" %%a in ('reg query "HKCU\Environment" /v PATH 2^>nul') do (
    set "PATH=%%b;%PATH%"
)
goto :eof
