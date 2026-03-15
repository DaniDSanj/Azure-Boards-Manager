"""Ejecución de consultas SQL y procedimientos almacenados en SQL Server."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Union

from sqlalchemy import text
from sqlalchemy.engine import Engine

from modules.utils.logger import get_logger

logger = get_logger(__name__)

# Directorio base para los ficheros .sql, relativo al directorio de trabajo
_DEFAULT_SQL_BASE_DIR = Path("input") / "sql"

# Encodings que se intentarán al leer ficheros .sql, en orden de preferencia.
_SQL_FILE_ENCODINGS = ("utf-8-sig", "utf-8", "latin-1")


class SqlExecutor:
    """
    Ejecuta consultas SQL y procedimientos almacenados en SQL Server.

    Recibe un engine de SQLAlchemy ya construido y validado por
    SqlConnection. No gestiona credenciales ni conexiones.

    Uso típico:
        conn     = SqlConnection(server="srv", database="bd")
        executor = SqlExecutor(engine=conn.engine)

        # Consulta embebida
        rows = executor.execute_query(
            "SELECT * FROM dbo.clientes WHERE activo = :activo",
            params={"activo": True}
        )

        # Consulta desde fichero
        rows = executor.execute_query_from_file("informe_mensual.sql")

        # Procedimiento almacenado
        result = executor.execute_procedure("dbo.usp_procesar_items")
    """

    def __init__(
        self,
        engine: Engine,
        sql_base_dir: Path | str = _DEFAULT_SQL_BASE_DIR,
    ) -> None:
        """
        Inicializa el ejecutor con un engine ya validado.

        Args:
            engine:       Engine de SQLAlchemy obtenido desde SqlConnection.
            sql_base_dir: Directorio base para la resolución de ficheros .sql.
                          Por defecto: ./input/sql/ relativo al directorio
                          de trabajo. Se puede sobreescribir en tests o en
                          proyectos con estructura de carpetas diferente.

        Raises:
            TypeError: Si engine no es una instancia de Engine.
        """
        if not isinstance(engine, Engine):
            raise TypeError(
                f"Se esperaba un Engine de SQLAlchemy, "
                f"pero se recibió {type(engine).__name__}. "
                f"Usa SqlConnection para construir el engine."
            )

        self._engine       = engine
        self._sql_base_dir = Path(sql_base_dir)

    def execute_query(
        self,
        sql: str,
        params: Dict[str, Any] | None = None,
    ) -> List[Dict[str, Any]]:
        """
        Ejecuta una consulta SQL y devuelve los resultados como lista
        de diccionarios.

        Cada diccionario representa una fila, con los nombres de columna
        como claves. Si la consulta no produce filas (UPDATE, DELETE,
        DDL...), devuelve una lista vacía.

        Los parámetros se enlazan de forma segura usando la sintaxis
        :nombre, que SQLAlchemy traduce al formato nativo del driver
        (? para pyodbc). Nunca interpoles valores directamente en el
        string SQL.

        Args:
            sql:    Sentencia SQL a ejecutar. Puede contener parámetros
                    en formato :nombre (ej. "WHERE id = :id").
            params: Diccionario de parámetros enlazados.
                    Ejemplo: {"id": 42, "activo": True}.
                    None si la consulta no tiene parámetros.

        Returns:
            Lista de diccionarios con los resultados.
            Lista vacía si la consulta no devuelve filas.

        Raises:
            ValueError: Si sql es None o está vacío.
            Exception:  Si la ejecución SQL falla.

        Example:
            >>> rows = executor.execute_query(
            ...     "SELECT id, nombre FROM dbo.clientes WHERE activo = :activo",
            ...     params={"activo": True}
            ... )
            >>> for row in rows:
            ...     print(row["id"], row["nombre"])
        """
        self._validate_sql(sql)

        logger.debug(
            "Ejecutando query (%d chars)%s.",
            len(sql),
            f" con {len(params)} parámetro(s)" if params else "",
        )

        return self._run_query(sql, params)

    def execute_query_from_file(
        self,
        filename: str,
        params: Dict[str, Any] | None = None,
    ) -> List[Dict[str, Any]]:
        """
        Carga un fichero .sql desde el directorio base y lo ejecuta.

        El fichero se resuelve como: {sql_base_dir}/{filename}.
        Se admiten rutas relativas con subdirectorios dentro del
        directorio base (ej. "subdir/consulta.sql").

        El fichero se lee con detección automática de encoding:
        se intentan UTF-8-BOM, UTF-8 y Latin-1 en ese orden.
        Esto cubre los ficheros guardados tanto desde editores Linux
        como desde SQL Server Management Studio en Windows.

        Args:
            filename: Nombre del fichero (con extensión).
                      Puede incluir subdirectorios relativos al base_dir.
                      Ejemplo: "informe.sql", "monthly/ventas.sql".
            params:   Parámetros enlazados, igual que en execute_query.

        Returns:
            Lista de diccionarios con los resultados.
            Lista vacía si la consulta no devuelve filas.

        Raises:
            FileNotFoundError: Si el fichero no existe en la ruta resuelta.
            ValueError:        Si el fichero está vacío.
            Exception:         Si la ejecución SQL falla.

        Example:
            >>> rows = executor.execute_query_from_file(
            ...     "resumen_mensual.sql",
            ...     params={"anio": 2025, "mes": 6}
            ... )
        """
        filepath = self._resolve_sql_file(filename)
        sql      = self._read_sql_file(filepath)

        logger.debug(
            "Ejecutando fichero SQL: '%s'%s.",
            filepath,
            f" con {len(params)} parámetro(s)" if params else "",
        )

        return self._run_query(sql, params)

    def execute_procedure(
        self,
        name: str,
        params: Dict[str, Any] | None = None,
    ) -> Union[List[Dict[str, Any]], bool]:
        """
        Ejecuta un procedimiento almacenado y devuelve el resultado.

        Gestiona automáticamente los múltiples result sets que SQL Server
        puede devolver durante la ejecución de un SP (mensajes de progreso,
        contadores intermedios, resultado final). Devuelve el primer result
        set que contenga filas de datos.

        Comportamiento de retorno:
            - Lista de diccionarios: si el SP devolvió al menos un result
              set con filas. Cada diccionario es una fila del resultado.
            - True:  el SP se ejecutó sin errores pero no devolvió filas.
            - False: el SP lanzó una excepción durante la ejecución.

        Args:
            name:   Nombre completo del procedimiento almacenado.
                    Incluir siempre el esquema para evitar ambigüedades.
                    Ejemplo: 'dbo.usp_merge_work_items', 'raw.usp_limpiar'.
            params: Parámetros del procedimiento como diccionario.
                    Las claves deben coincidir exactamente con los nombres
                    de los parámetros del SP (sin el @ inicial).
                    Ejemplo: {"id_cliente": 42, "activo": True}

        Returns:
            Lista de diccionarios, True o False según se describe arriba.

        Raises:
            ValueError: Si name es None o está vacío.

        Example:
            >>> # SP que devuelve datos
            >>> result = executor.execute_procedure(
            ...     "dbo.usp_get_resumen",
            ...     params={"anio": 2025}
            ... )
            >>> if isinstance(result, list):
            ...     for row in result:
            ...         print(row)

            >>> # SP sin retorno de datos
            >>> ok = executor.execute_procedure("dbo.usp_procesar_todo")
            >>> print("OK" if ok else "ERROR")
        """
        if not name or not name.strip():
            raise ValueError(
                "El nombre del procedimiento almacenado no puede ser None ni vacío."
            )

        logger.debug(
            "Ejecutando procedimiento almacenado: '%s'%s.",
            name,
            f" con parámetros {list(params.keys())}" if params else "",
        )

        return self._run_procedure(name, params)

    def _run_query(
        self,
        sql: str,
        params: Dict[str, Any] | None,
    ) -> List[Dict[str, Any]]:
        """
        Ejecuta una sentencia SQL y convierte los resultados a lista
        de diccionarios.

        Usa una conexión de solo lectura (sin begin()) para consultas
        SELECT, y una transacción (con begin()) para sentencias que
        modifican datos. La distinción se hace inspeccionando la primera
        palabra del SQL normalizado.

        Args:
            sql:    Sentencia SQL a ejecutar (ya validada).
            params: Parámetros enlazados o None.

        Returns:
            Lista de diccionarios con los resultados, o lista vacía.

        Raises:
            Exception: Si la ejecución SQL falla.
        """
        sql_upper     = sql.strip().upper()
        is_modifying  = any(
            sql_upper.startswith(kw)
            for kw in ("INSERT", "UPDATE", "DELETE", "MERGE", "TRUNCATE",
                       "CREATE", "ALTER", "DROP", "EXEC", "EXECUTE")
        )

        try:
            if is_modifying:
                # Sentencias que modifican datos: transacción explícita
                with self._engine.begin() as conn:
                    result = conn.execute(
                        text(sql),
                        params or {},
                    )
                    rows = self._cursor_to_dicts(result)
            else:
                # SELECT y similares: conexión sin transacción
                with self._engine.connect() as conn:
                    result = conn.execute(
                        text(sql),
                        params or {},
                    )
                    rows = self._cursor_to_dicts(result)

            logger.debug("Query ejecutada. Filas devueltas: %d.", len(rows))
            return rows

        except Exception as e:
            logger.error("Error al ejecutar query: %s", e)
            raise

    def _run_procedure(
        self,
        name: str,
        params: Dict[str, Any] | None,
    ) -> Union[List[Dict[str, Any]], bool]:
        """
        Ejecuta un procedimiento almacenado navegando por todos los
        result sets que devuelva SQL Server.

        Construye la llamada EXEC con parámetros nombrados (@param = :param)
        para garantizar la correspondencia correcta independientemente del
        orden en que el SP los declara.

        Navega por todos los result sets devueltos (SQL Server puede emitir
        varios antes del resultado final) y devuelve el primero que contenga
        filas. Si ninguno contiene filas, devuelve True.

        El bloque SET NOCOUNT ON suprime los mensajes de "N rows affected"
        que SQL Server emite entre result sets y que pueden interferir
        con la detección del resultado real.

        Args:
            name:   Nombre del SP (ya validado).
            params: Parámetros del SP o None.

        Returns:
            Lista de diccionarios, True, o False.
        """
        exec_sql = self._build_exec_sql(name, params)

        try:
            with self._engine.begin() as conn:
                # SET NOCOUNT ON: suprime mensajes intermedios de filas
                # afectadas que interferirían con nextset()
                conn.execute(text("SET NOCOUNT ON"))

                raw_conn   = conn.connection.connection   # conexión pyodbc nativa
                cursor     = raw_conn.cursor()

                cursor.execute(exec_sql, list(params.values()) if params else [])

                # Navegar por todos los result sets hasta encontrar datos
                rows = self._consume_result_sets(cursor)
                cursor.close()

            if rows:
                logger.debug(
                    "Procedimiento '%s' ejecutado. Filas devueltas: %d.",
                    name, len(rows),
                )
                return rows

            logger.debug("Procedimiento '%s' ejecutado sin filas de retorno.", name)
            return True

        except Exception as e:
            logger.error(
                "Error al ejecutar el procedimiento '%s': %s", name, e
            )
            return False

    @staticmethod
    def _build_exec_sql(
        name: str,
        params: Dict[str, Any] | None,
    ) -> str:
        """
        Construye la sentencia EXEC con parámetros nombrados.

        Formato generado:
            EXEC dbo.usp_mi_proc @param1 = ?, @param2 = ?

        Los parámetros se pasan por posición como lista de valores
        (en el mismo orden que las claves del diccionario), y los
        marcadores ? corresponden al formato nativo de pyodbc.

        El uso de parámetros enlazados (?) en lugar de interpolación
        directa del valor protege contra SQL injection incluso en
        llamadas a procedimientos almacenados.

        Args:
            name:   Nombre completo del SP.
            params: Parámetros del SP o None.

        Returns:
            Sentencia EXEC lista para ejecutar con pyodbc.

        Example:
            >>> _build_exec_sql("dbo.usp_test", {"id": 1, "activo": True})
            'EXEC dbo.usp_test @id = ?, @activo = ?'
        """
        if not params:
            return f"EXEC {name}"

        param_str = ", ".join(f"@{key} = ?" for key in params)
        return f"EXEC {name} {param_str}"

    @staticmethod
    def _consume_result_sets(cursor: Any) -> List[Dict[str, Any]]:
        """
        Navega por todos los result sets que devuelve un cursor pyodbc
        y retorna el primer conjunto que contenga filas de datos.

        SQL Server puede emitir múltiples result sets en una sola
        ejecución (mensajes PRINT, contadores, resultados intermedios).
        Este método los consume todos hasta encontrar uno con filas,
        lo que garantiza que el cursor no queda en un estado pendiente.

        Args:
            cursor: Cursor pyodbc tras haber ejecutado el SP.

        Returns:
            Lista de diccionarios con las filas del primer result set
            que contenga datos. Lista vacía si ninguno tiene filas.
        """
        while True:
            try:
                # description es None si el result set no tiene columnas
                # (ej. mensajes de contadores o result sets vacíos)
                if cursor.description:
                    columns = [col[0] for col in cursor.description]
                    raw_rows = cursor.fetchall()

                    if raw_rows:
                        # Primer result set con filas: convertir y devolver
                        return [
                            dict(zip(columns, row))
                            for row in raw_rows
                        ]

                # Este result set no tenía filas: avanzar al siguiente
                if not cursor.nextset():
                    break   # No hay más result sets

            except Exception:
                # Algunos drivers lanzan excepción en nextset() cuando
                # no hay más result sets en lugar de devolver False
                break

        return []

    @staticmethod
    def _cursor_to_dicts(result: Any) -> List[Dict[str, Any]]:
        """
        Convierte el resultado de una ejecución SQLAlchemy en una lista
        de diccionarios.

        Si el resultado no tiene columnas (sentencia sin retorno),
        devuelve una lista vacía sin lanzar excepción.

        Args:
            result: Objeto CursorResult devuelto por conn.execute().

        Returns:
            Lista de diccionarios o lista vacía.
        """
        try:
            keys = result.keys()
            return [dict(zip(keys, row)) for row in result.fetchall()]
        except Exception:
            # Las sentencias sin SELECT (UPDATE, DELETE, DDL) no tienen
            # cursor con columnas: es el comportamiento esperado
            return []

    def _resolve_sql_file(self, filename: str) -> Path:
        """
        Resuelve la ruta completa de un fichero .sql a partir de su
        nombre relativo al directorio base.

        Args:
            filename: Nombre del fichero, opcionalmente con subdirectorio
                      relativo al base_dir (ej. "subdir/consulta.sql").

        Returns:
            Ruta absoluta al fichero .sql.

        Raises:
            FileNotFoundError: Si el fichero no existe en la ruta resuelta.
        """
        filepath = (self._sql_base_dir / filename).resolve()

        if not filepath.exists():
            raise FileNotFoundError(
                f"No se encontró el fichero SQL: '{filepath}'.\n"
                f"  Nombre recibido : {filename}\n"
                f"  Directorio base : {self._sql_base_dir.resolve()}\n"
                f"  Ruta completa   : {filepath}\n"
                f"Verifica que el fichero existe y que el directorio base "
                f"es correcto (por defecto: ./input/sql/)."
            )

        logger.debug("Fichero SQL resuelto: '%s'.", filepath)
        return filepath

    @staticmethod
    def _read_sql_file(filepath: Path) -> str:
        """
        Lee el contenido de un fichero .sql con detección automática
        de encoding.

        Se intentan los encodings UTF-8-BOM, UTF-8 y Latin-1 en ese
        orden. UTF-8-BOM (utf-8-sig) es necesario para ficheros
        guardados desde SQL Server Management Studio en Windows, que
        añade un BOM invisible al inicio del fichero.

        Args:
            filepath: Ruta absoluta al fichero .sql.

        Returns:
            Contenido del fichero como string.

        Raises:
            ValueError: Si el fichero está vacío tras leerlo.
            OSError:    Si no se puede leer con ningún encoding soportado.
        """
        last_error: Exception | None = None

        for encoding in _SQL_FILE_ENCODINGS:
            try:
                sql = filepath.read_text(encoding=encoding)
                break
            except UnicodeDecodeError as e:
                last_error = e
                continue
        else:
            raise OSError(
                f"No se pudo leer '{filepath}' con ninguno de los encodings "
                f"soportados ({', '.join(_SQL_FILE_ENCODINGS)}). "
                f"Último error: {last_error}"
            )

        sql = sql.strip()

        if not sql:
            raise ValueError(
                f"El fichero SQL está vacío: '{filepath}'."
            )

        logger.debug(
            "Fichero SQL leído correctamente (%d caracteres, encoding: %s).",
            len(sql), encoding,
        )
        return sql

    @staticmethod
    def _validate_sql(sql: str) -> None:
        """
        Valida que la sentencia SQL no es None ni está vacía.

        Args:
            sql: Sentencia SQL a validar.

        Raises:
            ValueError: Si sql es None, vacío o contiene solo espacios.
        """
        if not sql or not sql.strip():
            raise ValueError(
                "La sentencia SQL no puede ser None ni estar vacía."
            )
