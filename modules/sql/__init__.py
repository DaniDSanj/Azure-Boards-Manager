"""Interfaz pública del módulo de gestión SQL."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

from modules.sql.connection import SqlConnection
from modules.sql.executor import SqlExecutor
from modules.sql.loader import SqlLoader, LoadStrategy
from modules.utils.logger import get_logger

logger = get_logger(__name__)

def create_sql_client(
    server: str,
    database: str,
    username: Optional[str] = None,
    password: Optional[str] = None,
    sql_base_dir: Path | str = Path("input") / "sql",
) -> Tuple[SqlLoader, SqlExecutor]:
    """
    Construye y devuelve un SqlLoader y un SqlExecutor listos para usar,
    compartiendo el mismo engine de conexión subyacente.

    Es la forma recomendada de inicializar el módulo SQL en el 95% de
    los casos, ya que evita instanciar SqlConnection directamente y
    garantiza que loader y executor comparten la misma conexión.

    Args:
        server:       Nombre del servidor o instancia SQL Server.
                      Ejemplos: 'mi_servidor', 'localhost\\SQLEXPRESS'.
        database:     Nombre de la base de datos de destino.
        username:     Usuario SQL Server. None activa Windows Auth.
        password:     Contraseña SQL Server. None activa Windows Auth.
        odbc_driver:  Nombre del driver ODBC instalado.
                      Por defecto: 'ODBC Driver 17 for SQL Server'.
        sql_base_dir: Directorio base para los ficheros .sql.
                      Por defecto: ./input/sql/ relativo al directorio
                      de trabajo del proceso Python.

    Returns:
        Tupla (SqlLoader, SqlExecutor) listos para operar.

    Raises:
        ValueError:       Si se proporciona username sin password
                          o password sin username.
        ConnectionError:  Si la conexión a SQL Server falla.

    Example:
        >>> from modules.sql import create_sql_client
        >>> loader, executor = create_sql_client(
        ...     server="mi_servidor",
        ...     database="mi_bd",
        ... )
        >>> loader.load(df, schema="raw", table="work_items")
        >>> rows = executor.execute_query("SELECT COUNT(*) AS total FROM raw.work_items")
    """
    logger.debug(
        "Inicializando módulo SQL [servidor: %s, base de datos: %s]...",
        server, database,
    )

    connection = SqlConnection(
        server=server,
        database=database,
        username=username,
        password=password,
    )

    loader   = SqlLoader(engine=connection.engine)
    executor = SqlExecutor(
        engine=connection.engine,
        sql_base_dir=Path(sql_base_dir),
    )

    logger.debug("Módulo SQL inicializado correctamente.")
    return loader, executor

__all__ = [
    # Función de conveniencia
    "create_sql_client",
    # Clases para uso avanzado
    "SqlConnection",
    "SqlLoader",
    "SqlExecutor",
    # Enum de estrategias de carga
    "LoadStrategy",
]
