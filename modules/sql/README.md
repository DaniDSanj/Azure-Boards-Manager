# Módulo SQL
En este módulo se gestionan todas aquellas funcionalidades que son transversales al proyecto. A continuación se describe el funcionamiento de cada fichero incorporado en este módulo.

## Índice
1. [`__init__.py` — Interfaz pública del módulo SQL](#__init__py--interfaz-pública-del-módulo-sql)
2. [`connection.py` — Gestión de conexiones a SQL Server](#connectionpy--gestión-de-conexiones-a-sql-server)
3. [`executor.py` — Ejecución de consultas y procedimientos almacenados](#executorpy--ejecución-de-consultas-y-procedimientos-almacenados)
4. [`loader.py` — Carga de DataFrames en SQL Server](#loaderpy--carga-de-dataframes-en-sql-server)

## `__init__.py` — Interfaz pública del módulo SQL
Este fichero es la puerta de entrada al módulo SQL del proyecto. Define qué puede importarse desde fuera y expone una función de conveniencia (`create_sql_client`) que construye todos los componentes necesarios para operar con SQL Server en una única llamada. En lugar de instanciar `SqlConnection`, `SqlLoader` y `SqlExecutor` por separado, el 95% de los casos de uso quedan cubiertos con esta función de conveniencia.

### Uso recomendado — `create_sql_client`

```python
from modules.sql import create_sql_client

loader, executor = create_sql_client(
    server="mi_servidor",
    database="mi_bd",
)

## Cargar un DataFrame
loader.load(df, schema="raw", table="azuTarjetas")

## Ejecutar una consulta
rows = executor.execute_query("SELECT COUNT(*) AS total FROM raw.azuTarjetas")

## Ejecutar una consulta desde fichero
rows = executor.execute_query_from_file("resumen.sql")

## Ejecutar un procedimiento almacenado
result = executor.execute_procedure("dbo.SP_AzureModelo")
```

### Uso avanzado — acceso directo a las clases
Para casos que requieran mayor control: reutilizar una conexión en varios módulos, configurar un directorio base de SQL diferente, o gestionar múltiples bases de datos simultáneamente.

```python
from modules.sql import SqlConnection, SqlLoader, SqlExecutor
from pathlib import Path

conn     = SqlConnection(server="srv", database="bd")
loader   = SqlLoader(engine=conn.engine)
executor = SqlExecutor(
    engine=conn.engine,
    sql_base_dir=Path("ruta/personalizada/sql"),
)
```

### Función `create_sql_client`
Construye y devuelve un `SqlLoader` y un `SqlExecutor` listos para usar, compartiendo el mismo engine de conexión subyacente.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `server` | `str` | — | Nombre del servidor o instancia SQL Server. Ejemplos: `'mi_servidor'`, `'localhost\\SQLEXPRESS'`. |
| `database` | `str` | — | Nombre de la base de datos de destino. |
| `username` | `Optional[str]` | `None` | Usuario SQL Server. `None` activa Windows Authentication. |
| `password` | `Optional[str]` | `None` | Contraseña SQL Server. `None` activa Windows Authentication. |
| `sql_base_dir` | `Path \| str` | `./input/sql/` | Directorio base para los ficheros `.sql`. |

**Returns:** Tupla `(SqlLoader, SqlExecutor)` listos para operar, compartiendo la misma conexión subyacente.

**Raises:**
- `ValueError` — Si se proporciona `username` sin `password` o viceversa.
- `ConnectionError` — Si la conexión a SQL Server falla.

### Estrategias de carga disponibles

`LoadStrategy` se importa desde este módulo y se usa como parámetro en `loader.load()`:

```python
from modules.sql import LoadStrategy

loader.load(df, schema="raw", table="azuTarjetas",
            strategy=LoadStrategy.TRUNCATE_INSERT)   ## por defecto

loader.load(df, schema="raw", table="LogsPython",
            strategy=LoadStrategy.INSERT)

loader.load(df, schema="dbo", table="clientes",
            strategy=LoadStrategy.UPSERT,
            key_columns=["id_cliente"])

loader.load(df, schema="dbo", table="facturas",
            strategy=LoadStrategy.INSERT_OR_FAIL)
```

| Estrategia | Comportamiento |
|---|---|
| `TRUNCATE_INSERT` | Vacía la tabla y la recarga desde cero |
| `INSERT` | Añade filas sin modificar las existentes |
| `UPSERT` | Actualiza existentes e inserta nuevas (T-SQL `MERGE`) |
| `INSERT_OR_FAIL` | Inserta o falla si hay duplicados |

### Exportaciones públicas del módulo

| Símbolo | Tipo | Descripción |
|---|---|---|
| `create_sql_client` | Función | Construye `loader` + `executor` en una llamada (uso recomendado) |
| `SqlConnection` | Clase | Gestión de conexiones (uso avanzado) |
| `SqlLoader` | Clase | Carga de DataFrames (uso avanzado) |
| `SqlExecutor` | Clase | Ejecución de consultas y SPs (uso avanzado) |
| `LoadStrategy` | Enum | Estrategias de carga disponibles |

Cualquier símbolo no listado aquí es un detalle de implementación interno y no forma parte de la interfaz pública del módulo.

## `connection.py` — Gestión de conexiones a SQL Server
Este módulo es el responsable exclusivo de construir, validar y entregar una conexión a SQL Server lista para usar. Su única salida es un objeto `engine` de SQLAlchemy que el resto de módulos (`SqlLoader`, `SqlExecutor`) utilizan sin necesidad de conocer ningún detalle sobre cómo se creó la conexión. El módulo abstrae completamente:
- La selección del modo de autenticación (Windows o SQL Server).
- La construcción de la cadena de conexión ODBC.
- La validación de la conexión en el momento de la construcción.

### Modos de autenticación

#### Windows Authentication (Trusted Connection)
El proceso Python se autentica contra SQL Server usando la cuenta de Windows del usuario actual. **No requiere usuario ni contraseña.** Se activa automáticamente cuando `username` y `password` son `None`.

```python
conn = SqlConnection(server="mi_servidor", database="mi_bd")
```

#### SQL Server Authentication
Requiere usuario y contraseña explícitos. Útil en entornos donde el proceso no corre bajo una cuenta de dominio con acceso a SQL Server (servidores compartidos, pipelines CI/CD, etc.). Se activa cuando `username` y `password` tienen valor.

```python
conn = SqlConnection(
    server="mi_servidor",
    database="mi_bd",
    username="sa",
    password="mi_contraseña",
)
```

### Clase `SqlConnection`
Fábrica de conexiones a SQL Server mediante SQLAlchemy + pyodbc. Valida la conexión en el momento de la construcción mediante un `SELECT 1`, fallando rápido si algo no está configurado correctamente.

#### Constructor `__init__()`

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `server` | `str` | — | Nombre del servidor o instancia SQL Server. Ejemplos: `'mi_servidor'`, `'localhost\\SQLEXPRESS'`, `'192.168.1.10,1433'`. |
| `database` | `str` | — | Nombre de la base de datos de destino. |
| `username` | `Optional[str]` | `None` | Usuario SQL Server. `None` activa Windows Authentication. |
| `password` | `Optional[str]` | `None` | Contraseña SQL Server. `None` activa Windows Authentication. |

**Raises:**
- `ValueError` — Si se proporciona `username` sin `password` o viceversa.
- `ConnectionError` — Si la conexión o la prueba `SELECT 1` fallan.

**Atributos públicos tras la construcción:**

| Atributo | Tipo | Descripción |
|---|---|---|
| `engine` | `sqlalchemy.engine.Engine` | Engine de SQLAlchemy validado y listo para usar por `SqlLoader` y `SqlExecutor`. |

#### `test_connection() → bool`
Ejecuta una prueba de conectividad sobre el engine existente. Útil para verificar que la conexión sigue activa después de un período de inactividad.

**Returns:** `True` si el engine responde correctamente a `SELECT 1`, `False` en cualquier otro caso.

```python
if not conn.test_connection():
    logger.warning("La conexión SQL ha caído.")
```

### Métodos privados

#### `_build_and_validate_engine(username, password) → Engine`
*(Uso interno)*. Construye el engine de SQLAlchemy y lo valida con un `SELECT 1`. Si algo falla, lanza `ConnectionError` con un mensaje detallado que indica el servidor, la base de datos, el modo de autenticación y el error original.

#### `_build_connection_url(username, password) → str`
*(Uso interno)*. Construye la cadena de conexión SQLAlchemy en el formato `mssql+pyodbc:///?odbc_connect=...`, que es la forma recomendada en SQLAlchemy 2.x para evitar problemas con caracteres especiales en el nombre del servidor o la contraseña. Para SQL Server Authentication, la contraseña se codifica con `quote_plus` para escapar correctamente caracteres especiales (`@`, `#`, `%`...).

#### `_validate_auth_params(username, password)`
*(Uso interno — método estático)*. Valida que los parámetros de autenticación son coherentes antes de intentar la conexión:
- Ambos `None` → Windows Authentication. ✅
- Ambos con valor → SQL Server Authentication. ✅
- Solo uno con valor → configuración incompleta. ❌ Lanza `ValueError`.

### Driver ODBC
Se busca dentro del sistema el driver más reciente. Si no se enceuntra, por defecto se usa `"ODBC Driver 17 for SQL Server"`, ya que es el más extendido y estable. Para listar los drivers ODBC instalados en el sistema:

```python
import pyodbc
print(pyodbc.drivers())
```

### Dependencias

| Librería | Versión mínima | Uso |
|---|---|---|
| `SQLAlchemy` | >= 2.0 | Construcción del engine y gestión de conexiones |
| `pyodbc` | >= 5.0 | Driver de bajo nivel para la conexión ODBC con SQL Server |

## `executor.py` — Ejecución de consultas y procedimientos almacenados
Este módulo es el responsable de ejecutar sentencias SQL y procedimientos almacenados contra SQL Server, devolviendo los resultados en un formato uniforme y predecible. Acepta las sentencias de dos formas:
- **Embebidas en Python** como strings directamente en el código.
- **En ficheros `.sql`** almacenados en el directorio `./input/sql/`.

Su responsabilidad se limita exclusivamente a la ejecución: no gestiona credenciales ni conexiones (eso es responsabilidad de `SqlConnection`), ni realiza cargas masivas de DataFrames (eso corresponde a `SqlLoader`).

### Parámetros seguros — Protección contra SQL injection
Siempre se deben usar **parámetros enlazados** en lugar de interpolar valores directamente en la cadena SQL, especialmente cuando los valores provienen de entrada del usuario.

```python
## ✅ Forma correcta: parámetros enlazados con sintaxis :nombre
executor.execute_query(
    "SELECT * FROM dbo.clientes WHERE id = :id AND activo = :activo",
    params={"id": 42, "activo": True}
)

## ❌ Forma INCORRECTA: vulnerable a SQL injection
executor.execute_query(f"SELECT * FROM dbo.clientes WHERE id = {id}")
```

Para procedimientos almacenados, los parámetros se pasan por nombre sin el prefijo `@`:

```python
executor.execute_procedure(
    "dbo.usp_get_cliente",
    params={"id_cliente": 42}
)
```

### Ficheros `.sql`

Los ficheros `.sql` se resuelven desde el directorio base `./input/sql/` relativo a la raíz del proyecto. Se admiten rutas relativas con subdirectorios dentro del directorio base.

```
./input/sql/
    consulta_clientes.sql
    merge_work_items.sql
    subdir/
        otra_consulta.sql   ← accesible como "subdir/otra_consulta.sql"
```

El directorio base puede sobreescribirse con el parámetro `sql_base_dir` en el constructor, lo que resulta útil en pruebas o en proyectos con estructura de carpetas diferente.

### Clase `SqlExecutor`

#### Constructor `__init__(engine, sql_base_dir)`

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `engine` | `sqlalchemy.engine.Engine` | — | Engine de SQLAlchemy obtenido desde `SqlConnection`. |
| `sql_base_dir` | `Path \| str` | `./input/sql/` | Directorio base para la resolución de ficheros `.sql`. |

**Raises:** `TypeError` si `engine` no es una instancia válida de `Engine`.

### Métodos públicos

#### `execute_query(sql, params) → List[Dict[str, Any]]`
Ejecuta una consulta SQL pasada como string y devuelve los resultados como lista de diccionarios.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `sql` | `str` | — | Sentencia SQL. Puede contener parámetros con sintaxis `:nombre`. |
| `params` | `Dict[str, Any] \| None` | `None` | Diccionario de parámetros enlazados. `None` si la consulta no tiene parámetros. |

**Returns:** Lista de diccionarios donde cada elemento es una fila (clave = nombre de columna). Lista vacía si la consulta no produce filas (`INSERT`, `UPDATE`, `DELETE`, DDL...).

**Raises:**
- `ValueError` — Si `sql` es `None` o está vacío.
- `Exception` — Si la ejecución SQL falla.

```python
rows = executor.execute_query(
    "SELECT id, nombre FROM dbo.clientes WHERE activo = :activo",
    params={"activo": True}
)
for row in rows:
    print(row["id"], row["nombre"])
```

#### `execute_query_from_file(filename, params) → List[Dict[str, Any]]`
Carga un fichero `.sql` desde el directorio base y lo ejecuta. Acepta los mismos parámetros que `execute_query`. El fichero se lee con **detección automática de encoding**: se intentan `UTF-8-BOM`, `UTF-8` y `Latin-1` en ese orden. Esto garantiza compatibilidad tanto con ficheros creados en Linux como con los guardados desde SQL Server Management Studio en Windows, que añaden un BOM invisible al inicio.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `filename` | `str` | — | Nombre del fichero con extensión. Puede incluir subdirectorios relativos al directorio base. Ejemplos: `"informe.sql"`, `"monthly/ventas.sql"`. |
| `params` | `Dict[str, Any] \| None` | `None` | Parámetros enlazados, igual que en `execute_query`. |

**Returns:** Lista de diccionarios con los resultados. Lista vacía si la consulta no devuelve filas.

**Raises:**
- `FileNotFoundError` — Si el fichero no existe en la ruta resuelta.
- `ValueError` — Si el fichero está vacío.
- `Exception` — Si la ejecución SQL falla.

```python
rows = executor.execute_query_from_file(
    "resumen_mensual.sql",
    params={"anio": 2025, "mes": 6}
)
```

#### `execute_procedure(name, params) → List[Dict[str, Any]] | bool`
Ejecuta un procedimiento almacenado y devuelve el resultado. Gestiona automáticamente los **múltiples result sets** que SQL Server puede devolver durante la ejecución de un SP (mensajes de progreso, contadores intermedios, resultado final). Devuelve el primer result set que contenga filas de datos.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `name` | `str` | — | Nombre completo del SP incluyendo esquema. Ejemplo: `'dbo.SP_AzureModelo'`. |
| `params` | `Dict[str, Any] \| None` | `None` | Parámetros del SP como diccionario. Las claves deben coincidir con los nombres de los parámetros del SP (sin el `@` inicial). |

**Returns:**
- `List[Dict[str, Any]]` — Si el SP devolvió al menos un result set con filas.
- `True` — Si el SP se ejecutó sin errores pero no devolvió filas.
- `False` — Si el SP lanzó una excepción durante la ejecución.

**Raises:** `ValueError` — Si `name` es `None` o está vacío.

```python
## SP que devuelve datos
result = executor.execute_procedure(
    "dbo.usp_get_resumen",
    params={"anio": 2025}
)
if isinstance(result, list):
    for row in result:
        print(row)

## SP sin retorno de datos (uso habitual en este proyecto)
ok = executor.execute_procedure("dbo.SP_AzureModelo")
if ok:
    logger.ok("Procedimiento ejecutado correctamente.")
else:
    logger.error("El procedimiento falló.")
```

### Métodos privados

#### `_run_query(sql, params) → List[Dict[str, Any]]`
Ejecuta una sentencia SQL distinguiendo automáticamente entre consultas de solo lectura (`SELECT`) y sentencias que modifican datos (`INSERT`, `UPDATE`, `DELETE`, `MERGE`, DDL...). Las primeras se ejecutan sin transacción explícita; las segundas, con `begin()`.

#### `_run_procedure(name, params) → List[Dict[str, Any]] | bool`
Ejecuta el procedimiento almacenado con `SET NOCOUNT ON` (para suprimir los mensajes intermedios de filas afectadas) y navega por todos los result sets devueltos hasta encontrar el primero con datos.

#### `_build_exec_sql(name, params) → str`
*(Método estático)*. Construye la sentencia `EXEC` con parámetros nombrados en el formato nativo de pyodbc (`@param = ?`). Protege contra SQL injection incluso en llamadas a procedimientos almacenados.

```python
_build_exec_sql("dbo.usp_test", {"id": 1, "activo": True})
## → 'EXEC dbo.usp_test @id = ?, @activo = ?'
```

#### `_consume_result_sets(cursor) → List[Dict[str, Any]]`
*(Método estático)*. Navega por todos los result sets de un cursor pyodbc y devuelve el primero que contenga filas. Garantiza que el cursor no queda en un estado pendiente incluso cuando SQL Server emite múltiples result sets antes del resultado final.

#### `_cursor_to_dicts(result) → List[Dict[str, Any]]`
*(Método estático)*. Convierte el resultado de una ejecución SQLAlchemy en una lista de diccionarios. Devuelve lista vacía sin lanzar excepción si el resultado no tiene columnas (sentencias sin `SELECT`).

#### `_resolve_sql_file(filename) → Path`

Resuelve la ruta completa de un fichero `.sql` a partir de su nombre relativo al directorio base.

**Raises:** `FileNotFoundError` si el fichero no existe en la ruta resuelta.

#### `_read_sql_file(filepath) → str`
*(Método estático)*. Lee el contenido de un fichero `.sql` con detección automática de encoding (`utf-8-sig` → `utf-8` → `latin-1`).

**Raises:**
- `ValueError` — Si el fichero está vacío.
- `OSError` — Si no se puede leer con ningún encoding soportado.

#### `_validate_sql(sql)`
*(Método estático)*. Valida que la sentencia SQL no es `None` ni está vacía.

**Raises:** `ValueError` si `sql` es `None`, vacío o contiene solo espacios.

### Dependencias

| Librería | Versión mínima | Uso |
|---|---|---|
| `SQLAlchemy` | >= 2.0 | Ejecución de consultas y gestión de transacciones |
| `pyodbc` | >= 5.0 | Acceso nativo al cursor para navegar por múltiples result sets |

## `loader.py` — Carga de DataFrames en SQL Server
Este módulo es el responsable de recibir un DataFrame de pandas ya transformado y cargarlo en una tabla de SQL Server. Aplica la estrategia de carga indicada por el llamante y crea la tabla automáticamente si no existe. Su responsabilidad se limita exclusivamente a la carga de datos: no gestiona credenciales ni cadenas de conexión (eso es responsabilidad de `SqlConnection`), ni ejecuta consultas o procedimientos almacenados (eso corresponde a `SqlExecutor`).

### Estrategias de carga — Enum `LoadStrategy`
El enum `LoadStrategy` controla cómo se comporta la carga en función del estado previo de la tabla. Hereda de `str` para que sus valores sean comparables directamente con strings y serializables a JSON sin conversión adicional.

| Estrategia | Valor | Comportamiento | Cuándo usarla |
|---|---|---|---|
| `TRUNCATE_INSERT` | `"truncate_insert"` | Vacía la tabla completamente y la recarga desde cero. | Tablas de staging o raw donde siempre se carga el conjunto completo de datos. **Valor por defecto.** |
| `INSERT` | `"insert"` | Añade las filas al final sin modificar las existentes. | Tablas de log o histórico donde nunca se reescriben datos anteriores. |
| `UPSERT` | `"upsert"` | Actualiza filas existentes (por clave) e inserta las nuevas. Implementado con T-SQL `MERGE`. | Cuando los datos pueden llegar con actualizaciones parciales sobre registros ya cargados. |
| `INSERT_OR_FAIL` | `"insert_or_fail"` | Inserta filas nuevas y falla si alguna ya existe. | Como mecanismo de validación cuando la duplicidad es un error de proceso que debe detectarse explícitamente. |

```python
from modules.sql import LoadStrategy

## Comparación directa con string (gracias a la herencia de str)
LoadStrategy.TRUNCATE_INSERT == "truncate_insert"   ## → True
```

### Creación automática de tabla
Si la tabla de destino no existe, `SqlLoader` la crea automáticamente antes de la carga, inferiendo los tipos de columna SQL desde los `dtypes` del DataFrame:

| Tipo pandas | Tipo SQL Server |
|---|---|
| `int8`, `Int8` | `TINYINT` |
| `int16`, `Int16` | `SMALLINT` |
| `int32`, `Int32` | `INT` |
| `int64`, `Int64` | `BIGINT` |
| `float32` | `REAL` |
| `float64` | `FLOAT` |
| `bool`, `boolean` | `BIT` |
| `datetime64[*]` | `DATETIME2` |
| `timedelta64[*]` | `BIGINT` (nanosegundos) |
| `object`, `string` | `NVARCHAR(MAX)` |
| `category` | `NVARCHAR(255)` |
| Otros | `NVARCHAR(MAX)` (tipo seguro por defecto) |

> Todas las columnas se crean como `NULL` para maximizar la compatibilidad con DataFrames que contienen valores ausentes.
> Para columnas de texto con longitud máxima conocida, se recomienda ajustar el DDL manualmente después del primer despliegue.

### Clase `SqlLoader`

#### Constructor `__init__(engine)`

| Parámetro | Tipo | Descripción |
|---|---|---|
| `engine` | `sqlalchemy.engine.Engine` | Engine de SQLAlchemy obtenido desde `SqlConnection`. |

**Raises:** `TypeError` si `engine` no es una instancia válida de `Engine`.

#### `load(df, schema, table, strategy, key_columns, batch_size) → int`
Método principal. Carga el DataFrame en la tabla indicada aplicando la estrategia especificada.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `df` | `pd.DataFrame` | — | DataFrame con los datos a cargar. No puede estar vacío. |
| `schema` | `str` | — | Esquema SQL Server de destino (ej. `'raw'`, `'dbo'`). |
| `table` | `str` | — | Nombre de la tabla de destino. |
| `strategy` | `LoadStrategy` | `TRUNCATE_INSERT` | Estrategia de carga a aplicar. |
| `key_columns` | `List[str] \| None` | `None` | Columnas que identifican unívocamente cada fila. **Obligatorio solo para `UPSERT`**. Ejemplo: `['Id']`, `['id_cliente', 'fecha']`. |
| `batch_size` | `int` | `500` | Número de filas por lote en las inserciones. |

**Returns:** Número de filas procesadas en la carga.

**Raises:**
- `ValueError` — Si el DataFrame está vacío, si la estrategia es `UPSERT` sin `key_columns`, o si alguna columna de `key_columns` no existe en el DataFrame.
- `Exception` — Si la operación SQL falla por cualquier motivo.

**Ejemplos de uso:**

```python
from modules.sql import create_sql_client, LoadStrategy

loader, executor = create_sql_client(server="srv", database="bd")

## Reemplazar toda la tabla (uso más habitual)
loader.load(df, schema="raw", table="azuTarjetas")

## Acumular registros sin borrar los existentes (ej. tabla de logs)
loader.load(df, schema="raw", table="LogsPython",
            strategy=LoadStrategy.INSERT)

## Actualizar existentes e insertar nuevas (por clave primaria)
loader.load(df, schema="dbo", table="clientes",
            strategy=LoadStrategy.UPSERT,
            key_columns=["id_cliente"])

## Insertar o fallar si hay duplicados
loader.load(df, schema="dbo", table="facturas",
            strategy=LoadStrategy.INSERT_OR_FAIL)
```

### Implementación interna de las estrategias

#### `_truncate_insert`
Vacía la tabla con `TRUNCATE TABLE` y la recarga con `pandas.to_sql`. El truncado y la inserción se ejecutan en **transacciones separadas** de forma intencionada: `TRUNCATE` no puede ejecutarse dentro de una transacción en SQL Server cuando la tabla tiene restricciones de clave foránea activas.

#### `_insert`
Añade filas al final de la tabla con `pandas.to_sql` usando `if_exists='append'`.

#### `_upsert`
Implementa el patrón upsert en tres pasos dentro de una **única transacción**:

1. Carga el DataFrame en una tabla temporal (`#_upsert_staging`).
2. Ejecuta un `MERGE` T-SQL entre la temporal y la tabla destino, comparando por las columnas clave.
3. La tabla temporal se elimina automáticamente al cerrar la conexión (comportamiento estándar de las tablas `#temp` en SQL Server).

El `MERGE` es la instrucción T-SQL nativa para este patrón: más eficiente que hacer `SELECT + UPDATE/INSERT` por separado, ya que procesa todas las filas en una única pasada.

#### `_insert_or_fail`
Delega en `pandas.to_sql` con `if_exists='append'`. Si la tabla tiene una `PRIMARY KEY` o un índice `UNIQUE` y alguna fila lo viola, SQL Server lanza un error que se propaga como excepción de SQLAlchemy.

### Métodos privados de utilidad

#### `_ensure_table_exists(df, schema, table)`
Crea el esquema y la tabla si no existen, infiriendo los tipos SQL desde los `dtypes` del DataFrame. La operación es idempotente: si la tabla ya existe, no hace nada.

#### `_infer_column_definitions(df) → List[str]`
*(Método estático)*. Genera las definiciones de columna T-SQL a partir de los `dtypes` del DataFrame, siguiendo la tabla de equivalencias documentada arriba. Devuelve una lista de strings del tipo `['[Id] BIGINT NULL', '[Titulo] NVARCHAR(MAX) NULL', ...]`.

#### `_validate_load_params(df, strategy, key_columns)`
*(Método estático)*. Valida los parámetros antes de operar:
1. El DataFrame no puede estar vacío.
2. La estrategia `UPSERT` requiere `key_columns`.
3. Todas las `key_columns` deben existir en el DataFrame.

#### `_fqn(schema, table) → str`
*(Método estático)*. Construye el nombre completamente cualificado de la tabla en formato T-SQL con corchetes: `[esquema].[tabla]`. Los corchetes escapan correctamente nombres con espacios, palabras reservadas o caracteres especiales.

```python
SqlLoader._fqn("raw", "azuTarjetas")   ## → '[raw].[azuTarjetas]'
```

### Dependencias

| Librería | Versión mínima | Uso |
|---|---|---|
| `pandas` | >= 2.0 | Manipulación del DataFrame y escritura con `to_sql` |
| `SQLAlchemy` | >= 2.0 | Ejecución de DDL y gestión de transacciones |
| `pyodbc` | >= 5.0 | Driver de bajo nivel para la conexión con SQL Server |
