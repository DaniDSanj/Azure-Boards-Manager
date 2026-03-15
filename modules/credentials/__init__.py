"""Interfaz pública del paquete de gestión de credenciales."""

from modules.credentials.credential_manager import CredentialManager
from modules.credentials.crypto import DecryptionError

_manager = CredentialManager()

def get_credential(credential_key: str) -> str:
    """
    Recupera una credencial de tipo TOKEN del Credential Manager.

    Si la credencial no existe, la solicita al usuario por consola
    (ocultando lo que escribe), la cifra y la guarda para usos futuros.
    En ejecuciones posteriores, la recupera automáticamente sin ningún
    prompt.

    Args:
        credential_key: Nombre clave de la credencial (ej. "azure_pat").
                        Debe coincidir con el usado al guardarla por
                        primera vez y en otros proyectos que la reutilicen.

    Returns:
        Valor de la credencial en texto plano.

    Raises:
        ValueError: Si credential_key es None o está vacío.
        SystemExit: Si el usuario no introduce ningún valor cuando
                    se le solicita la credencial.

    Example:
        >>> from modules.credentials import get_credential
        >>> pat = get_credential("azure_pat")
    """
    return _manager.get_credential(credential_key)


def get_login(credential_key: str) -> tuple[str, str]:
    """
    Recupera una credencial de tipo LOGIN (usuario + contraseña).

    Si el login no existe, solicita el usuario y la contraseña por
    consola (la contraseña se oculta al escribir), los cifra juntos
    y los guarda como una única entrada en el Credential Manager.
    En ejecuciones posteriores, los recupera automáticamente.

    Args:
        credential_key: Nombre clave del login (ej. "sql_login").

    Returns:
        Tupla (username, password) ambos en texto plano.

    Raises:
        ValueError: Si credential_key es None o está vacío.
        SystemExit: Si el usuario no introduce alguno de los valores.

    Example:
        >>> from modules.credentials import get_login
        >>> username, password = get_login("sql_login")
    """
    return _manager.get_login(credential_key)


def delete_credential(credential_key: str) -> bool:
    """
    Elimina una credencial del Credential Manager.

    Fuerza que la próxima llamada a get_credential() o get_login()
    solicite la credencial al usuario de nuevo. Útil para la rotación
    periódica de credenciales (ej. cuando una PAT de Azure caduca).

    Args:
        credential_key: Nombre clave de la credencial a eliminar.

    Returns:
        True  si existía y se eliminó correctamente.
        False si no existía.

    Raises:
        ValueError: Si credential_key es None o está vacío.

    Example:
        >>> from modules.credentials import delete_credential
        >>> delete_credential("azure_pat")   # La próxima ejecución pedirá la PAT
        True
    """
    return _manager.delete_credential(credential_key)


def credential_exists(credential_key: str) -> bool:
    """
    Comprueba si una credencial existe en el Credential Manager,
    sin descifrarla ni modificarla.

    Útil para verificar el estado del sistema antes de una ejecución
    o para diagnóstico sin alterar ninguna entrada.

    Args:
        credential_key: Nombre clave de la credencial a comprobar.

    Returns:
        True  si la entrada existe en el Credential Manager.
        False si no existe.

    Example:
        >>> from modules.credentials import credential_exists
        >>> if not credential_exists("azure_pat"):
        ...     print("La PAT de Azure no está configurada en este servidor.")
    """
    return _manager.credential_exists(credential_key)

# Exportaciones explícitas del paquete
__all__ = [
    # Funciones de conveniencia (uso recomendado)
    "get_credential",
    "get_login",
    "delete_credential",
    "credential_exists",
    # Clase para uso avanzado
    "CredentialManager",
    # Excepción exportada para código que necesite capturarla externamente
    "DecryptionError",
]
