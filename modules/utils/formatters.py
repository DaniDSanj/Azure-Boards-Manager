"""Funciones auxiliares de transformación y formateo de datos."""

from datetime import datetime
from typing import Any, List, Optional

from modules.utils.logger import get_logger

logger = get_logger(__name__)

def extract_identity(identity_field: Any) -> Optional[str]:
    """
    Extrae el nombre de usuario de un campo de identidad de Azure DevOps.

    Los campos de identidad pueden llegar como diccionario o como string,
    dependiendo de la versión de la API y del contexto.

    Args:
        identity_field: Campo de identidad devuelto por la API de Azure.

    Returns:
        Nombre de usuario legible, o None si el campo está vacío.
    """
    if identity_field:
        if isinstance(identity_field, dict):
            return identity_field.get("uniqueName")
        return str(identity_field)
    return None


def format_date(date_field: Any) -> Optional[str]:
    """
    Convierte un campo de fecha al formato ISO 8601 (string).

    Args:
        date_field: Fecha devuelta por la API (datetime o string).

    Returns:
        Fecha en formato ISO 8601, o None si el campo está vacío.
    """
    if date_field:
        if isinstance(date_field, datetime):
            return date_field.isoformat()
        return str(date_field)
    return None


def parse_tags(tags_field: Any) -> List[str]:
    """
    Convierte el campo de etiquetas de Azure (separado por ';')
    en una lista limpia de strings.

    Args:
        tags_field: String de etiquetas separadas por punto y coma.

    Returns:
        Lista de etiquetas sin espacios extra. Lista vacía si no hay etiquetas.

    Example:
        >>> parse_tags("backend; api; urgente")
        ['backend', 'api', 'urgente']
    """
    if tags_field:
        return [tag.strip() for tag in str(tags_field).split(";") if tag.strip()]
    return []

def extract_parent_id(relations: Any) -> Optional[int]:
    """
    Extrae el ID numérico de la tarjeta padre a partir de las relaciones
    de un work item.

    Azure DevOps representa el vínculo padre con el tipo
    ``System.LinkTypes.Hierarchy-Reverse``. El ID se obtiene
    parseando la URL de la relación, que siempre termina en ``/workItems/{id}``.

    Args:
        relations: Lista de objetos de relación devueltos por la API.
                   Puede ser None si la tarjeta no tiene relaciones.

    Returns:
        ID entero del padre directo, o None si la tarjeta no tiene padre.

    Example:
        URL de relación: '.../workItems/42'  →  devuelve 42
    """
    if not relations:
        return None

    for relation in relations:
        if relation.rel == "System.LinkTypes.Hierarchy-Reverse":
            try:
                # La URL tiene el formato: .../workItems/{id}
                return int(relation.url.rstrip("/").split("/")[-1])
            except (ValueError, AttributeError):
                logger.warning(
                    "No se pudo parsear el ID del padre desde la URL: %s", f"{relation.url!r}"
                )
                return None

    return None
