## Módulo Pipeline
Este módulo se encarga de realizar el proceso ETL, desde la extracción de los datos desde la plataforma Azure Boards del proyecto hasta tener los datos limpios en un dataframe. Para ello, se han preparado dos ficheros:
- **`./azure_extractor.py`**: Permite extraer los datos requeridos por el usuario desde Azure Boards.
- **`./transformer.py.`**: Realiza las transformaciones y limpieza de datos necesarias para un posterior análisis.

### Índice
1. [`azure_extractor.py` — Extracción de tarjetas desde Azure Boards](#azure_extractorpy--extracción-de-tarjetas-desde-azure-boards)
2. [`transformer.py` — Transformación y calidad del dato](#transformerpy--transformación-y-calidad-del-dato)

## `azure_extractor.py` — Extracción de tarjetas desde Azure Boards
Este módulo implementa `AzureDevOpsExtractor`, la clase responsable de conectarse a Azure DevOps y recuperar work items (tarjetas) desde Azure Boards. Soporta múltiples modos de consulta: por jerarquía de épica, por etiquetas, por tipo de tarjeta o mediante consultas WIQL personalizadas. La autenticación se realiza mediante **Personal Access Token (PAT)**. Una vez conectado, el extractor gestiona automáticamente el límite de 200 IDs por petición que impone la API, procesando los work items en lotes transparentes para el llamante.

### Constantes del módulo

| Constante | Valor | Descripción |
|---|---|---|
| `_BATCH_SIZE` | `200` | Límite de IDs por petición de detalle impuesto por la API de Azure DevOps |
| `_WIQL_MAX_RESULTS` | `20.000` | Límite de resultados por consulta WIQL. Si se alcanza, se emite un `WARNING` |

### Campos predeterminados — `_DEFAULT_FIELDS`
Lista de campos que el extractor solicitará por defecto a la API. Incluye los siguientes campos estándar del sistema presentes en todos los tipos de work item:

| Campo API | Campo resultado | Descripción |
|---|---|---|
| `System.Id` | `Id` | Identificador único de la tarjeta |
| `System.WorkItemType` | `Tipo` | Tipo de tarjeta (Epic, Feature, User Story, Task...) |
| `System.Title` | `Titulo` | Título de la tarjeta |
| `System.State` | `Estado` | Estado actual (New, Active, Closed...) |
| `System.AssignedTo` | `UsuarioAsignado` | Usuario asignado a la tarjeta |
| `System.CreatedBy` | `UsuarioCreacion` | Usuario que creó la tarjeta |
| `System.CreatedDate` | `FechaCreacion` | Fecha de creación (ISO 8601) |
| `System.ChangedDate` | `FechaModificacion` | Fecha de última modificación (ISO 8601) |
| `System.Tags` | `Etiquetas` | Lista de etiquetas (normalizada desde string separado por `;`) |
| `System.AreaPath` | `Area` | Ruta de área del proyecto |
| `System.IterationPath` | `Iteracion` | Ruta de iteración (sprint) |
| `System.Description` | `Descripcion` | Descripción en texto plano (HTML limpiado en `transformer.py`) |
| `Microsoft.VSTS.Common.Priority` | `Prioridad` | Prioridad numérica |
| `Microsoft.VSTS.Common.AcceptanceCriteria` | `CriteriosAceptacion` | Criterios de aceptación en texto plano |
| *(relaciones)* | `IdPadre` | ID numérico de la tarjeta padre directa |

⚠️ Si se quieren incluir campos personalizados (`Custom.*`) u otros campos que no sean los mencionados anteriormente, pueden incluirse en la extracción simplemente añádiéndolos en la variable `AZURE_FIELDS` del `.env` separados por comas, como se muestra en el siguiente ejemplo:
```env
 AZURE_FIELDS=Custom.Campo1,Custom.Campo2,...
```

### Clase `AzureDevOpsExtractor`

#### Constructor `__init__()`
Inicializa la conexión con Azure DevOps y configura la lista de campos a extraer.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `organization_url` | `str` | — | URL base de la organización (ej. `'https://dev.azure.com/mi-org'`). |
| `project_name` | `str` | — | Nombre del proyecto en Azure DevOps. |
| `personal_access_token` | `str` | — | PAT con permisos de lectura en Work Items. |
| `fields` | `Optional[List[str]]` | `None` | Campos adicionales a extraer en cada petición. Si es `None` o lista vacía, se usa `_DEFAULT_FIELDS` como fallback. Si se proporcionan, se **concatenan** a `_DEFAULT_FIELDS`. |

**Lógica de resolución de campos en el constructor:**
```
fields proporcionados
    │
    ├── None o vacío → self._fields = _DEFAULT_FIELDS
    │
    └── Con valor    → self._fields = _DEFAULT_FIELDS + fields
```

**Raises:** `ConnectionError` — Si la conexión con Azure DevOps falla.

**Atributos públicos tras la construcción:**

| Atributo | Tipo | Descripción |
|---|---|---|
| `organization_url` | `str` | URL base de la organización |
| `project_name` | `str` | Nombre del proyecto activo |
| `_fields` | `List[str]` | Lista efectiva de campos usada en todas las peticiones |

### Métodos públicos de consulta
Todos los métodos de consulta aceptan un parámetro `fields` opcional que **sobrescribe puntualmente** `self._fields` para esa llamada concreta. Si es `None`, se usa `self._fields`.

#### `get_all_work_items() → List[Dict[str, Any]]`
Recupera todos los work items del proyecto sin filtro adicional, ordenados por fecha de creación descendente.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `fields` | `Optional[List[str]]` | `None` | Sobrescribe puntualmente los campos a recuperar en esta llamada. |

**Returns:** Lista de diccionarios con los datos de cada work item.

#### `get_work_items_by_id() → List[Dict[str, Any]]`
Recupera una tarjeta y **todos sus descendientes en cualquier nivel de jerarquía** (Epic → Feature → User Story → Task → Sub-task...). La búsqueda es recursiva gracias al modificador `MODE (Recursive)` de WIQL: se obtienen todos los niveles de profundidad en una sola consulta. La tarjeta raíz indicada por `root_id` se incluye siempre en los resultados.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `root_id` | `int` | — | ID numérico de la tarjeta raíz. Puede ser cualquier tipo: Epic, Feature, User Story, etc. |
| `fields` | `Optional[List[str]]` | `None` | Sobrescribe puntualmente los campos a recuperar en esta llamada. |

**Returns:** Lista de diccionarios que incluye la tarjeta raíz y todos sus descendientes.

**Raises:** `Exception` — Si la consulta a Azure DevOps falla.

```python
# Obtener una épica con todas sus features, historias y tareas
items = extractor.get_work_items_by_id(root_id=12120)
```

#### `get_work_items_by_tags() → List[Dict[str, Any]]`
Recupera work items filtrados por etiquetas.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `tags` | `List[str]` | — | Lista de etiquetas por las que filtrar (ej. `['urgente', 'backend']`). |
| `match_all` | `bool` | `False` | `True` → el work item debe tener **todas** las etiquetas. `False` → basta con que tenga **alguna**. |
| `fields` | `Optional[List[str]]` | `None` | Sobrescribe puntualmente los campos a recuperar. |

**Returns:** Lista de work items que cumplen el criterio de etiquetas.

#### `get_work_items_by_type() → List[Dict[str, Any]]`
Recupera work items de un tipo específico.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `work_item_type` | `str` | — | Tipo exacto del work item (ej. `'Bug'`, `'User Story'`, `'Task'`, `'Epic'`). |
| `fields` | `Optional[List[str]]` | `None` | Sobrescribe puntualmente los campos a recuperar. |

**Returns:** Lista de work items del tipo indicado.

#### `get_work_items_by_query() → List[Dict[str, Any]]`
Ejecuta una **consulta WIQL personalizada**. Útil para casos de uso avanzados no cubiertos por los métodos anteriores.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `wiql_query` | `str` | — | Consulta WIQL completa en formato string. |
| `fields` | `Optional[List[str]]` | `None` | Sobrescribe puntualmente los campos a recuperar. |

**Returns:** Lista de work items resultado de la consulta.

### Método de exportación

#### `export_to_json() → str`
Exporta los work items a un fichero JSON con nombre estructurado en el directorio `output/`. El directorio se crea automáticamente si no existe. El nombre del fichero sigue el patrón:
```
work_items_{root_id}_{yyyymmdd_hhmmss}.json
```
Ejemplo: `work_items_12120_20260217_143022.json`

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `work_items` | `List[Dict[str, Any]]` | — | Lista de work items a exportar. |
| `root_id` | `int` | — | ID de la tarjeta raíz ejecutada, incluido en el nombre del fichero. |
| `output_dir` | `str` | `"output"` | Directorio de salida. Siempre será `output/`. |

**Returns:** Ruta completa del fichero generado.

**Raises:** `Exception` — Si la escritura del fichero falla.

### Métodos privados

#### `_execute_flat_query(wiql_query, fields, context) → List[Dict[str, Any]]`
Ejecuta una consulta WIQL plana (`FROM WorkItems`) y devuelve los work items con detalle completo. Gestiona el límite de 20.000 resultados: si se alcanza, emite un `WARNING` indicando que los datos pueden estar incompletos y sugiriendo acotar la consulta con filtros adicionales.

#### `_fetch_work_items_batch(work_item_ids, fields) → List[Dict[str, Any]]`
Recupera los detalles completos de una lista de work items en **lotes de 200** para respetar el límite de la API. Por cada lote realiza dos llamadas:
1. Una para obtener los campos de datos (usando `self._fields` si `fields` es `None`).
2. Otra para obtener las relaciones (necesarias para extraer `IdPadre`).

Si un lote falla por `AzureDevOpsServiceError`, se registra el error en el log y se continúa con el siguiente lote.

#### `_format_work_item(work_item) → Dict[str, Any]`
Convierte un objeto work item de la API en el diccionario limpio con los nombres de campo en español que se usarán en SQL Server. Aplica las funciones auxiliares de `formatters.py` para normalizar identidades, fechas, etiquetas e ID de padre.

### Dependencias
| Librería | Versión mínima | Uso |
|---|---|---|
| `azure-devops` | >= 7.1 | Cliente oficial de la API de Azure DevOps |
| `msrest` | >= 0.7 | Autenticación mediante PAT (`BasicAuthentication`) |
| `modules.utils.formatters` | - | Normalización de identidades, fechas, etiquetas e ID de padre |
| `modules.utils.logger` | - | Registro de eventos durante la extracción |

## `transformer.py` — Transformación y calidad del dato
Este módulo implementa `WorkItemTransformer`, la clase responsable de convertir la lista de work items en crudo devuelta por `AzureDevOpsExtractor` en un DataFrame de pandas limpio, validado y listo para su carga en SQL Server. El transformador aplica un pipeline de cinco pasos en orden fijo: conversión a DataFrame, validación de calidad, eliminación de columnas, limpieza de HTML y normalización de etiquetas.

### Constantes del módulo

| Constante | Valor actual | Descripción |
|---|---| ---| 
| `_COLUMNS_TO_DROP` | `[]` | Columnas que se eliminan antes de la carga. Vacía por diseño: no hay columnas que eliminar en la versión actual, pero está preparada para añadir en el futuro. |
| `_HTML_COLUMNS` | `["Descripcion", "CriteriosAceptacion"]` | Columnas de texto que pueden contener HTML y deben limpiarse. |
| `_PK_COLUMN` | `"Id"` | Columna que actúa como clave primaria. No puede ser nula ni duplicada. |

### Clase `WorkItemTransformer`

#### Uso típico
```python
from modules.pipeline.transformer import WorkItemTransformer

transformer = WorkItemTransformer()
df = transformer.transform(work_items)
```

### Método público

#### `transform() → pd.DataFrame`
Ejecuta el pipeline completo de transformación y validación sobre la lista de work items.

| Parámetro | Tipo | Descripción |
|---|---| ---| 
| `work_items` | `List[Dict[str, Any]]` | Lista de diccionarios devuelta por `AzureDevOpsExtractor`. |

**Returns:** DataFrame de pandas con los datos transformados y validados, listo para `SqlLoader`.

**Raises:** `ValueError` — Si la lista de work items está vacía.

#### Pasos del pipeline (en orden de ejecución)
```
1. Conversión a DataFrame
        │
        ▼
2. Validación de calidad
   · Elimina filas con Id nulo
   · Elimina filas duplicadas por Id
        │
        ▼
3. Eliminación de columnas innecesarias
   · Columnas definidas en _COLUMNS_TO_DROP
        │
        ▼
4. Limpieza de HTML
   · Campos: Descripcion, CriteriosAceptacion, etc.
        │
        ▼
5. Normalización de etiquetas
   · Lista Python → VARCHAR separado por comas
```

### Métodos privados del pipeline

#### `_validate_quality(df) → pd.DataFrame`
Aplica dos validaciones de calidad sobre el DataFrame, ambas registradas en el log con el número de filas descartadas para trazabilidad:

1. **Nulos en `Id`**: elimina filas cuyo campo `Id` sea nulo.
2. **Duplicados por `Id`**: elimina filas duplicadas conservando la primera ocurrencia (la más reciente según el orden de extracción).

Si no se descarta ninguna fila, registra un mensaje `DEBUG` confirmando que la validación fue superada. Si se descartan filas, emite un `WARNING` con el total.

#### `_drop_unnecessary_columns(df) → pd.DataFrame`
Elimina las columnas definidas en `_COLUMNS_TO_DROP`. Si alguna de ellas no existe en el DataFrame, se ignora silenciosamente para evitar errores en extracciones parciales.

⚠️ Actualmente `_COLUMNS_TO_DROP` está vacía por diseño. Para excluir una columna de la carga a SQL Server basta con añadir su nombre a esta lista.

#### `_clean_html_fields(df) → pd.DataFrame`
Limpia el HTML de los campos definidos en `_HTML_COLUMNS` extrayendo el texto plano de cada campo para que sea legible. Los campos ausentes en el DataFrame se ignoran silenciosamente. Delega el procesado de cada celda en `_strip_html()`.

#### `_normalize_tags(df) → pd.DataFrame`
Convierte el campo `Etiquetas` de lista Python a un VARCHAR separado por comas, compatible con SQL Server.

| Antes | Después |
|---|---| 
| `["backend", "api", "urgente"]` | `"backend, api, urgente"` |
| `[]` | `""` (cadena vacía, nunca `NULL`) |

Si el campo `Etiquetas` no existe en el DataFrame, el método lo ignora y devuelve el DataFrame sin cambios.

### Método auxiliar estático

#### `_strip_html() → str`
Extrae el texto plano de un string HTML en dos pasos:
1. `BeautifulSoup` parsea el HTML y extrae el texto visible, uniendo elementos con un espacio.
2. Se normalizan los espacios múltiples y saltos de línea consecutivos con una expresión regular para obtener un texto limpio y legible.

| Parámetro | Tipo | Descripción |
|---|---| ---| 
| `value` | `Any` | String HTML, `None`, o cualquier otro tipo. |

**Returns:** Texto plano limpio, o cadena vacía si el valor es nulo o no es un string.

```python
WorkItemTransformer._strip_html("<p>Descripción <b>importante</b></p>")
## → "Descripción importante"

WorkItemTransformer._strip_html(None)
## → ""
```

### Dependencias

| Librería | Versión mínima | Uso |
|---|---|---|
| `pandas` | >= 3.0 | Conversión a DataFrame y operaciones de transformación |
| `beautifulsoup4` | >= 4.14 | Extracción de texto plano desde HTML |
| `re` | - | Normalización de espacios y saltos de línea tras el parseo HTML |
| `modules.utils.logger` | - | Registro de eventos y advertencias de calidad del dato |
