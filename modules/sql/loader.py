"""Carga de DataFrames de pandas en tablas SQL Server."""

from __future__ import annotations

from enum import Enum
from typing import List

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from modules.utils.logger import Dest, get_logger

logger = get_logger(__name__)

# Tamaño de lote para inserciones en bloque.
_INSERT_BATCH_SIZE = 500

class LoadStrategy(str, Enum):
    """
    Estrategias de carga disponibles para SqlLoader.

    Hereda de str para que los valores sean comparables directamente
    con strings literales y serializables a JSON sin conversión extra.

    Example:
        >>> LoadStrategy.TRUNCATE_INSERT == "truncate_insert"
        True
    """
    TRUNCATE_INSERT = "truncate_insert"
    INSERT          = "insert"
    UPSERT          = "upsert"
    INSERT_OR_FAIL  = "insert_or_fail"

class SqlLoader:
    """
    Carga DataFrames de pandas en tablas SQL Server aplicando
    la estrategia de carga indicada.

    Recibe un engine de SQLAlchemy ya construido y validado por
    SqlConnection. No gestiona credenciales ni cadenas de conexión:
    esa responsabilidad pertenece exclusivamente a SqlConnection.

    La tabla de destino se crea automáticamente si no existe,
    inferiendo los tipos SQL desde los dtypes del DataFrame.
    """

    def __init__(self, engine: Engine) -> None:
        """
        Inicializa el cargador con un engine ya validado.

        Args:
            engine: Engine de SQLAlchemy obtenido desde SqlConnection.

        Raises:
            TypeError: Si engine no es una instancia de Engine.
        """
        if not isinstance(engine, Engine):
            raise TypeError(
                f"Se esperaba un Engine de SQLAlchemy, "
                f"pero se recibió {type(engine).__name__}. "
                f"Usa SqlConnection para construir el engine."
            )
        self._engine = engine

    def load(
        self,
        df: pd.DataFrame,
        schema: str,
        table: str,
        strategy: LoadStrategy = LoadStrategy.TRUNCATE_INSERT,
        key_columns: List[str] | None = None,
        batch_size: int = _INSERT_BATCH_SIZE,
    ) -> int:
        """
        Carga el DataFrame en la tabla indicada aplicando la estrategia
        de carga especificada.

        Si la tabla no existe, se crea automáticamente antes de la carga
        inferiendo los tipos SQL desde los dtypes del DataFrame.

        Args:
            df:          DataFrame con los datos a cargar. No puede estar vacío.
            schema:      Esquema SQL Server de destino (ej. 'raw', 'dbo').
            table:       Nombre de la tabla de destino (ej. 'work_items').
            strategy:    Estrategia de carga. Por defecto: TRUNCATE_INSERT.
                         Ver LoadStrategy para las opciones disponibles.
            key_columns: Lista de columnas que identifican unívocamente
                         cada fila. Obligatorio solo para UPSERT.
                         Ejemplo: ['id'], ['id_cliente', 'fecha'].
            batch_size:  Número de filas por lote en las inserciones.
                         Por defecto: 500.

        Returns:
            Número de filas procesadas en la carga.

        Raises:
            ValueError:  Si el DataFrame está vacío, si la estrategia
                         es UPSERT sin key_columns, o si alguna columna
                         de key_columns no existe en el DataFrame.
            Exception:   Si la operación SQL falla por cualquier motivo.

        Example:
            >>> rows = loader.load(df, schema="raw", table="work_items")
            >>> print(f"{rows} filas cargadas.")
        """
        self._validate_load_params(df, strategy, key_columns)

        fqn = self._fqn(schema, table)
        logger.debug(
            "Iniciando carga de %d filas en %s (estrategia: %s)...",
            len(df), fqn, strategy.value,
        )

        self._ensure_table_exists(df, schema, table)

        match strategy:
            case LoadStrategy.TRUNCATE_INSERT:
                self._truncate_insert(df, schema, table, batch_size)
            case LoadStrategy.INSERT:
                self._insert(df, schema, table, batch_size)
            case LoadStrategy.UPSERT:
                self._upsert(df, schema, table, key_columns)  # type: ignore[arg-type]
            case LoadStrategy.INSERT_OR_FAIL:
                self._insert_or_fail(df, schema, table, batch_size)

        rows = len(df)
        logger.debug("Carga completada: %d filas en %s.", rows, fqn)
        return rows

    def _truncate_insert(
        self,
        df: pd.DataFrame,
        schema: str,
        table: str,
        batch_size: int,
    ) -> None:
        """
        Vacía la tabla y la recarga completamente con los datos del DataFrame.

        El TRUNCATE y el INSERT se ejecutan dentro de transacciones
        separadas de forma intencionada:

        - TRUNCATE TABLE no puede ejecutarse dentro de una transacción
          en SQL Server cuando la tabla tiene restricciones de clave
          foránea activas. Al separarlo, se evitan errores en ese caso.
        - pandas.to_sql gestiona internamente su propia transacción
          por lotes, lo que es más eficiente que un único INSERT masivo.

        Args:
            df:         DataFrame a cargar.
            schema:     Esquema de la tabla destino.
            table:      Nombre de la tabla destino.
            batch_size: Filas por lote en la inserción.
        """
        fqn = self._fqn(schema, table)
        logger.debug("TRUNCATE_INSERT → truncando %s...", fqn)

        with self._engine.begin() as conn:
            conn.execute(text(f"TRUNCATE TABLE {fqn}"))

        logger.debug("TRUNCATE_INSERT → insertando %d filas...", len(df))

        df.to_sql(
            name=table,
            con=self._engine,
            schema=schema,
            if_exists="append",   # La tabla ya existe y acaba de ser truncada
            index=False,
            chunksize=batch_size,
        )

    def _insert(
        self,
        df: pd.DataFrame,
        schema: str,
        table: str,
        batch_size: int,
    ) -> None:
        """
        Añade las filas del DataFrame al final de la tabla sin
        modificar las filas existentes.

        Args:
            df:         DataFrame a cargar.
            schema:     Esquema de la tabla destino.
            table:      Nombre de la tabla destino.
            batch_size: Filas por lote en la inserción.
        """
        logger.debug("INSERT → añadiendo %d filas a %s...", len(df), self._fqn(schema, table))

        df.to_sql(
            name=table,
            con=self._engine,
            schema=schema,
            if_exists="append",
            index=False,
            chunksize=batch_size,
        )

    def _upsert(
        self,
        df: pd.DataFrame,
        schema: str,
        table: str,
        key_columns: List[str],
    ) -> None:
        """
        Actualiza las filas existentes e inserta las nuevas usando T-SQL MERGE.

        Proceso en tres pasos dentro de una única transacción:
            1. Carga el DataFrame en una tabla temporal (#_upsert_staging).
            2. Ejecuta un MERGE entre la tabla temporal y la tabla destino,
               comparando por las columnas clave.
            3. La tabla temporal se elimina automáticamente al cerrar
               la conexión (comportamiento estándar de las tablas #temp
               en SQL Server).

        El MERGE es la instrucción T-SQL nativa para este patrón y
        es más eficiente que hacer un SELECT + UPDATE/INSERT por separado,
        ya que procesa todas las filas en una única pasada sobre los datos.

        Args:
            df:          DataFrame a cargar.
            schema:      Esquema de la tabla destino.
            table:       Nombre de la tabla destino.
            key_columns: Columnas que identifican unívocamente cada fila.
        """
        fqn        = self._fqn(schema, table)
        temp_table = "#_upsert_staging"

        all_columns     = list(df.columns)
        update_columns  = [c for c in all_columns if c not in key_columns]

        # Condición ON del MERGE: igualdad en todas las columnas clave
        on_clause = " AND ".join(
            f"target.[{col}] = source.[{col}]" for col in key_columns
        )

        # SET del WHEN MATCHED: actualizar todas las columnas no clave
        set_clause = ", ".join(
            f"target.[{col}] = source.[{col}]" for col in update_columns
        )

        # Columnas e valores del INSERT
        insert_cols   = ", ".join(f"[{col}]" for col in all_columns)
        insert_values = ", ".join(f"source.[{col}]" for col in all_columns)

        merge_sql = f"""
            MERGE {fqn} AS target
            USING {temp_table} AS source
            ON ({on_clause})
            WHEN MATCHED THEN
                UPDATE SET {set_clause}
            WHEN NOT MATCHED BY TARGET THEN
                INSERT ({insert_cols})
                VALUES ({insert_values});
        """

        logger.debug(
            "UPSERT → tabla temporal + MERGE sobre %s (claves: %s)...",
            fqn, key_columns,
        )

        # Toda la operación en una única transacción: o todo bien o nada
        with self._engine.begin() as conn:
            # Paso 1: cargar en tabla temporal (solo existe en esta conexión)
            df.to_sql(
                name=temp_table,
                con=conn,
                if_exists="replace",
                index=False,
            )

            # Paso 2: MERGE desde la temporal a la tabla definitiva
            conn.execute(text(merge_sql))

    def _insert_or_fail(
        self,
        df: pd.DataFrame,
        schema: str,
        table: str,
        batch_size: int,
    ) -> None:
        """
        Inserta las filas del DataFrame y falla si alguna ya existe.

        Delega en pandas.to_sql con if_exists='append', que a su vez
        usa INSERT estándar. Si la tabla tiene una PRIMARY KEY o un
        índice UNIQUE definido en SQL Server y alguna fila viola esa
        restricción, SQL Server lanza un error que se propaga como
        excepción de SQLAlchemy.

        Esta estrategia es útil como mecanismo de validación: si el
        proceso llega aquí con datos duplicados, es un error de proceso
        que debe detectarse y corregirse explícitamente.

        Args:
            df:         DataFrame a cargar.
            schema:     Esquema de la tabla destino.
            table:      Nombre de la tabla destino.
            batch_size: Filas por lote en la inserción.

        Raises:
            Exception: Si SQL Server rechaza alguna fila por duplicidad
                       u otra violación de restricción de integridad.
        """
        logger.debug(
            "INSERT_OR_FAIL → insertando %d filas en %s (falla si hay duplicados)...",
            len(df), self._fqn(schema, table),
        )

        df.to_sql(
            name=table,
            con=self._engine,
            schema=schema,
            if_exists="append",
            index=False,
            chunksize=batch_size,
        )

    def _ensure_table_exists(
        self,
        df: pd.DataFrame,
        schema: str,
        table: str,
    ) -> None:
        """
        Crea el esquema y la tabla si no existen, infiriendo los tipos
        SQL desde los dtypes del DataFrame.

        La creación es idempotente: si la tabla ya existe, no hace nada.
        Si el esquema no existe, lo crea antes que la tabla.

        La inferencia de tipos sigue la tabla de equivalencias documentada
        en el módulo. Para tipos desconocidos, usa NVARCHAR(MAX) como
        tipo seguro por defecto.

        Args:
            df:     DataFrame cuyo esquema se usa como referencia.
            schema: Esquema SQL Server donde crear la tabla.
            table:  Nombre de la tabla a crear.
        """
        fqn = self._fqn(schema, table)
        logger.debug("Verificando existencia de %s...", fqn)

        ddl_schema = (
            f"IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = '{schema}') "
            f"EXEC('CREATE SCHEMA [{schema}]')"
        )

        col_definitions = self._infer_column_definitions(df)
        columns_ddl     = ",\n        ".join(col_definitions)

        ddl_table = f"""
            IF NOT EXISTS (
                SELECT 1
                FROM   sys.tables  t
                JOIN   sys.schemas s ON t.schema_id = s.schema_id
                WHERE  s.name = '{schema}' AND t.name = '{table}'
            )
            BEGIN
                CREATE TABLE {fqn} (
                    {columns_ddl}
                )
            END
        """

        with self._engine.begin() as conn:
            conn.execute(text(ddl_schema))
            conn.execute(text(ddl_table))

        logger.debug("Tabla %s lista.", fqn, dest=Dest.FILE)

    @staticmethod
    def _infer_column_definitions(df: pd.DataFrame) -> List[str]:
        """
        Genera las definiciones de columna T-SQL inferidas desde los
        dtypes del DataFrame.

        Tabla de equivalencias pandas → T-SQL:

            int64, Int64      → BIGINT
            int32, Int32      → INT
            int16, Int16      → SMALLINT
            int8,  Int8       → TINYINT
            float32           → REAL
            float64           → FLOAT
            bool, boolean     → BIT
            datetime64[*]     → DATETIME2
            timedelta64[*]    → BIGINT  (nanosegundos; convertir en SQL)
            object, string    → NVARCHAR(MAX)
            category          → NVARCHAR(255)
            otros             → NVARCHAR(MAX)  (tipo seguro por defecto)

        Todas las columnas se crean como NULL para maximizar la
        compatibilidad con DataFrames que tienen valores ausentes.

        Args:
            df: DataFrame del que inferir los tipos.

        Returns:
            Lista de strings con las definiciones de columna T-SQL,
            listas para incluir en un CREATE TABLE.

        Example:
            ['[id] BIGINT NULL', '[nombre] NVARCHAR(MAX) NULL', ...]
        """
        type_map = {
            "int8":          "TINYINT",
            "Int8":          "TINYINT",
            "int16":         "SMALLINT",
            "Int16":         "SMALLINT",
            "int32":         "INT",
            "Int32":         "INT",
            "int64":         "BIGINT",
            "Int64":         "BIGINT",
            "float32":       "REAL",
            "float64":       "FLOAT",
            "bool":          "BIT",
            "boolean":       "BIT",
            "object":        "NVARCHAR(MAX)",
            "string":        "NVARCHAR(MAX)",
            "category":      "NVARCHAR(255)",
        }

        definitions = []

        for col, dtype in df.dtypes.items():
            dtype_name = str(dtype)

            # Normalizar variantes de datetime (ej. datetime64[ns], datetime64[us, UTC])
            if dtype_name.startswith("datetime64"):
                sql_type = "DATETIME2"
            elif dtype_name.startswith("timedelta"):
                sql_type = "BIGINT"
            else:
                sql_type = type_map.get(dtype_name, "NVARCHAR(MAX)")

            definitions.append(f"[{col}] {sql_type} NULL")

        return definitions

    @staticmethod
    def _validate_load_params(
        df: pd.DataFrame,
        strategy: LoadStrategy,
        key_columns: List[str] | None,
    ) -> None:
        """
        Valida los parámetros de la llamada a load() antes de operar.

        Comprobaciones:
            1. El DataFrame no puede estar vacío.
            2. La estrategia UPSERT requiere key_columns.
            3. Todas las key_columns deben existir en el DataFrame.

        Args:
            df:          DataFrame a validar.
            strategy:    Estrategia de carga seleccionada.
            key_columns: Columnas clave (solo requeridas para UPSERT).

        Raises:
            ValueError: Si alguna validación falla.
        """
        if df.empty:
            raise ValueError(
                "El DataFrame está vacío. No hay datos que cargar."
            )

        if strategy == LoadStrategy.UPSERT:
            if not key_columns:
                raise ValueError(
                    "La estrategia UPSERT requiere el parámetro 'key_columns' "
                    "con al menos una columna clave. "
                    "Ejemplo: key_columns=['id']"
                )

            missing_cols = [c for c in key_columns if c not in df.columns]
            if missing_cols:
                raise ValueError(
                    f"Las siguientes columnas clave no existen en el DataFrame: "
                    f"{missing_cols}. "
                    f"Columnas disponibles: {list(df.columns)}"
                )

    @staticmethod
    def _fqn(schema: str, table: str) -> str:
        """
        Construye el nombre completamente cualificado de la tabla
        en formato T-SQL con corchetes: [esquema].[tabla].

        Los corchetes son necesarios para escapar correctamente nombres
        que contengan espacios, palabras reservadas o caracteres especiales.

        Args:
            schema: Nombre del esquema.
            table:  Nombre de la tabla.

        Returns:
            String con el FQN entre corchetes.

        Example:
            >>> SqlLoader._fqn("raw", "work_items")
            '[raw].[work_items]'
        """
        return f"[{schema}].[{table}]"
