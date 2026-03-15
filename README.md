# Azure Boards Manager
Pipeline de datos en Python para la extracción, transformación y carga de tarjetas (work items) desde **Azure DevOps Boards** hacia **SQL Server** con el objetivo de realizar análisis avanzados uniendo la gestión de proyectos en Azure con datos de negocio ya almacenados en SQL Server. Este trabajo ha sido desarrollado con ayuda de [Claude](https://claude.ai/). Para dudas y sugerencias, puedes ponerte en contacto conmigo a través de [Github](https://github.com/DaniDSanj) y [LinkedIn](https://www.linkedin.com/in/danidsanj/).

El proceso extrae de forma automática todas las tarjetas de un proyecto de Azure Boards a partir de uno o varios IDs raíz, recorre su jerarquía completa (Epic → Feature → User Story → Task...), transforma y limpia los datos y los carga en SQL Server. Tras la carga, ejecuta un procedimiento almacenado que aplica la lógica de negocio requerida y deja los datos listos para su análisis. Todo el proceso queda registrado en un fichero `.log` local y en una tabla de logs en SQL Server, con métricas de CPU, RAM e identificador único de ejecución.

## Índice
1. [Arquitectura](#arquitectura)
2. [Esquema](#esquema)
3. [Requisitos](#requisitos)
4. [Instalación](#instalación)
5. [Ejecución](#ejecución)
6. [Configuración](#configuración)
7. [Documentación](#documentación)
8. [Dependencias](#dependencias)
9. [Próximos Pasos](#próximos-pasos)
10. [`main.py` — Orquestación del proceso completo](#mainpy--orquestación-del-proceso-completo)

## Arquitectura
```
Azure DevOps Boards
        │
        │  API REST (PAT)
        ▼
┌───────────────────┐
│  azure_extractor  │ -> Extrae work items por jerarquía, etiquetas o tipo.
└────────┬──────────┘
         │
         │  Lista de diccionarios en crudo
         │
         ▼
┌───────────────────┐
│   transformer     │ -> Limpia HTML, valida calidad, normaliza etiquetas.
└────────┬──────────┘
         │
         │  DataFrame de pandas validado
         │
         ▼
┌───────────────────┐
│    sql/loader     │ -> Carga en SQL Server (TRUNCATE_INSERT por defecto).
└────────┬──────────┘
         │
         │
         ▼
┌───────────────────┐
│   sql/executor    │ -> Ejecuta el SP con lógica de negocio.
└────────┬──────────┘
         │
         ▼
     SQL Server
```

## Esquema
```
Azure-Boards-Manager/
│
├── main.py                         # Punto de entrada principal
│
├── install.bat                     # Instalador automático (doble clic para instalar)
├── exec.bat                        # Lanzador del proceso (doble clic para ejecutar)
│
├── modules/
│   │
│   ├── credentials/
│   │   ├── __init__.py
│   │   ├── credential_manager.py   # Gestión de credenciales cifradas
│   │   └── crypto.py               # Cifrado Fernet y derivación de clave
│   │
│   ├── pipeline/                   # Capa de extracción y transformación de datos
│   │   ├── azure_extractor.py      # Extracción de tarjetas (AzureDevOpsExtractor)
│   │   └── transformer.py          # Transformación y limpieza de datos
│   │
│   ├── sql/
│   │   ├── __init__.py             # Interfaz pública + create_sql_client()
│   │   ├── connection.py           # Gestión de conexiones
│   │   ├── executor.py             # Ejecución de consultas y procedimientos
│   │   └── loader.py               # Carga de datos
│   │
│   └── utils/                      # Utilidades transversales
│       ├── config.py               # Gestión de variables de entorno
│       ├── formatters.py           # Funciones auxiliares de formateo
│       └── logger.py               # Configuración del sistema de logs
│
├── output/                         # Ficheros de salida JSON (generados en ejecución)
├── .env                            # Variables de entorno (crear manualmente desde .env.example)
├── .env.example                    # Plantilla de configuración con instrucciones
├── requirements.txt                # Librerías del proyecto
├── CONTRIBUTING.md                 # Guía para contribuir al proyecto
└── CHANGELOG.md                    # Historial de versiones
```

## Requisitos
- **Windows 10 o superior** (el proyecto está optimizado para Windows)
- Conexión a internet en la primera instalación
- Acceso a un proyecto de **Azure DevOps** con una PAT válida con permisos de lectura en Work Items
- Acceso a una instancia de **SQL Server**

> Python y todas las dependencias se instalan automáticamente mediante `install.bat`. No es necesario instalarlos manualmente.

## Instalación

La instalación se realiza con un único fichero que configura todo el entorno de forma automática. No es necesario tener conocimientos técnicos ni instalar Python manualmente.

### Pasos

**1. Descarga el repositorio** desde GitHub. Puedes hacerlo de dos formas:
   - Pulsando el botón verde **`Code` → `Download ZIP`** y descomprimiendo la carpeta.
   - O si tienes Git instalado, clonando el repositorio:
     ```bash
     git clone https://github.com/DaniDSanj/azure-boards-manager.git
     cd azure-boards-manager
     ```

**2. Haz doble clic en `install.bat`** dentro de la carpeta del proyecto.

El instalador realizará automáticamente los siguientes pasos:

| Paso | Qué hace |
|---|---|
| 1/5 | Comprueba e instala `uv` (gestor de paquetes moderno) si no está presente |
| 2/5 | Comprueba e instala Python 3.14 si no está presente |
| 3/5 | Verifica que el fichero `.env` existe y está configurado |
| 4/5 | Crea el entorno virtual del proyecto |
| 5/5 | Instala todas las dependencias listadas en `requirements.txt` |

Al finalizar, verás uno de estos mensajes:

- ✅ **`INSTALACIÓN COMPLETADA CON ÉXITO`** — el proyecto está listo para usarse.
- ❌ **`LA INSTALACIÓN NO SE COMPLETÓ`** — sigue las instrucciones en pantalla para resolver el error y vuelve a ejecutar `install.bat`.

> `install.bat` es **idempotente**: puede ejecutarse varias veces sin problemas. Si el entorno ya está instalado, simplemente lo verifica y no repite pasos innecesarios.

### Primera ejecución — configuración de credenciales

La primera vez que ejecutes el proyecto, el sistema pedirá por consola tus credenciales de Azure DevOps y SQL Server y las guardará de forma segura en el **Windows Credential Manager**. En ejecuciones posteriores, las credenciales se recuperan automáticamente sin volver a pedirlas.

Para más información sobre cómo funciona este sistema, consulta la documentación del [módulo de credenciales](#módulo-credentials).

## Ejecución

Una vez completada la instalación y la configuración del fichero `.env`:

**Haz doble clic en `exec.bat`** dentro de la carpeta del proyecto.

El lanzador realiza una serie de comprobaciones previas antes de iniciar el proceso:

| Comprobación | Qué verifica |
|---|---|
| Entorno virtual | Que `install.bat` se ha ejecutado correctamente |
| Fichero `.env` | Que existe y que los campos obligatorios están rellenos |

Si todas las comprobaciones son correctas, el proceso se inicia automáticamente. Al finalizar verás un resumen con:
- ✅ **Proceso completado con éxito** — los datos han sido cargados en SQL Server.
- ❌ **El proceso ha finalizado con errores** — revisa los mensajes en pantalla y el fichero `Azure-Boards-Manager.log` para más detalle.

> Si el proceso falla y no consigues resolver el error, abre un [issue en GitHub](../../issues) adjuntando una captura de pantalla de la ventana y el contenido del fichero `.log`.

## Configuración

### 1. Fichero `.env`

Las variables de entorno necesarias para la ejecución del proyecto se almacenan en un fichero `.env` en la raíz del proyecto. La primera vez que ejecutes `install.bat` y no exista ese fichero, el instalador creará una copia automáticamente desde `.env.example`.

El fichero `.env` tiene el siguiente aspecto:

```env
# Variables de Azure DevOps
AZURE_DEVOPS_ORG_URL=https://dev.azure.com/mi-organizacion
AZURE_DEVOPS_PROJECT=NombreDelProyecto
AZURE_DEVOPS_PAT=
AZURE_FIELDS=
AZURE_ROOT_IDS=12120,13450,14200

# Variables de conexión en SQL Server
SQL_SERVER=nombre-del-servidor
SQL_DATABASE=nombre-de-la-base-de-datos
SQL_USER=
SQL_PASSWORD=
SQL_WINDOWS_AUTH_TIMEOUT=3

# Variables de ejecución en SQL Server
SQL_SCHEMA=raw
SQL_TABLE=azuTarjetas
SQL_LOG_SCHEMA=raw
SQL_LOG_TABLE=LogsPython
SQL_STORED_PROCEDURE=dbo.SP_AzureModelo
```

> ⚠️ Este proyecto está preparado para recoger credenciales privadas como el PAT de Azure (`AZURE_DEVOPS_PAT`) o el login de SQL (`SQL_USER` / `SQL_PASSWORD`) a través de este fichero. Sin embargo, se recomienda gestionar estas credenciales de forma segura. Para más información, consulta la documentación del [módulo de credenciales](#módulo-credentials).

#### Variables de Azure DevOps

| Variable | Descripción | Tipo | Comentarios |
|-|-|-|-|
| `AZURE_DEVOPS_ORG_URL` | URL de tu organización en Azure DevOps | ‼️ **Obligatorio** | — |
| `AZURE_DEVOPS_PROJECT` | Nombre del proyecto | ‼️ **Obligatorio** | — |
| `AZURE_DEVOPS_PAT` | Personal Access Token con permisos de lectura | ‼️ **Obligatorio** | Consultar [módulo 'credentials'](#módulo-credentials) |
| `AZURE_FIELDS` | Campos adicionales de las tarjetas a incorporar | ❓ **Opcional** | Consultar [módulo 'pipeline'](#módulo-pipeline) |
| `AZURE_ROOT_IDS` | Identificadores de tarjetas a descargar | ❓ **Opcional** | Especificar los IDs separados por comas. Si no se especifican, se pedirán por consola |

Para saber la URL específica de tu organización y el nombre del proyecto, consulta la URL principal, que debería tener el siguiente aspecto: `https://dev.azure.com/<Nombre-Organizacion>/<Nombre-Proyecto>`. Para más información, consulta la guía de [Microsoft Learn](https://learn.microsoft.com/es-es/azure/devops/organizations/accounts/use-personal-access-tokens-to-authenticate?view=azure-devops&tabs=Windows).

#### Variables de conexión en SQL Server

| Variable | Descripción | Tipo | Comentarios |
|-|-|-|-|
| `SQL_SERVER` | Servidor / Instancia | ‼️ **Obligatorio** | — |
| `SQL_DATABASE` | Base de datos | ‼️ **Obligatorio** | — |
| `SQL_WINDOWS_AUTH_TIMEOUT` | Tiempo máximo de Windows Authentication (segundos) | ‼️ **Obligatorio** | `3` como valor predeterminado |
| `SQL_USER` | Usuario para iniciar sesión en SQL Server | ❓ **Opcional** | Consultar [módulo 'credentials'](#módulo-credentials) |
| `SQL_PASSWORD` | Contraseña para iniciar sesión en SQL Server | ❓ **Opcional** | Consultar [módulo 'credentials'](#módulo-credentials) |

#### Variables de ejecución en SQL Server

| Variable | Descripción | Tipo | Comentarios |
|-|-|-|-|
| `SQL_SCHEMA` | Esquema de la tabla de destino | ‼️ **Obligatorio** | `raw` como valor predeterminado |
| `SQL_TABLE` | Nombre de la tabla de destino | ‼️ **Obligatorio** | `azuTarjetas` como valor predeterminado |
| `SQL_STORED_PROCEDURE` | Procedimiento almacenado a ejecutar tras la carga | ‼️ **Obligatorio** | `dbo.SP_AzureModelo` como valor predeterminado |
| `SQL_LOG_SCHEMA` | Esquema de la tabla de logs | ‼️ **Obligatorio** | `raw` como valor predeterminado |
| `SQL_LOG_TABLE` | Nombre de la tabla de logs | ‼️ **Obligatorio** | `LogsPython` como valor predeterminado |

## Documentación

Para realizar una configuración personalizada y aprovechar al máximo las funcionalidades del proyecto, se recomienda consultar la documentación de cada módulo:

#### Módulo *'credentials'*
- [`./modules/credentials/README.md`](./modules/credentials/README.md): Documentación general para la gestión de credenciales.
- [`./modules/credentials/DEPLOYMENT.md`](./modules/credentials/DEPLOYMENT.md): Guía de despliegue del módulo *Credential Manager*.

#### Módulo *'pipeline'*
- [`./modules/pipeline/README.md`](./modules/pipeline/README.md): Documentación para la extracción, transformación y limpieza de datos.

#### Módulo *'sql'*
- [`./modules/sql/README.md`](./modules/sql/README.md): Documentación para conexiones con SQL Server.

#### Módulo *'utils'*
- [`./modules/utils/README.md`](./modules/utils/README.md): Documentación de las funcionalidades transversales al proyecto.

## Dependencias

| Librería | Versión | Uso |
|---|---|---|
| `azure-devops` | 7.1.0b4 | Cliente oficial de la API de Azure DevOps |
| `msrest` | 0.7.1 | Autenticación PAT |
| `SQLAlchemy` | 2.0.46 | ORM y gestión de conexiones a SQL Server |
| `pyodbc` | 5.3.0 | Driver ODBC para SQL Server |
| `pandas` | 3.0.1 | Transformación de datos y carga con `to_sql` |
| `cryptography` | 46.0.5 | Cifrado Fernet y derivación PBKDF2 |
| `keyring` | 25.7.0 | Acceso a Windows Credential Manager |
| `python-dotenv` | 1.0.1 | Lectura del fichero `.env` |
| `beautifulsoup4` | 4.14.3 | Limpieza de HTML en campos de texto |
| `psutil` | 7.2.2 | Métricas de CPU y RAM para logging |
| `tqdm` | 4.67.3 | Barras de progreso para logging |
| `pytest` | 9.0.2 | Tests unitarios |

## Próximos Pasos

En las próximas iteraciones de este proyecto, se prevé trabajar sobre las siguientes áreas:
- Ampliar las salidas a más formatos, no solo SQL Server y JSON.
- Módulo de tests unitarios (ya incorporado en los requerimientos).
- Mejora del encapsulamiento del código en clases y refinamiento del código a nivel general.

## `main.py` — Orquestación del proceso completo

Este es el punto de entrada del proyecto. Orquesta en orden todos los pasos del proceso: carga de configuración, resolución de IDs, extracción desde Azure Boards, transformación del dato, carga a SQL Server, ejecución del procedimiento almacenado y volcado del log de la ejecución. Es el único fichero que activa la captura de logs a DataFrame (`capture_to_df=True`), lo que genera el UUID de ejecución y registra todos los mensajes en la tabla de logs de SQL Server al finalizar.

### Flujo de ejecución
```
1. Cargar configuración
   └── load_config() → AppConfig
        │
        ▼
2. Resolver IDs a procesar
   └── Desde .env (AZURE_ROOT_IDS) o solicitando al usuario por consola
        │
        ▼
3. Conectar con Azure DevOps
   └── AzureDevOpsExtractor(org_url, project, pat, fields=azure_fields or None)
        │
        ▼
4. Extraer tarjetas
   └── Por cada ID raíz:
       · get_work_items_by_id(root_id)
       · export_to_json(items, root_id)   → output/work_items_{id}_{ts}.json
       · Acumular en all_work_items
        │
        ▼
5. Transformar
   └── WorkItemTransformer().transform(all_work_items)
        │
        ▼
6. Conectar con SQL Server
   └── create_sql_client(server, database, username, password)
        │
        ▼
7. Cargar tarjetas a SQL Server
   └── loader.load(df, schema, table, TRUNCATE_INSERT)
        │
        ▼
8. Ejecutar procedimiento almacenado
   └── executor.execute_procedure(stored_procedure)
        │
        ▼
9. Volcar log de ejecución a SQL Server
   └── loader.load(get_log_dataframe(), log_schema, log_table, APPEND)
```
