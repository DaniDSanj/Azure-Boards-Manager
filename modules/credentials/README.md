# Módulo Credentials
En el caso de que queramos gestionar ciertas variables de entorno de forma segura, el proyecto tiene incluido este módulo, el cual crea la entidad Credential Manager que nos permite encriptar y almacenar las variables más sensibles para evitar tenerlas disponibles en un fichero plano como un `.env`. La filosofía de este módulo es que sea reutilizable en otro proyectos, por lo que para garantizar la compatibilidad con aquellos que reutilicen las mismas credenciales del Credential Manager, se recomienda usar siempre los mismos nombres clave. El proyecto usa un sistema de credenciales en tres capas de prioridad:

```
Prioridad 1 — Fichero .env         (fallback rápido, menos seguro)
Prioridad 2 — Windows Auth         (solo para SQL Server)
Prioridad 3 — Credential Manager   (opción recomendada, cifrado Fernet + PBKDF2)
```

Las credenciales almacenadas en el Credential Manager se cifran con **Fernet (AES-128-CBC + HMAC-SHA256)** con clave derivada mediante **PBKDF2-HMAC-SHA256** (390.000 iteraciones). Para rotar una credencial caducada (por ejemplo, una PAT de Azure expirada):

```python
from modules.credentials import delete_credential
delete_credential("azure_pat")   # La próxima ejecución pedirá la nueva PAT
```

⚠️ Para poder **configurar el módulo de credenciales por primera vez**, se recomienda seguir los pasos previstos dentro del fichero [DEPLOYMENT.md]().

## Índice
1. [`__init__.py` — Interfaz pública del módulo de credenciales](#__init__py--interfaz-pública-del-módulo-de-credenciales)
2. [`credential_manager.py` — Gestor del ciclo de vida de credenciales](#credential_managerpy--gestor-del-ciclo-de-vida-de-credenciales)
3. [`crypto.py` — Motor de cifrado de credenciales](#cryptopy--motor-de-cifrado-de-credenciales)

## `__init__.py` — Interfaz pública del módulo de credenciales
Este fichero es la puerta de entrada al módulo de gestión de credenciales. Instancia internamente un único `CredentialManager` compartido y expone cuatro funciones de conveniencia que cubren la totalidad de los casos de uso del proyecto: obtener una credencial simple, obtener un login, eliminar una credencial y comprobar si existe. El resto del proyecto nunca debe instanciar `CredentialManager` directamente: basta con importar estas funciones.

### Flujo general de una credencial
```
Primera ejecución
    │
    ▼
¿Existe la credencial en el Credential Manager?
    │
    ├── No → Se solicita al usuario por consola (entrada oculta)
    │           1. Se cifra con Fernet (PBKDF2-HMAC-SHA256)
    │           2. Se guarda en Windows Credential Manager
    │           3. Se devuelve el valor en claro
    │
    └── Sí → Se descifra
               │
               ├── OK  → Se devuelve el valor en claro
               │
               └── Error (clave cambiada / token corrupto)
                         Se elimina la entrada inválida
                         Se solicita al usuario de nuevo
```

A partir de la segunda ejecución, el proceso es completamente automático: el usuario no necesita introducir nada.

### Funciones

#### `get_credential(credential_key) → str`
Recupera una credencial de tipo **TOKEN** (valor único, como una PAT de Azure). Si la credencial no existe en el Credential Manager, la solicita al usuario por consola ocultando la entrada, la cifra y la guarda para usos futuros. En ejecuciones posteriores, la recupera automáticamente sin ningún prompt.

| Parámetro | Tipo | Descripción |
|---|---|---|
| `credential_key` | `str` | Nombre clave de la credencial (ej. `"azure_pat"`). Debe coincidir con el nombre usado al guardarla y en otros proyectos que la reutilicen. |

**Returns:** Valor de la credencial en texto plano.

**Raises:**
- `ValueError` — Si `credential_key` es `None` o está vacío.
- `SystemExit` — Si el usuario no introduce ningún valor cuando se le solicita la credencial.

```python
from modules.credentials import get_credential

pat = get_credential("azure_pat")
```

#### `get_login(credential_key) → tuple[str, str]`
Recupera una credencial de tipo **LOGIN** (usuario + contraseña), como las de SQL Server. Los dos valores se almacenan juntos como un único objeto JSON cifrado, garantizando que usuario y contraseña siempre están en sincronía. Si el login no existe, solicita ambos valores por consola (la contraseña se oculta al escribir).

| Parámetro | Tipo | Descripción |
|---|---|---|
| `credential_key` | `str` | Nombre clave del login (ej. `"sql_login"`). |

**Returns:** Tupla `(username, password)` ambos en texto plano.

**Raises:**
- `ValueError` — Si `credential_key` es `None` o está vacío.
- `SystemExit` — Si el usuario no introduce alguno de los valores cuando se le solicitan.

```python
from modules.credentials import get_login

username, password = get_login("sql_login")
```

#### `delete_credential(credential_key) → bool`
Elimina una credencial del Credential Manager. Fuerza que la próxima llamada a `get_credential()` o `get_login()` solicite la credencial al usuario de nuevo. Útil para la **rotación periódica de credenciales**: por ejemplo, cuando una PAT de Azure caduca y es necesario registrar una nueva.

| Parámetro | Tipo | Descripción |
|---|---|---|
| `credential_key` | `str` | Nombre clave de la credencial a eliminar. |

**Returns:** `True` si existía y se eliminó correctamente, `False` si no existía.

**Raises:** `ValueError` — Si `credential_key` es `None` o está vacío.

```python
from modules.credentials import delete_credential

delete_credential("azure_pat")   ## La próxima ejecución pedirá la PAT de nuevo
```

#### `credential_exists(credential_key) → bool`
Comprueba si una credencial existe en el Credential Manager **sin descifrarla ni modificarla**. Útil para diagnóstico o para verificar el estado del sistema antes de una ejecución.

| Parámetro | Tipo | Descripción |
|---|---|---|
| `credential_key` | `str` | Nombre clave de la credencial a comprobar. |

**Returns:** `True` si la entrada existe, `False` si no.

```python
from modules.credentials import credential_exists

if not credential_exists("azure_pat"):
    print("La PAT de Azure no está configurada en este servidor.")
```

### Exportaciones públicas del módulo

| Símbolo | Tipo | Descripción |
|---|---|---|
| `get_credential` | Función | Recupera una credencial de tipo TOKEN |
| `get_login` | Función | Recupera una credencial de tipo LOGIN (usuario + contraseña) |
| `delete_credential` | Función | Elimina una credencial (fuerza reintroducción) |
| `credential_exists` | Función | Comprueba si una credencial existe sin modificarla |
| `CredentialManager` | Clase | Gestor completo para uso avanzado |
| `DecryptionError` | Excepción | Para capturar fallos de descifrado en código externo |

## `credential_manager.py` — Gestor del ciclo de vida de credenciales
Este módulo implementa `CredentialManager`, la clase que gestiona el ciclo de vida completo de las credenciales del proyecto: almacenamiento cifrado, recuperación automática e interacción con el usuario cuando una credencial no existe o no puede descifrarse.Todas las operaciones de lectura y escritura se realizan contra **Windows Credential Manager** a través de la librería `keyring`. El cifrado y descifrado se delegan en `crypto.py`.

En la práctica, este módulo no se usa directamente: la interfaz pública del paquete (`credentials/__init__.py`) instancia un único `CredentialManager` compartido y expone las funciones de conveniencia `get_credential`, `get_login`, `delete_credential` y `credential_exists`.

### Función auxiliar `_secure_input(prompt) → str`
*(Función privada del módulo — no es un método de la clase)*. Solicita un valor secreto al usuario ocultando lo que escribe. Usa `getpass.getpass()` como primera opción, que oculta completamente la entrada sin mostrar ningún carácter. Si `getpass` no tiene acceso a una terminal real (caso habitual al ejecutar desde un IDE como PyCharm o VS Code, o desde ciertos terminales emulados en Windows), recurre a `input()` como fallback, avisando al usuario de que la entrada será visible en pantalla.

| Parámetro | Tipo | Descripción |
|---|---|---|
| `prompt` | `str` | Texto del prompt que se muestra al usuario. |

**Returns:** Valor introducido por el usuario como string.

### Clase `CredentialManager`

#### Constructor `__init__()`
Inicializa el gestor resolviendo el nombre de servicio activo desde `crypto.resolve_service_name()`. El nombre de servicio identifica el "espacio de nombres" en el Credential Manager y debe ser el mismo en todos los proyectos que compartan credenciales.

### Métodos públicos

#### `get_credential(credential_key) → str`
Recupera una credencial de tipo TOKEN siguiendo este flujo:
1. Busca el token cifrado en el Credential Manager.
2. Si lo encuentra, lo descifra y devuelve el valor en claro.
3. Si no lo encuentra, solicita el valor al usuario por consola, lo cifra y lo guarda.
4. Si el descifrado falla (clave cambiada, token corrupto), elimina la entrada inválida y vuelve al paso 3.

| Parámetro | Tipo | Descripción |
|---|---|---|
| `credential_key` | `str` | Nombre clave de la credencial (ej. `"azure_pat"`). |

**Returns:** Valor de la credencial en texto plano.

**Raises:**
- `ValueError` — Si `credential_key` es `None` o está vacío.
- `SystemExit` — Si el usuario no introduce ningún valor cuando se le solicita.

#### `get_login(credential_key) → tuple[str, str]`
Recupera una credencial de tipo LOGIN (usuario + contraseña). Los dos valores se almacenan juntos como un objeto JSON cifrado en una sola entrada del Credential Manager, garantizando que usuario y contraseña siempre están en sincronía. Flujo idéntico al de `get_credential()`, adaptado para solicitar y devolver dos valores en lugar de uno.

| Parámetro | Tipo | Descripción |
|---|---|---|
| `credential_key` | `str` | Nombre clave del login (ej. `"sql_login"`). |

**Returns:** Tupla `(username, password)` ambos en texto plano.

**Raises:**
- `ValueError` — Si `credential_key` es `None` o está vacío.
- `SystemExit` — Si el usuario no introduce alguno de los valores cuando se le solicitan.

#### `delete_credential(credential_key) → bool`
Elimina una credencial del Credential Manager. Tras eliminarla, la próxima llamada a `get_credential()` o `get_login()` solicitará al usuario que la introduzca de nuevo. Útil para forzar la rotación de credenciales caducadas.

| Parámetro | Tipo | Descripción |
|---|---|---|
| `credential_key` | `str` | Nombre clave de la credencial a eliminar. |

**Returns:** `True` si existía y se eliminó, `False` si no existía.

**Raises:** `ValueError` — Si `credential_key` es `None` o está vacío.



#### `credential_exists(credential_key) → bool`
Comprueba si una credencial existe en el Credential Manager sin descifrarla ni modificarla.

| Parámetro | Tipo | Descripción |
|---|---|---|
| `credential_key` | `str` | Nombre clave de la credencial a comprobar. |

**Returns:** `True` si existe, `False` si no.

**Raises:** `ValueError` — Si `credential_key` es `None` o está vacío.

### Métodos privados

#### `_prompt_and_save_credential(credential_key) → str`
Solicita al usuario un valor TOKEN por consola (entrada oculta), lo cifra con `encrypt()` y lo guarda en el Credential Manager.

**Raises:** `SystemExit` — Si el usuario no introduce ningún valor.

#### `_prompt_and_save_login(credential_key) → tuple[str, str]`
Solicita al usuario el nombre de usuario (visible) y la contraseña (oculta) por consola, los cifra como JSON y los guarda como una única entrada en el Credential Manager.

**Raises:** `SystemExit` — Si el usuario no introduce alguno de los valores.

#### `_save_credential(credential_key, value)`
Cifra un valor TOKEN con `encrypt()` y lo persiste en el Credential Manager mediante `keyring.set_password()`.

#### `_save_login(credential_key, username, password)`
Serializa el par `(username, password)` como JSON, lo cifra con `encrypt()` y lo guarda como una única entrada en el Credential Manager. Guardar ambos valores juntos garantiza que nunca puede existir uno sin el otro.

#### `_safe_decrypt(credential_key, raw_token) → Optional[str]`
Intenta descifrar un token TOKEN. Si el descifrado falla (por `DecryptionError`, que indica que las claves de cifrado han cambiado o el token está corrupto), elimina la entrada inválida y devuelve `None` para que el flujo solicite la credencial al usuario.

| Parámetro | Tipo | Descripción |
|---|---|---|
| `credential_key` | `str` | Nombre clave (para logs y borrado en caso de fallo). |
| `raw_token` | `str` | Token cifrado leído del Credential Manager. |

**Returns:** Valor descifrado en texto plano, o `None` si el descifrado falló.

#### `_safe_decrypt_login(credential_key, raw_token) → Optional[tuple[str, str]]`
Igual que `_safe_decrypt` pero para tokens de tipo LOGIN: descifra y deserializa el JSON. Además de `DecryptionError`, captura `json.JSONDecodeError` y `KeyError` por si el payload estuviera malformado.

**Returns:** Tupla `(username, password)` en claro, o `None` si falló.

#### `_keyring_get(credential_key) → Optional[str]`
Encapsula `keyring.get_password()` centralizando el manejo de errores. Devuelve el token cifrado o `None` si la entrada no existe.

**Raises:** `keyring.errors.KeyringError` si el acceso al Credential Manager falla a nivel de sistema.

#### `_delete_silently(credential_key)`
Elimina una entrada del Credential Manager sin lanzar excepción si no existe. Usado internamente para limpiar tokens inválidos tras un fallo de descifrado.

#### `_validate_key(credential_key)` *(método estático)*
Valida que el nombre clave no es `None`, vacío ni contiene solo espacios.

**Raises:** `ValueError` si la validación falla.

### Dependencias

| Librería | Versión mínima | Uso |
|---|---|---|
| `keyring` | >= 25.7 | Lectura, escritura y borrado en Windows Credential Manager |
| `modules.credentials.crypto` | - | Cifrado (`encrypt`), descifrado (`decrypt`) y nombre de servicio |
| `modules.utils.logger` | - | Registro de eventos durante las operaciones de credenciales |

## `crypto.py` — Motor de cifrado de credenciales
Este módulo es el motor criptográfico del sistema de gestión de credenciales. Se encarga de derivar la clave de cifrado, cifrar valores en texto plano y descifrarlos cuando sea necesario. El algoritmo utilizado es **Fernet** (cifrado simétrico AES-128-CBC + HMAC-SHA256), con la clave derivada mediante **PBKDF2-HMAC-SHA256** a partir de dos parámetros configurables: un material clave (`KEY_MATERIAL`) y una sal (`KEY_SALT`). Esto garantiza que la clave nunca se almacena directamente: se reconstruye en memoria en cada operación y se descarta al finalizar.

### Configuración de entorno
El módulo resuelve su configuración a partir de variables de entorno del sistema operativo. En desarrollo local acepta valores por defecto embebidos en el código; en producción las variables de entorno son obligatorias.

#### Variables de entorno

| Variable | Descripción | Obligatoria en producción |
|---|---|---|
| `ABM_KEY_MATERIAL` | Material clave para la derivación PBKDF2. Debe ser un string largo y aleatorio. | ✅ |
| `ABM_KEY_SALT` | Sal para la derivación PBKDF2. Debe ser distinta del material clave. | ✅ |
| `ABM_SERVICE_NAME` | Nombre del servicio en Windows Credential Manager. Identifica el "espacio de nombres" de las entradas. | Recomendado |

> ⚠️ Si solo una de las dos variables de cifrado está definida (sin su par), el módulo lanza `EnvironmentError` con un mensaje explícito. Ambas deben definirse juntas o ninguna.

> ⚠️ Si `ABM_SERVICE_NAME` no está definida, se usa el valor por defecto `"Azure-Boards-Manager-dev"` con un `WARNING`. Proyectos que quieran compartir credenciales deben usar el mismo nombre de servicio.

#### Valores por defecto (solo desarrollo local)

| Constante | Valor | Uso |
|---|---|---|
| `_DEFAULT_KEY_MATERIAL` | `b"Azure-Boards-Manager::credentials::v1"` | Material clave en ausencia de `ABM_KEY_MATERIAL` |
| `_DEFAULT_KEY_SALT` | `b"ABM::fernet::salt::2025"` | Sal en ausencia de `ABM_KEY_SALT` |
| `_DEFAULT_SERVICE_NAME` | `"Azure-Boards-Manager-dev"` | Nombre de servicio en ausencia de `ABM_SERVICE_NAME` |

### Cadena de derivación de clave
```
ABM_KEY_MATERIAL + ABM_KEY_SALT
        │
        ▼
  PBKDF2-HMAC-SHA256
  (390.000 iteraciones)
        │
        ▼
  32 bytes raw key
        │
        ▼
  Base64-URL encode
        │
        ▼
  Clave Fernet (32 bytes en base64-url)
        │
        ▼
  Fernet.encrypt() / Fernet.decrypt()
```

Las 390.000 iteraciones de PBKDF2 superan la recomendación del NIST 2023 (≥ 310.000), lo que hace computacionalmente costoso un ataque de fuerza bruta sobre la clave.

### Funciones de la interfaz pública

#### `encrypt(plain_text) → str`
Cifra un string de texto plano y devuelve el token cifrado como string ASCII puro (base64-url), seguro para almacenar en cualquier sistema. Cada llamada produce un token diferente aunque el texto de entrada sea el mismo, ya que Fernet incluye un vector de inicialización (IV) aleatorio por diseño.

| Parámetro | Tipo | Descripción |
|---|---|---|
| `plain_text` | `str` | Texto a cifrar. No puede ser `None` ni estar vacío. |

**Returns:** Token cifrado como string ASCII (Fernet base64-url).

**Raises:**
- `ValueError` — Si `plain_text` es `None` o está vacío.
- `EnvironmentError` — Si la configuración de variables de entorno es incompleta (solo una de las dos definida).

```python
from modules.credentials.crypto import encrypt, decrypt

token = encrypt("mi_pat_de_azure")
## → cadena larga de caracteres ASCII almacenable en Credential Manager
```

#### `decrypt(cipher_text) → str`
Descifra un token Fernet y devuelve el texto original en claro. Verifica automáticamente la firma HMAC del token antes de descifrar, garantizando que el contenido no ha sido manipulado ni corrompido desde que se generó.

| Parámetro | Tipo | Descripción |
|---|---|---|
| `cipher_text` | `str` | Token Fernet producido por `encrypt()`. No puede ser `None` ni estar vacío. |

**Returns:** Texto original en texto plano.

**Raises:**
- `ValueError` — Si `cipher_text` es `None` o está vacío.
- `DecryptionError` — Si el token es inválido, ha sido manipulado, o la clave ha cambiado desde que se cifró.
- `EnvironmentError` — Si la configuración de variables de entorno es incompleta.

```python
original = decrypt(token)
## → "mi_pat_de_azure"
```

> Si `decrypt` lanza `DecryptionError`, la causa más probable es que `ABM_KEY_MATERIAL` o `ABM_KEY_SALT` han cambiado desde que se guardaron las credenciales. La solución es eliminar la entrada del Credential Manager de Windows y volver a ejecutar el programa para introducir las credenciales de nuevo.

#### `resolve_service_name() → str`

Devuelve el nombre del servicio para Windows Credential Manager. Si `ABM_SERVICE_NAME` está definida como variable de entorno, devuelve ese valor; si no, devuelve el valor por defecto con un `WARNING`.

**Returns:** Nombre del servicio como string.

### Funciones privadas

#### `_resolve_key_params() → tuple[bytes, bytes]`
Resuelve `KEY_MATERIAL` y `KEY_SALT` siguiendo la prioridad: variable de entorno del SO > constante por defecto. Emite un `WARNING` si se usan los valores por defecto.

**Raises:** `EnvironmentError` — Si solo una de las dos variables está definida.

#### `_derive_fernet_key() → bytes`
Deriva una clave Fernet de 32 bytes en base64-url usando PBKDF2-HMAC-SHA256 sobre los parámetros resueltos por `_resolve_key_params()`. La clave se reconstruye en memoria en cada llamada y se descarta al salir del scope: **nunca se persiste en disco ni en variables globales**.

#### `_get_cipher() → Fernet`
Construye y devuelve una instancia `Fernet` lista para operar, derivando la clave en el momento de la llamada.

### Clase `DecryptionError`
Excepción propia del módulo que se lanza cuando el descifrado falla por token inválido o clave incorrecta. Proporciona una señal semántica clara que `CredentialManager` captura para pedir al usuario que reintroduzca sus credenciales, en lugar de propagar un error críptico de librería (`cryptography.fernet.InvalidToken`) al resto del sistema.

```python
from modules.credentials.crypto import DecryptionError

try:
    value = decrypt(token)
except DecryptionError:
    ## La clave ha cambiado o el token está corrupto
    ...
```

### Dependencias

| Librería | Versión mínima | Uso |
|---|---|---|
| `cryptography` | >= 46.0 | Cifrado Fernet, derivación PBKDF2-HMAC-SHA256 |
| `modules.utils.logger` | - | Registro de eventos durante el cifrado y descifrado |
