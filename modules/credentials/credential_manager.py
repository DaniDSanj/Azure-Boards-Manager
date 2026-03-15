"""Gestor de credenciales para AzureTaskManager."""

import getpass
import json
import sys
from typing import Optional

import keyring
import keyring.errors

from modules.credentials.crypto import (
    DecryptionError,
    decrypt,
    encrypt,
    resolve_service_name,
)
from modules.utils.logger import get_logger

logger = get_logger(__name__)


# ── Entrada segura de contraseñas ─────────────────────────────────────────────

def _secure_input(prompt: str) -> str:
    """
    Solicita un valor secreto al usuario ocultando lo que escribe.

    Intenta usar getpass.getpass() como primera opción, que oculta
    completamente la entrada sin mostrar ningún carácter en pantalla.

    Si getpass no tiene acceso a una terminal real (caso habitual al
    ejecutar desde un IDE como PyCharm o VS Code, o desde ciertos
    terminales emulados en Windows), captura el KeyboardInterrupt que
    lanza en ese contexto y recurre a input() como fallback, avisando
    al usuario de que lo que escriba será visible en pantalla.

    Este comportamiento es un bug conocido de getpass en Windows cuando
    stdin no es una terminal interactiva real (msvcrt no disponible).

    Args:
        prompt: Texto del prompt que se muestra al usuario.

    Returns:
        Valor introducido por el usuario como string.
    """
    try:
        return getpass.getpass(prompt=prompt)

    except (KeyboardInterrupt, Exception): 
        # getpass no tiene acceso a terminal real.
        # Saltamos a la línea siguiente para separar visualmente el aviso.
        print()
        logger.warning(
            "getpass no disponible en este terminal. "
            "Usando input() como fallback: la entrada será visible en pantalla."
        )
        print(
            "  ⚠ Aviso: este terminal no soporta entrada oculta.\n"
            "  Lo que escribas a continuación será visible en pantalla."
        )
        # Restaurar stdin por si getpass lo dejó en un estado inconsistente
        try:
            sys.stdin = open( "con:", "r", encoding="utf-8" )   # "con:" es la consola en Windows
        except OSError:
            pass                            # Si falla, continuamos con el stdin actual
        return input(prompt)

class CredentialManager:
    """
    Gestiona el ciclo de vida completo de las credenciales del proyecto:
    almacenamiento cifrado, recuperación automática e interacción con el
    usuario cuando una credencial no existe o no puede descifrarse.

    Todas las operaciones de lectura y escritura se realizan contra
    Windows Credential Manager a través de la librería keyring.

    Uso típico:
        manager = CredentialManager()

        # Credencial simple (PAT de Azure)
        pat = manager.get_credential("azure_pat")

        # Credencial de login (SQL Server)
        username, password = manager.get_login("sql_login")
    """

    def __init__(self) -> None:
        """
        Inicializa el gestor resolviendo el nombre de servicio activo.

        El nombre de servicio se lee desde la variable de entorno
        ATM_SERVICE_NAME (ver crypto.resolve_service_name). Es el
        identificador del "espacio de nombres" en el Credential Manager
        y debe ser el mismo en todos los proyectos que compartan credenciales.
        """
        self._service = resolve_service_name()
        logger.debug(
            "CredentialManager inicializado. Servicio activo: '%s'.", self._service
        )

    # ── Interfaz pública ──────────────────────────────────────────────────────

    def get_credential(self, credential_key: str) -> str:
        """
        Recupera una credencial de tipo TOKEN (valor único).

        Flujo:
            1. Busca el token cifrado en el Credential Manager.
            2. Si lo encuentra, lo descifra y devuelve el valor en claro.
            3. Si no lo encuentra, solicita el valor al usuario por consola,
               lo cifra y lo guarda para usos futuros.
            4. Si el descifrado falla (clave cambiada, token corrupto),
               elimina la entrada inválida y vuelve al paso 3.

        Args:
            credential_key: Nombre clave de la credencial
                            (ej. "azure_pat").

        Returns:
            Valor de la credencial en texto plano.

        Raises:
            ValueError: Si credential_key es None o está vacío.
            SystemExit: Si el usuario no introduce ningún valor cuando
                        se le solicita la credencial.

        Example:
            >>> pat = manager.get_credential("azure_pat")
        """
        self._validate_key(credential_key)

        logger.debug(
            "Buscando credencial '%s' en servicio '%s'...",
            credential_key, self._service
        )

        raw_token = self._keyring_get(credential_key)

        if raw_token is not None:
            # Credencial encontrada → intentar descifrar
            decrypted = self._safe_decrypt(credential_key, raw_token)
            if decrypted is not None:
                logger.debug(
                    "Credencial '%s' recuperada automáticamente del Credential Manager.",
                    credential_key
                )
                return decrypted
            # _safe_decrypt devolvió None → token inválido ya eliminado,
            # continuar para solicitar al usuario

        # Credencial no encontrada o eliminada por ser inválida → pedir al usuario
        return self._prompt_and_save_credential(credential_key)

    def get_login(self, credential_key: str) -> tuple[str, str]:
        """
        Recupera una credencial de tipo LOGIN (usuario + contraseña).

        Los dos valores se almacenan juntos como un objeto JSON cifrado
        en una sola entrada del Credential Manager, garantizando que
        usuario y contraseña están siempre en sincronía.

        Flujo idéntico al de get_credential(), adaptado para solicitar
        y devolver dos valores en lugar de uno.

        Args:
            credential_key: Nombre clave del login
                            (ej. "sql_login").

        Returns:
            Tupla (username, password) ambos en texto plano.

        Raises:
            ValueError: Si credential_key es None o está vacío.
            SystemExit: Si el usuario no introduce alguno de los valores
                        cuando se le solicitan.

        Example:
            >>> username, password = manager.get_login("sql_login")
        """
        self._validate_key(credential_key)

        logger.debug(
            "Buscando login '%s' en servicio '%s'...",
            credential_key, self._service
        )

        raw_token = self._keyring_get(credential_key)

        if raw_token is not None:
            result = self._safe_decrypt_login(credential_key, raw_token)
            if result is not None:
                logger.debug(
                    "Login '%s' recuperado automáticamente del Credential Manager.",
                    credential_key
                )
                return result
            # Token inválido ya eliminado → continuar para pedir al usuario

        return self._prompt_and_save_login(credential_key)

    def delete_credential(self, credential_key: str) -> bool:
        """
        Elimina una credencial del Credential Manager.

        Útil para forzar la rotación de una credencial: tras eliminarla,
        la próxima llamada a get_credential() o get_login() solicitará
        al usuario que la introduzca de nuevo.

        Args:
            credential_key: Nombre clave de la credencial a eliminar.

        Returns:
            True  si la credencial existía y se eliminó correctamente.
            False si la credencial no existía.

        Raises:
            ValueError: Si credential_key es None o está vacío.

        Example:
            >>> manager.delete_credential("azure_pat")
            True
        """
        self._validate_key(credential_key)

        existing = self._keyring_get(credential_key)
        if existing is None:
            logger.warning(
                "delete_credential: la credencial '%s' no existe en el "
                "servicio '%s'. No hay nada que eliminar.",
                credential_key, self._service
            )
            return False

        try:
            keyring.delete_password(self._service, credential_key)
            logger.debug(
                "Credencial '%s' eliminada del Credential Manager (servicio '%s').",
                credential_key, self._service
            )
            return True

        except keyring.errors.PasswordDeleteError as e:
            logger.error(
                "Error al eliminar la credencial '%s': %s",
                credential_key, e
            )
            raise

    def credential_exists(self, credential_key: str) -> bool:
        """
        Comprueba si una credencial existe en el Credential Manager,
        sin intentar descifrarla.

        Útil para diagnóstico y verificación del estado del sistema
        sin alterar ninguna entrada.

        Args:
            credential_key: Nombre clave de la credencial a comprobar.

        Returns:
            True si la entrada existe (aunque su token pudiera ser inválido).
            False si no existe ninguna entrada para esa clave.
        """
        self._validate_key(credential_key)
        return self._keyring_get(credential_key) is not None

    # ── Métodos privados: flujos de solicitud al usuario ──────────────────────

    def _prompt_and_save_credential(self, credential_key: str) -> str:
        """
        Solicita una credencial de tipo TOKEN al usuario por consola
        y la guarda cifrada en el Credential Manager.

        Usa _secure_input() para ocultar lo que el usuario escribe.
        Si el terminal no soporta entrada oculta (ej. IDE, terminal
        emulado), avisa al usuario y recurre a input() como fallback.

        Args:
            credential_key: Nombre clave de la credencial a solicitar.

        Returns:
            Valor introducido por el usuario en texto plano.

        Raises:
            SystemExit: Si el usuario no introduce ningún valor.
        """
        print(f"\n  Credencial '{credential_key}' no encontrada en el sistema.")

        value = _secure_input(
            prompt=f"  Introduce el valor para '{credential_key}': "
        )

        if not value.strip():
            raise SystemExit(
                f"No se introdujo ningún valor para '{credential_key}'. "
                "Ejecución cancelada."
            )

        self._save_credential(credential_key, value.strip())
        return value.strip()

    def _prompt_and_save_login(self, credential_key: str) -> tuple[str, str]:
        """
        Solicita las credenciales de tipo LOGIN (usuario + contraseña)
        al usuario por consola y las guarda cifradas juntas como JSON
        en el Credential Manager.

        El nombre de usuario se muestra mientras se escribe (no es secreto).
        La contraseña se oculta con getpass.

        Args:
            credential_key: Nombre clave del login a solicitar.

        Returns:
            Tupla (username, password) en texto plano.

        Raises:
            SystemExit: Si el usuario no introduce alguno de los valores.
        """
        print(f"\n  Credencial de login '{credential_key}' no encontrada en el sistema.")

        # El nombre de usuario no es secreto: se muestra al escribir
        username = input(
            f"  Introduce el nombre de usuario para '{credential_key}': "
        ).strip()

        if not username:
            raise SystemExit(
                f"No se introdujo ningún nombre de usuario para '{credential_key}'. "
                "Ejecución cancelada."
            )

        # La contraseña sí es secreta: se oculta con _secure_input
        password = _secure_input(
            prompt=f"  Introduce la contraseña para '{credential_key}': "
        )

        if not password.strip():
            raise SystemExit(
                f"No se introdujo ninguna contraseña para '{credential_key}'. "
                "Ejecución cancelada."
            )

        self._save_login(credential_key, username, password.strip())
        return username, password.strip()

    # ── Métodos privados: cifrado y persistencia ──────────────────────────────

    def _save_credential(self, credential_key: str, value: str) -> None:
        """
        Cifra un valor TOKEN y lo guarda en el Credential Manager.

        Args:
            credential_key: Nombre clave de la credencial.
            value:          Valor en texto plano a cifrar y guardar.
        """
        token = encrypt(value)
        keyring.set_password(self._service, credential_key, token)
        logger.debug(
            "Credencial '%s' guardada correctamente en el Credential Manager "
            "(servicio '%s').",
            credential_key, self._service
        )
        print(f"  ✔ Credencial '{credential_key}' guardada correctamente.\n")

    def _save_login(
        self, credential_key: str, username: str, password: str
    ) -> None:
        """
        Serializa un par (username, password) como JSON, lo cifra y
        lo guarda como una única entrada en el Credential Manager.

        Guardar los dos valores juntos garantiza que siempre están
        sincronizados: no puede existir solo el usuario sin la contraseña
        ni viceversa.

        Args:
            credential_key: Nombre clave del login.
            username:       Nombre de usuario en texto plano.
            password:       Contraseña en texto plano.
        """
        payload = json.dumps({"username": username, "password": password})
        token   = encrypt(payload)
        keyring.set_password(self._service, credential_key, token)
        logger.debug(
            "Login '%s' guardado correctamente en el Credential Manager "
            "(servicio '%s').",
            credential_key, self._service
        )
        print(f"  ✔ Login '{credential_key}' guardado correctamente.\n")

    # ── Métodos privados: descifrado seguro ───────────────────────────────────

    def _safe_decrypt(
        self, credential_key: str, raw_token: str
    ) -> Optional[str]:
        """
        Intenta descifrar un token TOKEN. Si el descifrado falla,
        elimina la entrada inválida del Credential Manager y devuelve
        None para que el flujo solicite la credencial al usuario.

        Esto cubre el caso en que ATM_KEY_MATERIAL o ATM_KEY_SALT han
        cambiado desde que se guardó la credencial, haciendo indescifrables
        los tokens existentes.

        Args:
            credential_key: Nombre clave de la credencial (para logs y borrado).
            raw_token:      Token cifrado leído del Credential Manager.

        Returns:
            Valor descifrado en texto plano, o None si el descifrado falló.
        """
        try:
            return decrypt(raw_token)

        except DecryptionError:
            logger.warning(
                "El token de '%s' no pudo descifrarse. Es posible que las claves "
                "de cifrado hayan cambiado. Se eliminará la entrada y se solicitará "
                "la credencial de nuevo.",
                credential_key
            )
            print(
                f"\n  ⚠ La credencial '{credential_key}' almacenada no puede leerse "
                f"(la clave de cifrado puede haber cambiado).\n"
                f"  Se solicitará de nuevo."
            )
            self._delete_silently(credential_key)
            return None

    def _safe_decrypt_login(
        self, credential_key: str, raw_token: str
    ) -> Optional[tuple[str, str]]:
        """
        Intenta descifrar y deserializar un token LOGIN. Si falla,
        elimina la entrada inválida y devuelve None.

        Args:
            credential_key: Nombre clave del login.
            raw_token:      Token cifrado leído del Credential Manager.

        Returns:
            Tupla (username, password) en claro, o None si falló.
        """
        try:
            plain = decrypt(raw_token)
            data  = json.loads(plain)
            return data["username"], data["password"]

        except DecryptionError:
            logger.warning(
                "El token de login '%s' no pudo descifrarse. "
                "Se eliminará y se solicitará de nuevo.",
                credential_key
            )
            print(
                f"\n  ⚠ El login '{credential_key}' almacenado no puede leerse "
                f"(la clave de cifrado puede haber cambiado).\n"
                f"  Se solicitará de nuevo."
            )
            self._delete_silently(credential_key)
            return None

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(
                "El token de login '%s' está malformado (JSON inválido): %s. "
                "Se eliminará y se solicitará de nuevo.",
                credential_key, e
            )
            print(
                f"\n  ⚠ El login '{credential_key}' almacenado está corrupto.\n"
                f"  Se solicitará de nuevo."
            )
            self._delete_silently(credential_key)
            return None

    # ── Métodos privados: operaciones sobre keyring ───────────────────────────

    def _keyring_get(self, credential_key: str) -> Optional[str]:
        """
        Lee el token cifrado del Credential Manager.

        Encapsula la llamada a keyring.get_password() para centralizar
        el manejo de errores y los mensajes de log.

        Args:
            credential_key: Nombre clave de la credencial.

        Returns:
            Token cifrado como string, o None si no existe la entrada.
        """
        try:
            return keyring.get_password(self._service, credential_key)
        except keyring.errors.KeyringError as e:
            logger.error(
                "Error al acceder al Credential Manager para la clave '%s': %s",
                credential_key, e
            )
            raise

    def _delete_silently(self, credential_key: str) -> None:
        """
        Elimina una entrada del Credential Manager sin lanzar excepción
        si no existe. Usado internamente para limpiar tokens inválidos.

        Args:
            credential_key: Nombre clave de la credencial a eliminar.
        """
        try:
            keyring.delete_password(self._service, credential_key)
            logger.debug(
                "Entrada '%s' eliminada del Credential Manager.", credential_key
            )
        except keyring.errors.PasswordDeleteError:
            # Si ya no existía, no es un error: el objetivo se cumple igual
            logger.debug(
                "La entrada '%s' no existía al intentar eliminarla (ignorado).",
                credential_key
            )

    # ── Métodos privados: validación ──────────────────────────────────────────

    @staticmethod
    def _validate_key(credential_key: str) -> None:
        """
        Valida que el nombre clave de la credencial no sea None ni vacío.

        Args:
            credential_key: Valor a validar.

        Raises:
            ValueError: Si el valor es None, vacío o solo espacios.
        """
        if not credential_key or not credential_key.strip():
            raise ValueError(
                "El nombre clave de la credencial no puede ser None ni estar vacío."
            )
