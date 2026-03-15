"""Motor de cifrado y descifrado para el sistema de gestión de credenciales."""

import base64
import os
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from modules.utils.logger import get_logger

logger = get_logger(__name__)

# Valores por defecto (solo para desarrollo local)
_DEFAULT_KEY_MATERIAL: bytes = b"Azure-Boards-Manager::credentials::v1"
_DEFAULT_KEY_SALT: bytes     = b"ABM::fernet::salt::2025"
_DEFAULT_SERVICE_NAME: str   = "Azure-Boards-Manager"

# Número de iteraciones PBKDF2 (recomendación NIST 2023: >= 310.000)
_PBKDF2_ITERATIONS: int = 390_000

# Nombres de las variables de entorno
_ENV_KEY_MATERIAL  = "ABM_KEY_MATERIAL"
_ENV_KEY_SALT      = "ABM_KEY_SALT"
_ENV_SERVICE_NAME  = "ABM_SERVICE_NAME"

# Resolución de configuración
def _resolve_key_params() -> tuple[bytes, bytes]:
    """
    Resuelve KEY_MATERIAL y KEY_SALT con la siguiente prioridad:
    variable de entorno del SO > constante por defecto del código.

    En producción (servidor), ambas variables de entorno son obligatorias.
    En desarrollo local, se aceptan los valores por defecto con un WARNING.

    Returns:
        Tupla (key_material, key_salt) ambos como bytes.

    Raises:
        EnvironmentError: Si solo una de las dos variables está definida.
    """
    env_material = os.environ.get(_ENV_KEY_MATERIAL)
    env_salt     = os.environ.get(_ENV_KEY_SALT)

    # Caso: ambas variables de entorno presentes → modo producción
    if env_material and env_salt:
        logger.debug(
            "Clave de cifrado derivada desde variables de entorno del sistema "
            "(%s, %s). Modo: producción.", _ENV_KEY_MATERIAL, _ENV_KEY_SALT
        )
        return env_material.encode("utf-8"), env_salt.encode("utf-8")

    # Caso: solo una definida → configuración incompleta, error explícito
    if bool(env_material) != bool(env_salt):
        defined   = _ENV_KEY_MATERIAL if env_material else _ENV_KEY_SALT
        undefined = _ENV_KEY_SALT     if env_material else _ENV_KEY_MATERIAL
        raise EnvironmentError(
            f"Configuración de cifrado incompleta: '{defined}' está definida "
            f"pero '{undefined}' no lo está. Ambas deben definirse juntas. "
            f"Consulta DEPLOYMENT.md para instrucciones de configuración."
        )

    # Caso: ninguna definida → modo desarrollo local con aviso
    logger.warning(
        "⚠ Las variables de entorno %s y %s no están definidas. "
        "Usando valores por defecto embebidos en el código. "
        "Esto es aceptable en desarrollo local, pero NO en un servidor. "
        "Consulta DEPLOYMENT.md para configurar el entorno correctamente.",
        _ENV_KEY_MATERIAL, _ENV_KEY_SALT
    )
    return _DEFAULT_KEY_MATERIAL, _DEFAULT_KEY_SALT


def resolve_service_name() -> str:
    """
    Devuelve el nombre del servicio para Windows Credential Manager.

    El nombre de servicio identifica el "espacio de nombres" de las
    entradas en el Credential Manager. Proyectos que compartan este
    nombre y las mismas claves de cifrado pueden reutilizar los mismos
    tokens sin volver a pedirlos al usuario.

    Prioridad: variable de entorno ATM_SERVICE_NAME > valor por defecto.

    Si ATM_SERVICE_NAME no está definida en producción, se emite un
    WARNING: el valor por defecto funciona, pero no es compartible con
    otros proyectos a menos que también usen el mismo valor por defecto.

    Returns:
        Nombre del servicio como string.
    """
    service_name = os.environ.get(_ENV_SERVICE_NAME)

    if service_name:
        logger.debug(
            "Nombre de servicio Credential Manager: '%s' (desde variable de entorno).",
            service_name
        )
        return service_name

    logger.warning(
        "⚠ La variable de entorno %s no está definida. "
        "Usando nombre de servicio por defecto: '%s'. "
        "Para compartir credenciales entre proyectos, define %s con el "
        "mismo valor en todos los proyectos que deban compartirlas.",
        _ENV_SERVICE_NAME, _DEFAULT_SERVICE_NAME, _ENV_SERVICE_NAME
    )
    return _DEFAULT_SERVICE_NAME


# ── Derivación de clave Fernet ────────────────────────────────────────────────

def _derive_fernet_key() -> bytes:
    """
    Deriva una clave Fernet válida (32 bytes en base64-url) usando
    PBKDF2-HMAC-SHA256 sobre los parámetros resueltos por
    _resolve_key_params().

    La clave se reconstruye en memoria en cada llamada y se descarta
    al salir del scope. Nunca se persiste en disco ni en variables globales.

    Returns:
        Clave Fernet de 32 bytes codificada en base64-url.
    """
    key_material, key_salt = _resolve_key_params()

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=key_salt,
        iterations=_PBKDF2_ITERATIONS,
    )
    raw_key = kdf.derive(key_material)
    return base64.urlsafe_b64encode(raw_key)


def _get_cipher() -> Fernet:
    """
    Construye y devuelve una instancia Fernet lista para operar.

    La clave se deriva en el momento de la llamada y se descarta
    al salir del scope.

    Returns:
        Instancia Fernet configurada con la clave activa.
    """
    return Fernet(_derive_fernet_key())


# ── Interfaz pública ───────────────────────────────────────────────────────────

def encrypt(plain_text: str) -> str:
    """
    Cifra un string de texto plano y devuelve el token cifrado.

    Cada llamada produce un token diferente aunque el texto de entrada
    sea el mismo, ya que Fernet incluye un vector de inicialización (IV)
    aleatorio por diseño. El token resultante es un string ASCII puro
    (base64-url) seguro para almacenar en cualquier sistema.

    Args:
        plain_text: Texto a cifrar. No puede ser None ni estar vacío.

    Returns:
        Token cifrado como string ASCII (Fernet base64-url).

    Raises:
        ValueError:       Si plain_text es None o está vacío.
        EnvironmentError: Si la configuración de variables de entorno
                          es incompleta (solo una de las dos definida).

    Example:
        >>> token = encrypt("mi_pat_de_azure")
        >>> # Resultado: cadena larga de caracteres ASCII almacenable
    """
    if not plain_text:
        raise ValueError("El texto a cifrar no puede ser None ni estar vacío.")

    cipher  = _get_cipher()
    token   = cipher.encrypt(plain_text.encode("utf-8"))
    encoded = token.decode("ascii")

    logger.debug("Texto cifrado correctamente (longitud token: %d).", len(encoded))
    return encoded


def decrypt(cipher_text: str) -> str:
    """
    Descifra un token Fernet y devuelve el texto original en claro.

    Verifica automáticamente la firma HMAC del token antes de descifrar,
    garantizando que el contenido no ha sido manipulado ni corrompido
    desde que se generó.

    Args:
        cipher_text: Token Fernet producido por encrypt(). No puede
                     ser None ni estar vacío.

    Returns:
        Texto original en texto plano.

    Raises:
        ValueError:       Si cipher_text es None o está vacío.
        DecryptionError:  Si el token es inválido, ha sido manipulado,
                          o la clave ha cambiado desde que se cifró.
        EnvironmentError: Si la configuración de variables de entorno
                          es incompleta (solo una de las dos definida).

    Example:
        >>> original = decrypt(token)
        >>> # Resultado: "mi_pat_de_azure"
    """
    if not cipher_text:
        raise ValueError("El texto cifrado no puede ser None ni estar vacío.")

    cipher = _get_cipher()

    try:
        plain_bytes = cipher.decrypt(cipher_text.encode("ascii"))
        plain_text  = plain_bytes.decode("utf-8")

        logger.debug("Texto descifrado correctamente.")
        return plain_text

    except InvalidToken as e:
        logger.error(
            "Fallo al descifrar: el token es inválido o la clave ha cambiado. "
            "Verifica que ATM_KEY_MATERIAL y ATM_KEY_SALT en el servidor coinciden "
            "exactamente con los valores usados cuando se guardaron las credenciales."
        )
        raise DecryptionError(
            "No se pudo descifrar la credencial almacenada. Causas posibles:\n"
            "  1. ATM_KEY_MATERIAL o ATM_KEY_SALT han cambiado desde que se "
            "guardaron las credenciales.\n"
            "  2. El token en el Credential Manager está corrupto.\n"
            "Solución: elimina la entrada del Credential Manager de Windows "
            "y vuelve a ejecutar el programa para introducir las credenciales."
        ) from e


# ── Excepción propia ───────────────────────────────────────────────────────────

class DecryptionError(Exception):
    """
    Se lanza cuando el descifrado falla por token inválido o clave incorrecta.

    Proporciona una señal semántica clara que CredentialManager captura
    para pedir al usuario que reintroduzca sus credenciales, en lugar
    de propagar un error críptico de librería al resto del sistema.
    """
