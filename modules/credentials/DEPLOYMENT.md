# Guía de configuración de credenciales del proyecto
Guía paso a paso para configurar el sistema de gestión de credenciales de AzureTaskManager en un servidor Windows compartido.

## Índice
1. [Configurar Sistema](#1-configurar-sistema)
2. [Definir Contraseña Maestra](#2-definir-contraseña-maestra)
3. [Variables de Entorno](#3-guardar-variables-de-entorno)
4. [Verificar Configuración](#4-verificar-configuración)
5. [Introducir Credenciales](#5-introducir-credenciales)
6. [Reutilizar Credenciales](#6-reutilizar-credenciales)
7. [Recuperar Claves](#7-recuperar-claves)

## 1. Configurar Sistema
Para poder usar este módulo de forma correcta, se necesitará cumplir los siguientes requisitos:
- Tener acceso de administrador al sistema, ya que necesitamos definir variables de entorno de sistema.
- Instalar Python 3.14 o superior en el equipo que va a ejecutar el proyecto.
- Instalar las dependencias del proyecto en el entorno:
```powershell
pip install -r requirements.txt
```

## 2. Definir Contraseña Maestra
El sistema de cifrado de este proyecto utiliza el método de encriptadop Fernet a través de una contraseña maestra compuesta por dos elementos:
- **Material**: Es propia contraseña maestra que se encriptará en el sistema.
- **Salt**: Es una cadena de datos aleatorios (bits) que se añade al *MATERIAL* para diferenciarlo de otra contraseña si esta se repite en el sistema.

Estos dos elementos deben generarse **una única vez** en el servidor y guardarse en un lugar seguro. Para configurar la clave, es preferible generarla de forma aleatoria. Para ello, puedes ejecutar este comando que generará ambos valores:
```powershell
python -c "
import secrets
print('KEY_MATERIAL =', secrets.token_hex(32))
print('KEY_SALT     =', secrets.token_hex(16))
"
```
**Ejemplo de salida:**
```
KEY_MATERIAL = f47a0fd654db27010a7a9acaa7bc4086d9c7653cf8185b80b0619345a8ca74fa
KEY_SALT     = 681ff2cad37c151b1d836941f9baa88e
```

> ⚠️ **IMPORTANTE** ⚠️
>
> Guarda estos valores en un lugar seguro antes de continuar. Si se pierden, las credenciales guardadas en el Credential Manager quedarán ilegibles para siempre y habrá que volver a introducirlas. No las guardes en un repositorio Git ni en ningún fichero de texto plano (como el .env).

Además, será necesario un nombre de servicio que permita identificar el proceso de recuperación de claves para saber qué claves debemos recuperar. Este punto será muy útil si varios proyectos comparten las mismas credenciales.

| Variable | Obligatoria en servidor | Descripción | Cómo generarla |
|----------|------------------------|-------------|----------------|
| `ABM_KEY_MATERIAL` | ✅ Sí | Contraseña maestra del cifrado | `python -c "import secrets; print(secrets.token_hex(32))"` |
| `ABM_KEY_SALT` | ✅ Sí | Sal del cifrado | `python -c "import secrets; print(secrets.token_hex(16))"` |
| `ABM_SERVICE_NAME` | ✅ Sí (para compartir credenciales) | Nombre del servicio en Credential Manager | Valor acordado por el equipo, ej. `Azure-Boards-Manager` |

## 3. Guardar Variables de Entorno
Para guardar la contraseña maestra, hay que definir **3 variables de entorno** en el sistema. Existen dos formas de hacerlo: por interfaz gráfica o por PowerShell.

### Interfaz gráfica (recomendada para el primer despliegue)
Accede a las variables de entorno a través del Panel de Control.
```
Panel de control
  → Sistema y seguridad
    → Sistema
      → Configuración avanzada del sistema (menú lateral izquierdo)
        → Pestaña "Opciones avanzadas"
          → Botón "Variables de entorno..."
```
Una vez dentro, habrá dos listados: variables del sistema, que son variables que afectan a todos los usuarios; y variables de usuario, las cuales solo afectan a la cuenta de servicio actual. En función de nuestra preferencia, añadir cada una de las tres variables en el listado de que más se ajuste a nuestra preferencia.
> 💡 **¿Sistema o usuario?**
> - **Variables del sistema** → disponibles para todos los usuarios y procesos del servidor.
> - **Variables de usuario** → solo disponibles para la sesión del usuario actual.
>
> Para una cuenta de servicio dedicada que ejecuta tareas programadas, lo habitual es definirlas en **"Variables del sistema"** si hay una sola cuenta de servicio, o en **"Variables de usuario"** si cada proyecto tiene su propia cuenta.

| Variable | Valor |
|-|-|
| `ABM_KEY_MATERIAL` | El valor generado en el Paso 2 |
| `ABM_KEY_SALT` | El valor generado en el Paso 2 |
| `ABM_SERVICE_NAME` | `Azure-Boards-Manager` (o el nombre acordado) |

### PowerShell (recomendada para automatización y scripting)

Ejecutar como Administrador:
```powershell
# Sustituir los valores entre comillas por los generados en el Paso 2

[System.Environment]::SetEnvironmentVariable(
    "ABM_KEY_MATERIAL",
    "f47a0fd654db27010a7a9acaa7bc4086d9c7653cf8185b80b0619345a8ca74fa",
    "Machine"   # "Machine" = Variable del Sistema | "User" = Variable de usuario actual
)

[System.Environment]::SetEnvironmentVariable(
    "ABM_KEY_SALT",
    "681ff2cad37c151b1d836941f9baa88e",
    "Machine"
)

[System.Environment]::SetEnvironmentVariable(
    "ABM_SERVICE_NAME",
    "Azure-Boards-Manager",
    "Machine"
)
```

> ⚠️ **IMPORTANTE** ⚠️
>
> Tras definir las variables, es necesario cerrar y volver a abrir cualquier ventana de PowerShell o CMD. Si el proceso se ejecuta como tarea programada, reiniciar el programador de tareas o la propia tarea para que cargue el entorno nuevo.

## 4. Verificar Configuración
Antes de la primera ejecución real, podemos verificar que las variables están correctamente definidas tanto en **Powershell**:
```powershell
# Verificar que las tres variables están accesibles
[System.Environment]::GetEnvironmentVariable("ABM_KEY_MATERIAL", "Machine")
[System.Environment]::GetEnvironmentVariable("ABM_KEY_SALT", "Machine")
[System.Environment]::GetEnvironmentVariable("ABM_SERVICE_NAME", "Machine")
```
Como en **Python**:
```powershell
python -c "
import os
variables = ['ABM_KEY_MATERIAL', 'ABM_KEY_SALT', 'ABM_SERVICE_NAME']
all_ok = True
for var in variables:
    value = os.environ.get(var)
    if value:
        print(f'  OK  {var} = {value[:8]}...')  # Solo primeros 8 chars por seguridad
    else:
        print(f'  FALTA  {var} no está definida')
        all_ok = False
print()
print('Configuracion correcta.' if all_ok else 'Configuracion INCOMPLETA. Revisa el Paso 3.')
"
```

## 5. Introducir Credenciales

Con las variables de entorno configuradas, solo tendremos que ejecutar el proyecto como si fuera una ejecución normal a través de la consola:
```powershell
python main.py
```
Una vez el programa revise el fichero `.env` y no encuentre las credenciales, irá a buscarlas al sistema sin éxito. Entonces será el mismo programa quien las solicite por consola una única vez, mostrando el siguiente mensaje:
```powershell
Credencial 'azure_pat' no encontrada en el sistema.
Introduce el valor para 'azure_pat': |
```
El usuario deberá escribir la contraseña o copiarla y pegarla en la consola. Es importante señalar que **NO se mostrará ningún valor escrito por el usuario** por cuestiones de seguridad, por lo que se recomienda la opción de copiado y pegado en la consola. Una vez entonces, se presiona *ENTER* y recibiremos el siguiente mensaje:
```powershell
Credencial 'azure_pat' guardada correctamente en el Credential Manager.
```
Ocurrirá lo mismo con las credenciales de login en SQL:

```powershell
Credencial 'sql_password' no encontrada en el sistema.
Introduce el nombre de usuario para 'sql_password': [el usuario escribe, se muestra]
Introduce la contraseña para 'sql_password': [el usuario escribe, no se muestra]
Credencial 'sql_password' guardada correctamente en el Credential Manager.
```
A partir de este momento, **todas las ejecuciones futuras recuperarán las credenciales automáticamente** sin ningún prompt. Si se necesita rotar alguna credencial, sería necesario ejecutar el siguiente comando:
```powershell
python rotate.py
```

## 6. Reutilizar Credenciales
Este módulo facilita que un segundo proyecto Python en el mismo servidor use las mismas credenciales sin volver a solicitarlas. Para ello, es necesario seguir los siguientes pasos:
- El nuevo proyecto debe usar las mismas credenciales. Es decir, `ABM_KEY_MATERIAL`, `ABM_KEY_SALT` y `ABM_SERVICE_NAME` deben tener los mismos valores que en el proyecto original. 
- Copiar la carpeta `./modules/credentials/` al nuevo proyecto.
- Añadir las dependencias al `requirements.txt` del nuevo proyecto:
   ```
   keyring==25.7.0
   cryptography==46.0.5
   ```
- Usar el mismo nombre clave al llamar a `get_credential()` (ej. `"azure_pat"`).
- En el código del nuevo proyecto, usar la nueva variable de este modo: 
   ```python
   from modules.credentials import get_credential

   # Recuperará la PAT existente sin pedir nada al usuario
   azure_pat = get_credential("azure_pat")
   ```
De esta forma, al ejecutar el nuevo proyecto, el sistema encontrará las credenciales existentes y las devolverá directamente, sin ningún prompt.

## 7. Recuperar Claves
Si por cualquier motivo `ABM_KEY_MATERIAL` o `ABM_KEY_SALT` cambian después de haber guardado credenciales, el sistema no podrá descifrar los tokens existentes. El log mostrará un error `DecryptionError`. Para soluic

**Proceso de recuperación:**
1. Abrir Windows Credential Manager: ```Panel de control → Administrador de credenciales → Credenciales de Windows```
2. Buscar las entradas con el nombre del servicio (ej. `Azure-Boards-Manager`) y eliminarlas.
3. Actualizar las variables de entorno con los nuevos valores.
4. Volver a ejecutar el proyecto. El sistema pedirá las credenciales de nuevo y las guardará cifradas con las nuevas claves.
