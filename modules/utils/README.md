# Módulo Utils
En este módulo se gestionan todas aquellas funcionalidades que son transversales al proyecto. A continuación se describe el funcionamiento de cada fichero incorporado en este módulo.

## Índice
1. [`config.py` — Gestión centralizada de la configuración](#configpy--gestión-centralizada-de-la-configuración)
2. [`formatters.py` — Funciones auxiliares de formateo](#formatterspy--funciones-auxiliares-de-formateo)
3. [`logger.py` — Sistema de logging centralizado](#loggerpy--sistema-de-logging-centralizado)

## `config.py` — Gestión centralizada de la configuración
Este módulo es el punto de entrada único para toda la configuración del proyecto. Su responsabilidad es reunir, validar y entregar en un solo objeto (`AppConfig`) todo lo que el resto de módulos necesitan para funcionar: las URLs de Azure DevOps, los parámetros de conexión a SQL Server, los campos a extraer y las credenciales de acceso. La información se obtiene de dos fuentes distintas, con una separación clara según su sensibilidad:
- **Fichero `.env`** → Configuración no sensible (URLs, nombres de servidor, timeouts, IDs de tarjetas, campos de extracción).
- **Windows Credential Manager** → Credenciales sensibles (PAT de Azure, usuario y contraseña de SQL Server), almacenadas cifradas en el sistema operativo.

### Constantes del módulo
Exportadas para que otros módulos puedan importar los nombres estándar de las claves del Credential Manager sin escribirlos literalmente:

| Constante | Valor | Descripción |
|---|---|---|
| `CREDENTIAL_KEY_PAT` | `"azure_pat"` | Clave de la PAT de Azure DevOps en el Credential Manager |
| `CREDENTIAL_KEY_SQL_LOGIN` | `"sql_login"` | Clave del login de SQL Server en el Credential Manager |

### Variables del fichero `.env`

#### Obligatorias

| Variable | Descripción |
|---|---|
| `AZURE_DEVOPS_ORG_URL` | URL base de la organización en Azure DevOps |
| `AZURE_DEVOPS_PROJECT` | Nombre del proyecto en Azure DevOps |
| `SQL_SERVER` | Nombre del servidor o instancia SQL Server |
| `SQL_DATABASE` | Nombre de la base de datos de destino |

#### Opcionales (con valor por defecto)

| Variable | Por defecto | Descripción |
|---|---|---|
| `AZURE_ROOT_IDS` | `""` (lista vacía) | IDs raíz a procesar, separados por comas (ej. `12120,13450`) |
| `AZURE_FIELDS` | `""` (lista vacía) | Campos adicionales de Azure DevOps a extraer, separados por comas. Se **concatenan** a `_DEFAULT_FIELDS` del extractor. Si no se define, el extractor usa únicamente sus campos predeterminados. |
| `SQL_SCHEMA` | `"raw"` | Esquema de destino para la tabla de tarjetas |
| `SQL_TABLE` | `"azuTarjetas"` | Tabla de destino para las tarjetas |
| `SQL_LOG_SCHEMA` | `"raw"` | Esquema de destino para la tabla de logs |
| `SQL_LOG_TABLE` | `"LogsPython"` | Tabla de destino para los logs de ejecución |
| `SQL_STORED_PROCEDURE` | `"dbo.SP_AzureModelo"` | Procedimiento almacenado a ejecutar tras la carga |
| `SQL_WINDOWS_AUTH_TIMEOUT` | `3` | Segundos máximos para el intento de Windows Authentication |

#### Credenciales opcionales de fallback rápido (menos seguras)
Permiten configurar credenciales directamente en el `.env` sin pasar por el Credential Manager. **Recomendadas solo en entornos de prueba o desarrollo.** No subir el `.env` a Git si contiene credenciales reales.

| Variable | Descripción |
|---|---|
| `AZURE_DEVOPS_PAT` | PAT de Azure DevOps en texto plano. Si está definida, se usa directamente. |
| `SQL_USER` | Usuario de SQL Server. Solo se usa si `SQL_PASSWORD` también está definida. |
| `SQL_PASSWORD` | Contraseña de SQL Server. Solo se usa si `SQL_USER` también está definida. |

> ⚠️ Si solo una de las dos variables SQL está definida (sin su par), se emite un `WARNING` y se ignoran ambas.

### Cadena de prioridad para la resolución de credenciales

#### PAT de Azure DevOps
```
Prioridad 1 — AZURE_DEVOPS_PAT en el .env
    │   Si está definida → se usa directamente (WARNING emitido)
    │
    ▼ Si no está en el .env:
Prioridad 2 — Windows Credential Manager
    En la primera ejecución se solicita al usuario por consola.
    En ejecuciones posteriores se recupera automáticamente.
```

#### Credenciales SQL Server
```
Prioridad 1 — SQL_USER + SQL_PASSWORD en el .env
    │   Si ambas están definidas → se usan directamente (WARNING emitido)
    │   Si solo una → WARNING y se ignoran ambas
    │
    ▼ Si no están en el .env:
Prioridad 2 — Windows Authentication
    │   Prueba de conexión con timeout configurable.
    │   Si tiene éxito → sql_user y sql_password serán None.
    │
    ▼ Si Windows Auth falla:
Prioridad 3 — Windows Credential Manager
    En la primera ejecución se solicitan al usuario por consola.
    En ejecuciones posteriores se recuperan automáticamente.
```

### Clase `AppConfig`
Contenedor tipado (dataclass) que agrupa toda la configuración del proyecto en un único objeto. Es el resultado que devuelve `load_config()` y el que consume el resto de módulos.

#### Atributos

| Atributo | Tipo | Descripción |
|---|---|---|
| `azure_org_url` | `str` | URL base de la organización en Azure DevOps |
| `azure_project` | `str` | Nombre del proyecto en Azure DevOps |
| `azure_pat` | `str` | Personal Access Token de Azure DevOps |
| `azure_root_ids` | `List[int]` | IDs raíz a procesar. Lista vacía si no se define `AZURE_ROOT_IDS` |
| `azure_fields` | `List[str]` | Campos adicionales a extraer. Lista vacía si no se define `AZURE_FIELDS`; el extractor usará en ese caso sus campos predeterminados |
| `sql_server` | `str` | Nombre del servidor o instancia SQL Server |
| `sql_database` | `str` | Nombre de la base de datos de destino |
| `sql_user` | `Optional[str]` | Usuario SQL. `None` si se usa Windows Authentication |
| `sql_password` | `Optional[str]` | Contraseña SQL. `None` si se usa Windows Authentication |
| `sql_dest_schema` | `str` | Esquema de destino para la tabla de tarjetas |
| `sql_dest_table` | `str` | Tabla de destino para las tarjetas |
| `sql_log_schema` | `str` | Esquema de destino para los logs |
| `sql_log_table` | `str` | Tabla de destino para los logs |
| `sql_stored_procedure` | `str` | Procedimiento almacenado a ejecutar tras la carga |
| `sql_windows_auth_timeout` | `int` | Timeout en segundos para la prueba de Windows Auth |

### Funciones

#### `load_config() → AppConfig`
Función principal del módulo. Carga, valida y combina toda la configuración del proyecto en un único objeto `AppConfig`.

**Proceso interno:**
1. Lee las variables no sensibles del fichero `.env`.
2. Valida que todas las variables obligatorias están presentes.
3. Carga la PAT de Azure mediante `_load_pat()`.
4. Resuelve las credenciales SQL mediante `_load_sql_credentials()`.
5. Construye y devuelve el objeto `AppConfig`.

**Returns:** `AppConfig` con toda la configuración lista para usar.

**Raises:**
- `ValueError` — Si alguna variable obligatoria del `.env` no está definida, o si `SQL_WINDOWS_AUTH_TIMEOUT` contiene un valor inválido.
- `SystemExit` — Si el usuario no introduce alguna credencial cuando se le solicita en la primera ejecución.

#### `_load_pat() → str`
*(Función privada — uso interno)*. Resuelve la PAT de Azure DevOps siguiendo su cadena de prioridad: `.env` primero, Credential Manager si no está definida en el `.env`.

| Parámetro | Tipo | Descripción |
|---|---|---|
| `env_pat` | `Optional[str]` | Valor de `AZURE_DEVOPS_PAT` leído del `.env`, o `None` si no está definida. |

**Returns:** PAT de Azure DevOps en texto plano.

#### `_load_sql_credentials() → tuple[Optional[str], Optional[str]]`
*(Función privada — uso interno)*. Resuelve las credenciales SQL siguiendo su cadena de prioridad: `.env` → Windows Auth → Credential Manager.

| Parámetro | Tipo | Descripción |
|---|---|---|
| `server` | `str` | Nombre del servidor SQL (del `.env`) |
| `database` | `str` | Nombre de la base de datos (del `.env`) |
| `timeout` | `int` | Segundos máximos para el intento de Windows Auth |
| `sql_user` | `Optional[str]` | Valor de `SQL_USER` del `.env`, o `None` |
| `sql_password` | `Optional[str]` | Valor de `SQL_PASSWORD` del `.env`, o `None` |

**Returns:**
- `(None, None)` si Windows Authentication está disponible.
- `(user, password)` en cualquier otro caso con credenciales válidas.

#### `_probe_windows_auth() → bool`
*(Función privada — uso interno)*. Intenta una conexión de prueba a SQL Server con Windows Authentication, delegando en `SqlConnection.test_connection()`. Completamente silenciosa para el usuario: no lanza excepciones ni muestra mensajes en pantalla. Todos los detalles quedan en el fichero `.log`.

| Parámetro | Tipo | Descripción |
|---|---|---|
| `server` | `str` | Nombre del servidor o instancia SQL Server |
| `database` | `str` | Nombre de la base de datos de destino |
| `timeout` | `int` | Segundos máximos antes de considerar la prueba fallida |

**Returns:** `True` si la conexión con Windows Auth fue exitosa, `False` en cualquier otro caso.

#### `_parse_timeout() → int`
*(Función privada — uso interno)*. Parsea el valor de `SQL_WINDOWS_AUTH_TIMEOUT` desde el `.env`. Si está vacío, devuelve `3` como valor por defecto.

| Parámetro | Tipo | Descripción |
|---|---|---|
| `raw` | `str` | String leído del `.env`. Puede estar vacío. |

**Returns:** Timeout en segundos como entero positivo.

**Raises:** `ValueError` si el valor no es un entero positivo.

#### `_parse_root_ids() → List[int]`
*(Función privada — uso interno)*. Parsea la cadena de IDs separados por comas en una lista de enteros. Filtra entradas vacías para tolerar comas finales o espacios.

| Parámetro | Tipo | Descripción |
|---|---|---|
| `raw` | `str` | String con los IDs separados por comas (ej. `'12120,13450'`). |

**Returns:** Lista de enteros. Lista vacía si el string está vacío.

**Raises:** `ValueError` si algún valor no puede convertirse a entero.

```python
_parse_root_ids("12120,13450,14200")  # → [12120, 13450, 14200]
_parse_root_ids("")                   # → []
```

#### `_parse_fields() → List[str]`
*(Función privada — uso interno)*. Parsea la cadena de campos separados por comas en una lista de strings. Filtra entradas vacías para tolerar comas finales, espacios en blanco o líneas múltiples en el `.env`. Si la variable no está definida o está vacía, devuelve una lista vacía. El extractor interpretará una lista vacía como indicación de usar sus campos predeterminados.

| Parámetro | Tipo | Descripción |
|---|---|---|
| `raw` | `str` | String con los campos separados por comas leído del `.env`. |

**Returns:** Lista de strings con los nombres de campo sin espacios extra. Lista vacía si el string está vacío.

```python
_parse_fields("System.Id,System.Title,Custom.Area")
# → ['System.Id', 'System.Title', 'Custom.Area']

_parse_fields("System.Id, System.Title , ")
# → ['System.Id', 'System.Title']

_parse_fields("")
# → []
```

### Dependencias
| Librería | Versión mínima | Uso |
|---|---|---|
| `python-dotenv` | >= 1.0 | Lectura del fichero `.env` |
| `modules.credentials` | - | Acceso al Windows Credential Manager |
| `modules.sql.connection` | - | Prueba de conectividad con Windows Auth |
| `modules.utils.logger` | - | Registro de eventos durante la carga de configuración |

## `formatters.py` — Funciones auxiliares de formateo
Contiene un conjunto de funciones auxiliares de transformación y formateo de datos extraídas de `AzureDevOpsExtractor`. Su existencia responde al **principio de responsabilidad única (SRP)**: cada función hace una sola cosa, lo que facilita su mantenimiento, reutilización y prueba independiente. Estas funciones se utilizan en `azure_extractor.py` durante el proceso de normalización de cada work item recibido desde la API de Azure DevOps.

### Funciones

#### `extract_identity() → Optional[str]`

Extrae el nombre de usuario legible de un campo de identidad devuelto por la API de Azure DevOps. Los campos de identidad (como `AssignedTo` o `CreatedBy`) pueden llegar de dos formas distintas dependiendo de la versión de la API y el contexto:
- Como **diccionario** con la clave `uniqueName` (forma habitual).
- Como **string** directo.

La función normaliza ambos casos devolviendo siempre un string o `None`.
| Parámetro | Tipo | Descripción |
|---|---|---|
| `identity_field` | `Any` | Campo de identidad devuelto por la API de Azure |

**Returns:** Nombre de usuario legible (`uniqueName` si es diccionario, el propio string en otro caso), o `None` si el campo está vacío.

**Ejemplo:**
```python
# Entrada como diccionario (caso habitual)
extract_identity({"uniqueName": "user@empresa.com", "displayName": "Usuario"})
# → "user@empresa.com"

# Entrada como string
extract_identity("user@empresa.com")
# → "user@empresa.com"

# Campo vacío
extract_identity(None)
# → None
```

#### `format_date() → Optional[str]`
Convierte un campo de fecha al formato ISO 8601 en forma de string. La API de Azure DevOps puede devolver las fechas como objetos `datetime` de Python o como strings. La función normaliza ambas formas para garantizar coherencia en el DataFrame resultante.

| Parámetro | Tipo | Descripción |
|---|---|---|
| `date_field` | `Any` | Fecha devuelta por la API. Puede ser `datetime`, `str` o `None`. |

**Returns:** Fecha en formato ISO 8601 (ej. `"2026-02-22T10:01:00"`), o `None` si el campo está vacío.

**Ejemplo:**
```python
from datetime import datetime
format_date(datetime(2026, 2, 22, 10, 1, 0))
# → "2026-02-22T10:01:00"

format_date("2026-02-22T10:01:00.000Z")
# → "2026-02-22T10:01:00.000Z"

format_date(None)
# → None
```

#### `parse_tags() → List[str]`
Convierte el campo de etiquetas de Azure DevOps (una cadena de texto con los tags separados por punto y coma) en una lista limpia de strings. Azure DevOps almacena las etiquetas en un único campo de texto con el formato `"tag1; tag2; tag3"`. Esta función lo divide y elimina espacios sobrantes.

| Parámetro | Tipo | Descripción |
|---|---|---|
| `tags_field` | `Any` | String de etiquetas separadas por punto y coma, o `None`. |

**Returns:** Lista de etiquetas sin espacios extra. Lista vacía si no hay etiquetas o el campo está vacío.

**Ejemplo:**
```python
parse_tags("backend; api; urgente")
# → ["backend", "api", "urgente"]

parse_tags("")
# → []

parse_tags(None)
# → []
```

#### `extract_parent_id() → Optional[int]`
Extrae el ID numérico de la tarjeta padre a partir de la lista de relaciones de un work item. En Azure DevOps, la relación con el padre se representa mediante el tipo de vínculo `System.LinkTypes.Hierarchy-Reverse`. El ID del padre se obtiene parseando la URL de esa relación, que sigue el patrón `.../workItems/{id}`.

| Parámetro | Tipo | Descripción |
|---|---|---|
| `relations` | `Any` | Lista de objetos de relación devueltos por la API. Puede ser `None` si la tarjeta no tiene relaciones. |

**Returns:** ID entero del padre directo, o `None` si la tarjeta no tiene padre o no se pudo parsear el ID. Si el parseo de la URL falla por un formato inesperado, se emite un `WARNING` en el log y se devuelve `None`.

**Ejemplo:**
```
URL de relación: '.../workItems/42'  →  devuelve 42
```

### Dependencias
| Librería | Uso |
|---|---|
| `modules.utils.logger` | Registro de advertencias si falla el parseo de `extract_parent_id` |

## `logger.py` — Sistema de logging centralizado
Este módulo proporciona un sistema de logging (registro de eventos) centralizado y reutilizable para todo el proyecto. Extiende el sistema estándar de logging de Python añadiendo funcionalidades específicas:

- **Niveles de log enriquecidos** con códigos de estado HTTP para facilitar el diagnóstico.
- **Métricas de sistema en tiempo real** (CPU y RAM) adjuntas a cada mensaje.
- **Destino configurable por mensaje**: consola, fichero `.log` o ambos.
- **Compatibilidad con barras de progreso** `tqdm` para evitar solapamientos visuales.
- **Fichero rotativo** con límite de tamaño (máximo 5 MB por fichero, hasta 3 copias de respaldo).
- **Captura opcional a DataFrame de pandas**, listo para exportar a una tabla SQL al final de la ejecución.
- **Identificador único de ejecución** (UUID v4) y usuario del sistema operativo generados automáticamente.

El fichero `.log` se genera en el directorio raíz del proyecto (directorio de trabajo actual al ejecutar `main.py`).

### Configuración interna

| Constante | Valor | Descripción |
|---|---|---|
| `_PROJECT_NAME` | `"Azure-Boards-Manager"` | Nombre del proyecto, usado como raíz del árbol de loggers |
| `_LOG_FILE_NAME` | `"Azure-Boards-Manager.log"` | Nombre del fichero de log |
| `_LOG_DIR` | `os.getcwd()` | Directorio donde se crea el fichero `.log` (raíz del proyecto) |
| `_MAX_BYTES` | `5 MB` | Tamaño máximo por fichero antes de rotar |
| `_BACKUP_COUNT` | `3` | Número máximo de copias de respaldo del `.log` |
| `_DATE_FORMAT` | `"%Y-%m-%d %H:%M:%S"` | Formato de fecha en los mensajes |

### Niveles de log y códigos HTTP
El módulo extiende los niveles estándar de Python con un nivel personalizado (`OK`) y asocia a cada nivel un código de estado HTTP para facilitar la clasificación de mensajes:

| Nivel | Valor numérico | Código HTTP | Texto HTTP | Uso |
|---|---|---|---|---|
| `DEBUG` | 10 | 102 | Processing | Detalles internos de ejecución. Solo aparece en fichero, no en consola. |
| `INFO` | 20 | 200 | OK | Eventos informativos del proceso (inicio, IDs en proceso, totales...) |
| `OK` | 25 | 201 | Created | Confirmación explícita de operación exitosa (carga SQL, SP ejecutado...) |
| `WARNING` | 30 | 400 | Bad Request | Situaciones anómalas que no interrumpen el proceso |
| `ERROR` | 40 | 500 | Internal Server Error | Errores que pueden interrumpir o degradar el proceso |

El nivel `OK` (valor 25) es un nivel **personalizado** situado entre `INFO` y `WARNING`, creado específicamente para confirmar operaciones completadas con éxito de forma explícita.

### Formato de salida
Cada mensaje de log sigue este formato tanto en consola como en fichero:

```
2026-02-22 10:01:00 | OK      | 201 | Created               | CPU: 12.31% | RAM: 45.23% | modules.main | Mensaje
```

Campos en orden:
1. Fecha y hora
2. Nivel del log
3. Código HTTP
4. Texto HTTP
5. Uso de CPU del proceso en ese instante
6. Uso de RAM del proceso en ese instante
7. Módulo que genera el mensaje
8. Texto del mensaje

### Destinos de salida — Enum `Dest`
Controla dónde se escribe cada mensaje. Se pasa como parámetro `dest` en cada llamada al logger.

```python
from modules.utils.logger import Dest

logger.info("Solo en pantalla",  dest=Dest.CONSOLE)
logger.info("Solo en fichero",   dest=Dest.FILE)
logger.info("En ambos sitios",   dest=Dest.BOTH)    # valor por defecto
```

| Valor | Consola | Fichero | DataFrame SQL |
|---|---|---|---|
| `Dest.CONSOLE` | ✅ | ❌ | ❌ |
| `Dest.FILE` | ❌ | ✅ | ✅ |
| `Dest.BOTH` | ✅ | ✅ | ✅ |

Los mensajes con `dest=Dest.CONSOLE` no se capturan en el DataFrame ni se escriben en fichero. Esto evita que separadores visuales (líneas de `═`, banners...) contaminen la tabla SQL con ruido sin valor analítico.

### Uso básico

```python
from modules.utils.logger import get_logger, Dest

logger = get_logger(__name__)

logger.debug("Lote procesado: IDs 1-200")
logger.info("Conexión establecida con Azure DevOps")
logger.ok("Carga completada: 342 filas insertadas en raw.azuTarjetas")
logger.warning("Se han alcanzado 19.800 resultados, cerca del límite")
logger.error("No se pudo conectar a SQL Server")

# Destino explícito
logger.info("Solo en pantalla",  dest=Dest.CONSOLE)
logger.info("Solo en fichero",   dest=Dest.FILE)
```

### Uso con captura a DataFrame (para volcado a SQL)
Solo debe activarse en `main.py`. Al hacerlo, se generan automáticamente el UUID de la ejecución y el usuario del SO, y se imprime el banner de inicio en consola.

```python
from modules.utils.logger import get_logger, get_log_dataframe, get_execution_id

logger = get_logger(__name__, capture_to_df=True)

# ... ejecución del proceso ...

log_df = get_log_dataframe()    # Obtener el DataFrame con todos los mensajes capturados
exec_id = get_execution_id()    # UUID v4 de esta ejecución
```

### Esquema del DataFrame de logs
Cuando se activa `capture_to_df=True`, cada mensaje de log (excepto los de `Dest.CONSOLE` y nivel `DEBUG`) se acumula en un DataFrame con esta estructura:

| Columna | Tipo pandas | Tipo SQL Server | Descripción |
|---|---|---|---|
| `Id_Ejecucion` | `object` | `NVARCHAR(36)` | UUID v4 de la ejecución |
| `Usuario_Ejecucion` | `object` | `NVARCHAR(100)` | Usuario del SO que ejecutó el proceso |
| `Nombre_Proyecto` | `object` | `NVARCHAR(100)` | Nombre del proyecto (`Azure-Boards-Manager`) |
| `Timestamp` | `datetime64` | `DATETIME2` | Fecha y hora del mensaje |
| `Nivel` | `object` | `NVARCHAR(10)` | Nivel del log (`INFO`, `OK`, `WARNING`...) |
| `Codigo_HTTP` | `int64` | `INT` | Código HTTP asociado al nivel |
| `Modulo` | `object` | `NVARCHAR(200)` | Módulo que generó el mensaje |
| `Mensaje` | `object` | `NVARCHAR(MAX)` | Texto del mensaje |
| `CPU_Porcentaje` | `float64` | `FLOAT` | Uso de CPU del proceso en el momento del mensaje |
| `RAM_Porcentaje` | `float64` | `FLOAT` | Uso de RAM del proceso en el momento del mensaje |

### Funciones de la interfaz pública

#### `get_logger() → _ProjectLogger`
Único punto de entrada que deben usar todos los módulos del proyecto para obtener su logger.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `name` | `str` | — | Nombre del módulo. Usar siempre `__name__`. |
| `capture_to_df` | `bool` | `False` | Activa la captura a DataFrame y el banner de inicio. Solo debe usarse en `main.py`. |

**Returns:** `_ProjectLogger` con los métodos `debug()`, `info()`, `ok()`, `warning()`, `error()` y el parámetro `dest` disponibles.

**Raises:** `TypeError` si `name` no es un string no vacío.

#### `get_log_dataframe() → pandas.DataFrame`
Construye y devuelve el DataFrame con todos los mensajes capturados desde el inicio de la ejecución. Llamar al final del proceso, antes de volcar los datos a SQL.

**Returns:** `pandas.DataFrame` con las columnas del esquema descrito arriba. DataFrame vacío si no hay registros.

**Raises:** `ImportError` si `pandas` no está instalado.

#### `get_execution_id() → str`
Devuelve el UUID v4 de la ejecución actual, generado en el momento en que se llamó a `get_logger(__name__, capture_to_df=True)`.

**Returns:** UUID como string, o cadena vacía si la captura no está activa.

#### `get_execution_user() → str`
Devuelve el nombre del usuario del sistema operativo bajo el que se está ejecutando el proceso.

**Returns:** Nombre de usuario como string, o cadena vacía si la captura no está activa.

#### Clase `_ProjectLogger`
*(Clase interna — no instanciar directamente. Usar `get_logger()`)*

Extiende `logging.Logger` para añadir:
- El parámetro `dest` en todos los métodos de log.
- El método personalizado `ok()`.
- La captura automática al DataFrame cuando `capture_to_df=True`.

#### Métodos de log
Todos aceptan los mismos parámetros base:

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `msg` | `str` | — | Mensaje a registrar. Acepta placeholders `%s`, `%d`... |
| `*args` | `Any` | — | Argumentos para el formateo del mensaje con `%` |
| `dest` | `Dest` | `Dest.BOTH` | Destino de salida del mensaje |

| Método | Nivel | Cuándo usarlo |
|---|---|---|
| `debug()` | DEBUG | Detalles internos de ejecución. Solo aparece en fichero. |
| `info()` | INFO | Eventos generales del proceso |
| `ok()` | OK | Confirmación explícita de operación completada con éxito |
| `warning()` | WARNING | Situaciones anómalas no bloqueantes |
| `error()` | ERROR | Errores que pueden degradar o interrumpir el proceso |

### Clase `Dest`
Enum que define los posibles destinos de salida de un mensaje. Ver sección [Destinos de salida](#destinos-de-salida--enum-dest).

### Reutilización en otros proyectos
Este módulo está diseñado para ser autocontenido y portátil:
1. Copiar el fichero en `modules/utils/logger.py` del proyecto destino.
2. Ajustar `_PROJECT_NAME` y `_LOG_FILE_NAME`.
3. Verificar que `psutil`, `tqdm` y `pandas` están en `requirements.txt`.

### Dependencias
| Librería | Versión mínima | Uso |
|---|---|---|
| `psutil` | >= 6.0 | Métricas de CPU y RAM en tiempo real |
| `tqdm` | >= 4.0 | Detección de barra de progreso activa para evitar solapamientos visuales |
| `pandas` | >= 2.0 | DataFrame de logs (solo si `capture_to_df=True`) |
