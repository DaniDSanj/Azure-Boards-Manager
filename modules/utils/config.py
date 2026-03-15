"""Gestión centralizada de la configuración del proyecto."""

import os
from dataclasses import dataclass, field
from typing import List, Optional

from dotenv import load_dotenv

from modules.credentials import get_credential, get_login
from modules.sql.connection import SqlConnection
from modules.utils.logger import get_logger

logger = get_logger(__name__)

# Nombres clave en Windows Credential Manager
CREDENTIAL_KEY_PAT       = "azure_pat"
CREDENTIAL_KEY_SQL_LOGIN = "sql_login"

@dataclass
class AppConfig:
    """
    Contenedor tipado con toda la configuración de la aplicación.

    Combina la configuración no sensible (leída del .env) con las
    credenciales sensibles (leídas del Credential Manager cuando
    Windows Authentication no está disponible para el usuario actual).

    Attributes:
        org_url:      URL base de la organización en Azure DevOps.
        project:      Nombre del proyecto en Azure DevOps.
        pat:          Personal Access Token de Azure DevOps.
                      Siempre obtenida del Credential Manager.
        sql_server:   Nombre del servidor o instancia SQL Server.
        sql_database: Nombre de la base de datos de destino.
        sql_user:     Usuario SQL Server.
                      None si Windows Authentication está disponible.
                      Valor real si se usa SQL Server Authentication.
        sql_password: Contraseña SQL Server.
                      None si Windows Authentication está disponible.
                      Valor real si se usa SQL Server Authentication.
        root_ids:     Lista de IDs de tarjetas raíz a procesar.
                      Lista vacía si no se define AZURE_ROOT_IDS en el .env.
        azure_fields: Lista de campos de Azure DevOps a extraer.
                      Lista vacía si no se define AZURE_FIELDS en el .env;
                      en ese caso el extractor usará su _DEFAULT_FIELDS.
    """
    # Azure DevOps
    azure_org_url: str
    azure_project: str
    azure_pat: str

    # Conexión SQL Server
    sql_server:   str
    sql_database: str
    sql_user: Optional[str]         # None → Windows Auth
    sql_password: Optional[str]     # None → Windows Auth
    sql_dest_schema: str
    sql_dest_table: str
    sql_log_schema: str
    sql_log_table: str
    sql_stored_procedure: str
    sql_windows_auth_timeout: int

    # Otras (opcionales)
    azure_root_ids: List[int] = field(default_factory=list)
    azure_fields: List[str] = field(default_factory=list)

def load_config() -> AppConfig:
    """
    Carga la configuración completa del proyecto combinando el .env
    y el Credential Manager de Windows.

    Proceso:
        1. Lee las variables no sensibles del fichero .env.
        2. Valida que todas las variables obligatorias están presentes.
        3. Carga la PAT de Azure desde el Credential Manager.
        4. Determina el modo de autenticación SQL mediante una conexión
           de prueba con Windows Authentication (con timeout configurable).
        5. Si Windows Auth no está disponible, carga las credenciales SQL
           desde el Credential Manager.
        6. Construye y devuelve el objeto AppConfig.

    Returns:
        AppConfig con toda la configuración lista para usar.

    Raises:
        ValueError:  Si alguna variable obligatoria del .env no está definida,
                     o si SQL_WINDOWS_AUTH_TIMEOUT contiene un valor inválido.
        SystemExit:  Si el usuario no introduce alguna credencial cuando
                     se le solicita en la primera ejecución con SQL Auth.
    """
    load_dotenv()

    # Leer .env
    azure_org_url = os.getenv("AZURE_DEVOPS_ORG_URL")
    azure_project = os.getenv("AZURE_DEVOPS_PROJECT")
    azure_root_ids = _parse_root_ids(os.getenv("AZURE_ROOT_IDS", ""))
    azure_fields   = _parse_fields(os.getenv("AZURE_FIELDS", ""))
    sql_server = os.getenv("SQL_SERVER")
    sql_database = os.getenv("SQL_DATABASE")
    sql_dest_schema = os.getenv( "SQL_SCHEMA" , "raw" )
    sql_dest_table = os.getenv( "SQL_TABLE" , "azuTarjetas" )
    sql_log_schema = os.getenv( "SQL_LOG_SCHEMA" , "raw" )
    sql_log_table = os.getenv( "SQL_LOG_TABLE" , "LogsPython" )
    sql_stored_procedure = os.getenv( "SQL_STORED_PROCEDURE" , "dbo.SP_AzureModelo" )
    sql_windows_auth_timeout = _parse_timeout( os.getenv( "SQL_WINDOWS_AUTH_TIMEOUT" , "3" ) )

    # Credenciales opcionales del .env (Prioridad 1 — fallback rápido)
    azure_pat = os.getenv("AZURE_DEVOPS_PAT", "").strip() or None
    sql_user = os.getenv("SQL_USER", "").strip() or None
    sql_password = os.getenv("SQL_PASSWORD", "").strip() or None

    # Validar variables obligatorias
    missing = [
        name for name, value in {
            "AZURE_DEVOPS_ORG_URL": azure_org_url,
            "AZURE_DEVOPS_PROJECT": azure_project,
            "SQL_SERVER": sql_server,
            "SQL_DATABASE": sql_database,
        }.items()
        if not value
    ]

    if missing:
        raise ValueError(
            f"Faltan las siguientes variables en el fichero .env: "
            f"{', '.join(missing)}. "
            f"Consulta .env.example para ver el formato esperado."
        )

    # Resolver PAT de Azure
    azure_pat = _load_pat(azure_pat)

    # Resolver credenciales SQL
    sql_user, sql_password = _load_sql_credentials(
        server = sql_server,
        database = sql_database,
        timeout = sql_windows_auth_timeout,
        sql_user = sql_user,
        sql_password = sql_password,
    )

    # Construir AppConfig
    logger.debug("Configuración cargada correctamente.")

    return AppConfig(
        azure_org_url = azure_org_url ,
        azure_project = azure_project ,
        azure_pat = azure_pat ,
        azure_root_ids = azure_root_ids ,
        azure_fields = azure_fields ,
        sql_server = sql_server ,
        sql_database = sql_database ,
        sql_user = sql_user ,
        sql_password = sql_password ,
        sql_dest_schema = sql_dest_schema ,
        sql_dest_table = sql_dest_table ,
        sql_log_schema = sql_log_schema ,
        sql_log_table = sql_log_table ,
        sql_stored_procedure = sql_stored_procedure ,
        sql_windows_auth_timeout = sql_windows_auth_timeout
    )

# Carga PAT de Azure
def _load_pat(env_pat: Optional[str]) -> str:
    """
    Resuelve la PAT de Azure DevOps siguiendo la cadena de prioridad:

      Prioridad 1 — AZURE_DEVOPS_PAT en el .env
          Si está definida y no está vacía, se usa directamente.
          Se emite un WARNING recordando que es menos seguro que el
          Credential Manager.

      Prioridad 2 — Windows Credential Manager
          Si no está en el .env, se recupera del Credential Manager.
          En la primera ejecución se solicita al usuario por consola.

    Args:
        env_pat: Valor de AZURE_DEVOPS_PAT leído del .env, o None si
                 no está definida.

    Returns:
        PAT de Azure DevOps en texto plano.
    """
    if env_pat:
        logger.warning( "PAT de Azure DevOps cargada desde el fichero .env (AZURE_DEVOPS_PAT)" )
        return env_pat

    logger.debug(
        "Recuperando PAT de Azure DevOps del Credential Manager "
        "(clave: '%s')...", CREDENTIAL_KEY_PAT
    )
    pat = get_credential(CREDENTIAL_KEY_PAT)
    logger.debug("PAT de Azure DevOps cargada correctamente.")

    return pat

def _load_sql_credentials(
    server:       str,
    database:     str,
    timeout:      int,
    sql_user: Optional[str],
    sql_password: Optional[str],
) -> tuple[Optional[str], Optional[str]]:
    """
    Resuelve las credenciales SQL siguiendo la cadena de prioridad:

      Prioridad 1 — SQL_USER + SQL_PASSWORD en el .env
          Si ambas están definidas → se usan directamente, saltando
          la prueba de Windows Auth y el Credential Manager.
          Si solo una está definida → WARNING y se ignoran ambas,
          continuando con las prioridades siguientes.

      Prioridad 2 — Windows Authentication
          Se intenta una conexión SELECT 1 con Trusted Connection y
          el timeout configurado. Si tiene éxito → (None, None).

      Prioridad 3 — Windows Credential Manager
          Si Windows Auth falla → get_login("sql_login").
          En la primera ejecución se solicitan al usuario por consola.

    Args:
        server:       Nombre del servidor SQL (del .env).
        database:     Nombre de la base de datos (del .env).
        timeout:      Segundos máximos para el intento de Windows Auth.
        env_sql_user: Valor de SQL_USER del .env, o None.
        env_sql_pass: Valor de SQL_PASSWORD del .env, o None.

    Returns:
        (None, None)      si Windows Authentication está disponible.
        (user, password)  en cualquier otro caso con credenciales válidas.
    """
    # Prioridad 1: credenciales en el .env
    if sql_user and sql_password:
        logger.warning(
            "Credenciales SQL cargadas desde el fichero .env "
            "(SQL_USER + SQL_PASSWORD). Este método es menos seguro que el "
            "Credential Manager. Considera migrar las credenciales al sistema "
            "una vez el entorno esté configurado."
        )
        return sql_user, sql_password

    if bool(sql_user) != bool(sql_password):
        # Solo una de las dos está definida: configuración incompleta.
        # Se ignoran ambas y se continúa con el flujo normal.
        defined   = "SQL_USER"     if sql_user else "SQL_PASSWORD"
        undefined = "SQL_PASSWORD" if sql_user else "SQL_USER"
        logger.warning(
            "Configuración SQL incompleta en el .env: '%s' está definida "
            "pero '%s' no lo está. Se ignorarán ambas y se usará el flujo "
            "habitual (Windows Auth → Credential Manager). "
            "Define las dos juntas o ninguna.",
            defined, undefined
        )

    # Prioridad 2: Windows Authentication
    logger.debug(
        "Comprobando disponibilidad de Windows Authentication "
        "(servidor: %s, timeout: %ds)...", server, timeout
    )

    if _probe_windows_auth(server, database, timeout):
        logger.debug(
            "Windows Authentication disponible. "
            "No se requieren credenciales SQL adicionales."
        )
        return None, None

    # Prioridad 3: Windows Credential Manager
    logger.debug(
        "Windows Authentication no disponible. "
        "Usando SQL Server Authentication vía Credential Manager."
    )
    logger.debug(
        "Recuperando credenciales SQL Server (clave: '%s')...",
        CREDENTIAL_KEY_SQL_LOGIN
    )
    sql_user, sql_password = get_login(CREDENTIAL_KEY_SQL_LOGIN)
    logger.debug("Credenciales SQL Server cargadas correctamente.")
    return sql_user, sql_password

def _probe_windows_auth(server: str, database: str, timeout: int) -> bool:
    """
    Intenta una conexión de prueba a SQL Server con Windows Authentication.

    Delega en SqlConnection y su método test_connection(), usando el
    mismo driver y mecanismo de conexión que se empleará en el proceso
    real.

    La conexión se construye con un timeout de red equivalente al
    configurado en SQL_WINDOWS_AUTH_TIMEOUT. Si SqlConnection no puede
    establecer la conexión dentro de ese tiempo, devuelve False.

    La función es completamente silenciosa para el usuario: no lanza
    excepciones ni muestra mensajes en pantalla. Todos los detalles
    quedan registrados en el log para diagnóstico.

    Args:
        server:   Nombre del servidor o instancia SQL Server.
        database: Nombre de la base de datos de destino.
        timeout:  Segundos máximos antes de considerar la prueba fallida.

    Returns:
        True  si la conexión con Windows Auth fue exitosa.
        False en cualquier otro caso (timeout, error de autenticación,
              servidor no alcanzable, driver no instalado, etc.).
    """
    try:
        # SqlConnection valida la conexión. Si algo falla, lanza ConnectionError.
        conn = SqlConnection(
            server=server,
            database=database,
            timeout=timeout
        )
        result = conn.test_connection()

        logger.debug(
            "Conexión de prueba con Windows Authentication exitosa "
            "(servidor: %s, base de datos: %s).", server, database
        )
        return result

    except (ConnectionError, TimeoutError, OSError) as e:
        logger.warning(
            "Windows Authentication no disponible "
            "(servidor: %s, base de datos: %s): %s",
            server, database, e
        )
        return False

def _parse_timeout(raw: str) -> int:
    """
    Parsea el valor de SQL_WINDOWS_AUTH_TIMEOUT desde el .env.

    Si la variable no está definida o está vacía, devuelve el valor
    por defecto (_DEFAULT_WINDOWS_AUTH_TIMEOUT). Si contiene un valor
    no numérico o fuera de rango, lanza un ValueError explícito.

    Args:
        raw: String leído del .env. Puede ser vacío si no está definido.

    Returns:
        Timeout en segundos como entero positivo.

    Raises:
        ValueError: Si el valor no es un entero positivo.
    """
    if not raw or not raw.strip():
        logger.debug(
            "SQL_WINDOWS_AUTH_TIMEOUT no definido en el .env. "
            "Usando valor por defecto: %ds.", 3
        )
        return 3

    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise ValueError(
            f"SQL_WINDOWS_AUTH_TIMEOUT contiene un valor no válido: '{raw}'. "
            f"Debe ser un número entero positivo (ej. 3)."
        ) from exc

    if value <= 0:
        raise ValueError(
            f"SQL_WINDOWS_AUTH_TIMEOUT debe ser un número entero positivo. "
            f"Valor recibido: {value}."
        )

    logger.debug(
        "SQL_WINDOWS_AUTH_TIMEOUT configurado a %ds (desde el .env).", value
    )
    return value

def _parse_root_ids(raw: str) -> List[int]:
    """
    Parsea la cadena de IDs separados por comas en una lista de enteros.

    Filtra entradas vacías para tolerar comas finales o espacios.

    Args:
        raw: String con los IDs separados por comas (ej. '12120,13450').

    Returns:
        Lista de enteros. Lista vacía si el string está vacío.

    Raises:
        ValueError: Si algún valor no puede convertirse a entero.

    Examples:
        >>> _parse_root_ids("12120,13450,14200")
        [12120, 13450, 14200]
        >>> _parse_root_ids("")
        []
    """
    if not raw or not raw.strip():
        return []

    try:
        return [int(item.strip()) for item in raw.split(",") if item.strip()]
    except ValueError as e:
        raise ValueError(
            f"AZURE_ROOT_IDS contiene un valor no numérico: {e}. "
            "Asegúrate de que todos los IDs son números enteros separados por comas."
        ) from e

def _parse_fields(raw: str) -> List[str]:
    """
    Parsea la cadena de campos separados por comas en una lista de strings.

    Filtra entradas vacías para tolerar comas finales, espacios en blanco
    o líneas múltiples en el .env.

    Si la variable no está definida o está vacía, devuelve una lista vacía.
    El extractor interpretará una lista vacía como «usar _DEFAULT_FIELDS».

    Args:
        raw: String con los campos separados por comas leído del .env.
             Puede estar vacío si AZURE_FIELDS no está definida.

    Returns:
        Lista de strings con los nombres de campo sin espacios extra.
        Lista vacía si el string está vacío o no está definido.

    Examples:
        >>> _parse_fields("System.Id,System.Title,Custom.Area")
        ['System.Id', 'System.Title', 'Custom.Area']
        >>> _parse_fields("")
        []
        >>> _parse_fields("System.Id, System.Title , ")
        ['System.Id', 'System.Title']
    """
    if not raw or not raw.strip():
        return []

    return [field.strip() for field in raw.split(",") if field.strip()]
