@echo off
cd /d "%~dp0"
setlocal EnableDelayedExpansion
chcp 65001 >nul 2>&1

:: ===================================================================================================
:: Azure Boards Manager - Ejecutar
:: ===================================================================================================
:: Este script lanza el proceso de extraccion de tarjetas desde Azure Boards y su carga en SQL Server. 
:: Es necesario haber ejecutado instalar.bat al menos una vez.
:: ===================================================================================================

set "OK=   [OK]"
set "INFO= [INFO]"
set "WARN= [AVISO]"
set "ERR=  [ERROR]"
set "STEP= --"

:: Registrar hora de inicio para el resumen final
set HORA_INICIO=%TIME%

call :imprimir_cabecera

:: -----------------------------------------------------------------------------
:: COMPROBACION 1 - El entorno virtual existe
:: -----------------------------------------------------------------------------
echo.
echo   Comprobando entorno de ejecucion...
echo.

if not exist ".venv\Scripts\python.exe" (
    echo %ERR% No se encontro el entorno virtual del proyecto.
    echo.
    echo       El proyecto no esta instalado correctamente en este equipo.
    echo.
    echo       Solucion:
    echo         1. Haz doble clic en:  instalar.bat
    echo         2. Espera a que termine la instalacion
    echo         3. Vuelve a ejecutar:  ejecutar.bat
    echo.
    goto :fin_con_error
)

echo %OK% Entorno virtual encontrado.

:: -----------------------------------------------------------------------------
:: COMPROBACION 2 - El fichero .env existe y tiene los campos obligatorios
:: -----------------------------------------------------------------------------
if not exist ".env" (
    echo %ERR% No se encontro el fichero de configuracion ^(.env^).
    echo.
    echo       Solucion:
    echo         1. Haz doble clic en:  instalar.bat
    echo         2. Sigue las instrucciones para configurar el fichero .env
    echo         3. Vuelve a ejecutar:  ejecutar.bat
    echo.
    goto :fin_con_error
)

:: Verificar campos obligatorios del .env
:: Para cada campo, se lee su valor desde el .env con for /f y se comprueba
:: si esta vacio. Este metodo es mas fiable que findstr para este caso.
set CAMPOS_FALTANTES=

for %%F in (AZURE_DEVOPS_ORG_URL AZURE_DEVOPS_PROJECT SQL_SERVER SQL_DATABASE) do (
    set "VALOR_%%F="
    for /f "tokens=1,* delims==" %%A in ('findstr /i "^%%F=" .env 2^>nul') do (
        set "VALOR_%%F=%%B"
    )
    if "!VALOR_%%F!"=="" (
        set "CAMPOS_FALTANTES=!CAMPOS_FALTANTES! %%F"
    )
)

if not "!CAMPOS_FALTANTES!"=="" (
    echo %ERR% El fichero .env tiene campos obligatorios sin rellenar:
    echo.
    for %%F in (!CAMPOS_FALTANTES!) do (
        echo         - %%F
    )
    echo.
    echo       Solucion:
    echo         1. Abre el fichero ".env" con el Bloc de notas
    echo         2. Rellena los campos indicados arriba
    echo         3. Guarda el fichero y vuelve a ejecutar ejecutar.bat
    echo.
    goto :fin_con_error
)

echo %OK% Configuracion verificada.

:: -----------------------------------------------------------------------------
:: EJECUCION - Lanzar el proceso principal
:: -----------------------------------------------------------------------------
echo.
echo   Ejecutando fichero principal...

:: Activar el entorno virtual y ejecutar el proyecto
call .venv\Scripts\activate.bat
python main.py
set CODIGO_SALIDA=%ERRORLEVEL%
call .venv\Scripts\deactivate.bat 2>nul

:: -----------------------------------------------------------------------------
:: RESUMEN FINAL
:: -----------------------------------------------------------------------------
echo.

if %CODIGO_SALIDA% EQU 0 (
    echo   Proceso completado con exito.
    echo.
    echo     Hora Inicio : %HORA_INICIO%
    echo     Hora Fin    : %TIME%
    echo.
    echo   Los datos han sido cargados en SQL Server correctamente.
    echo   Puedes revisar el detalle completo en el fichero de log: Azure-Boards-Manager.log
) else (
    echo   EL PROCESO HA FINALIZADO CON ERRORES  ^(codigo: %CODIGO_SALIDA%^)
    echo.
    echo     Hora Inicio : %HORA_INICIO%
    echo     Hora Fin    : %TIME%
    echo.
    echo   Que hacer ahora:
    echo     1. Revisa los mensajes de error que aparecen arriba
    echo     2. Consulta el fichero de log para mas detalle: Azure-Boards-Manager.log
    echo     3. Si el error persiste, abre un issue en GitHub adjuntando
    echo        una captura de pantalla de esta ventana y el fichero .log
)

echo.
echo ===================================================================================================
echo.
pause
exit /b %CODIGO_SALIDA%

:: =============================================================================
:: FUNCIONES AUXILIARES
:: =============================================================================

:imprimir_cabecera
echo.
echo ===================================================================================================
echo   Azure Boards Manager - Ejecucion Manual
echo ===================================================================================================
goto :eof

:fin_con_error
echo ===================================================================================================
echo.
pause
exit /b 1
