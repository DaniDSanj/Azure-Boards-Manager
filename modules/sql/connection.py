"""Gestión centralizada de conexiones a SQL Server."""

from typing import Optional
from urllib.parse import quote_plus

import pyodbc
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from modules.utils.logger import get_logger

logger = get_logger(__name__)

# Driver ODBC por defecto, aunque se busca la versión mas reciente
_DEFAULT_ODBC_DRIVER = "ODBC Driver 17 for SQL Server"

class SqlConnection:
    """
    Fábrica de conexiones a SQL Server mediante SQLAlchemy + pyodbc.

    Gestiona la selección automática del modo de autenticación
    (Windows Auth o SQL Server Auth) y valida la conexión en el
    momento de la construcción, fallando rápido si algo no está
    configurado correctamente.

    Attributes:
        engine: Engine de SQLAlchemy listo para usar por SqlLoader
                y SqlExecutor. Solo se crea si la conexión de prueba
                tiene éxito.
    """

    def __init__(
        self,
        server: str,
        database: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
        timeout: int = 3
    ) -> None:
        """
        Inicializa la conexión y verifica que es funcional.

        El modo de autenticación se selecciona automáticamente:
            - username=None y password=None → Windows Authentication.
            - username y password con valor → SQL Server Authentication.

        Una vez construido el objeto, el engine ya ha sido validado
        con un SELECT 1 y está listo para operar.

        Args:
            server:      Nombre del servidor o instancia SQL Server.
                         Ejemplos: 'mi_servidor', 'localhost\\SQLEXPRESS',
                         '192.168.1.10,1433'.
            database:    Nombre de la base de datos de destino.
            username:    Usuario SQL Server. None activa Windows Auth.
            password:    Contraseña SQL Server. None activa Windows Auth.

        Raises:
            ValueError:       Si se proporciona username sin password
                              o password sin username.
            ConnectionError:  Si la conexión o la prueba SELECT 1 fallan.

        Example:
            >>> conn = SqlConnection(server="srv", database="bd")
            >>> engine = conn.engine
        """

        odbc_list = [ driver for driver in pyodbc.drivers() if "SQL Server" in driver ]
        odbc_driver = odbc_list[-1] if odbc_list[-1] else _DEFAULT_ODBC_DRIVER

        self._server      = server
        self._database    = database
        self._odbc_driver = odbc_driver

        self._validate_auth_params(username, password)

        self._auth_mode = (
            "SQL Server Authentication"
            if username and password
            else "Windows Authentication"
        )

        self.engine: Engine = self._build_and_validate_engine(
            username, password, timeout
        )

    def test_connection(self) -> bool:
        """
        Ejecuta una prueba de conectividad sobre el engine existente.

        Útil para verificar que la conexión sigue activa después de un
        período de inactividad, sin necesidad de construir un nuevo objeto.

        Returns:
            True  si el engine responde correctamente a SELECT 1.
            False si la conexión ha fallado por cualquier motivo.

        Example:
            >>> if not conn.test_connection():
            ...     logger.warning("La conexión SQL ha caído.")
        """
        try:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            logger.debug(
                "Test de conexión exitoso [%s/%s].",
                self._server, self._database,
            )
            return True

        except SQLAlchemyError as e:
            logger.warning(
                "Test de conexión fallido [%s/%s]: %s",
                self._server, self._database, e,
            )
            return False

    def __repr__(self) -> str:
        return (
            f"SqlConnection("
            f"server={self._server!r}, "
            f"database={self._database!r}, "
            f"auth={self._auth_mode!r})"
        )

    def _build_and_validate_engine(
        self,
        username: Optional[str],
        password: Optional[str],
        timeout: int
    ) -> Engine:
        """
        Construye el engine de SQLAlchemy y verifica la conexión con
        un SELECT 1. Si algo falla, lanza ConnectionError con un mensaje
        claro que indica el servidor, la base de datos y el motivo.

        La cadena de conexión se construye de forma diferente según el
        modo de autenticación activo.

        Para SQL Server Auth, la contraseña se codifica con quote_plus
        para escapar correctamente caracteres especiales (ej. '@', '#',
        '%') que de otro modo romperían el parsing de la URL.

        Args:
            username: Usuario SQL. None si Windows Auth.
            password: Contraseña SQL. None si Windows Auth.

        Returns:
            Engine de SQLAlchemy validado y listo para operar.

        Raises:
            ConnectionError: Si la creación o la prueba de conexión fallan.
        """
        connection_url = self._build_connection_url(username, password)

        logger.debug(
            "Conectando a SQL Server [%s] base de datos [%s] usando %s...",
            self._server, self._database, self._auth_mode,
        )

        try:
            engine = create_engine(
                connection_url,
                connect_args={"timeout": timeout},
                pool_pre_ping=True, # Evita errores por conexiones previas que han caducado
                echo=False, # No imprime el SQL generado en los logs.
            )

            # Prueba de conexión explícita: falla rápido si algo está mal
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))

            logger.debug(
                "Conexión establecida correctamente [%s/%s] (%s).",
                self._server, self._database, self._auth_mode,
            )
            return engine

        except SQLAlchemyError as e:
            raise ConnectionError(
                f"No se pudo conectar a SQL Server.\n"
                f"  Servidor  : {self._server}\n"
                f"  Base datos: {self._database}\n"
                f"  Modo auth : {self._auth_mode}\n"
                f"  Driver    : {self._odbc_driver}\n"
                f"  Error     : {e}"
            ) from e

    def _build_connection_url(
        self,
        username: Optional[str],
        password: Optional[str],
    ) -> str:
        """
        Construye la cadena de conexión SQLAlchemy según el modo de
        autenticación activo.

        Formato general del dialecto mssql+pyodbc con cadena ODBC
        pasada como parámetro 'odbc_connect' (forma recomendada en
        SQLAlchemy 2.x para evitar problemas con caracteres especiales
        en el nombre del servidor o la contraseña):

            mssql+pyodbc:///?odbc_connect=DRIVER=...;SERVER=...;...

        Esta forma es más robusta que la URL clásica porque no requiere
        codificar manualmente el nombre del servidor ni la instancia.

        Args:
            username: Usuario SQL. None si Windows Auth.
            password: Contraseña SQL. None si Windows Auth.

        Returns:
            URL de conexión como string para create_engine().
        """
        driver = self._odbc_driver

        if username and password:
            # SQL Server Authentication
            safe_password = quote_plus(password)
            odbc_str = (
                f"DRIVER={{{driver}}};"
                f"SERVER={self._server};"
                f"DATABASE={self._database};"
                f"UID={username};"
                f"PWD={safe_password};"
            )
        else:
            # Windows Authentication
            odbc_str = (
                f"DRIVER={{{driver}}};"
                f"SERVER={self._server};"
                f"DATABASE={self._database};"
                f"Trusted_Connection=yes;"
            )

        return f"mssql+pyodbc:///?odbc_connect={quote_plus(odbc_str)}"

    @staticmethod
    def _validate_auth_params(
        username: Optional[str],
        password: Optional[str],
    ) -> None:
        """
        Valida que los parámetros de autenticación son coherentes.

        Reglas:
            - Ambos None → Windows Authentication. Válido.
            - Ambos con valor → SQL Server Authentication. Válido.
            - Solo uno de los dos con valor → configuración incompleta.
              Lanza ValueError con un mensaje explícito.

        Args:
            username: Valor del parámetro username recibido en __init__.
            password: Valor del parámetro password recibido en __init__.

        Raises:
            ValueError: Si solo uno de los dos parámetros tiene valor.
        """
        has_user = bool(username and username.strip())
        has_pass = bool(password and password.strip())

        if has_user == has_pass: # Ambos presentes o ambos ausentes → configuración válida
            return

        missing = "password" if has_user else "username"
        provided = "username" if has_user else "password"

        raise ValueError(
            f"Configuración de autenticación incompleta: "
            f"se proporcionó '{provided}' pero falta '{missing}'. "
            f"Para SQL Server Authentication deben proporcionarse ambos. "
            f"Para Windows Authentication, omite los dos."
        )
