"""Módulo de transformación y calidad del dato."""

import re
from typing import Any, Dict, List
import pandas as pd
from bs4 import BeautifulSoup

from modules.utils.logger import get_logger

logger = get_logger(__name__)

# Columnas que se eliminan antes de la carga a SQL Server
_COLUMNS_TO_DROP = []

# Columnas de texto que pueden contener HTML
_HTML_COLUMNS = ["Descripcion","CriteriosAceptacion","HitoMotivoEstado"]

# Columna que actúa como clave primaria y no puede ser nula ni duplicada
_PK_COLUMN = "Id"

class WorkItemTransformer:
    """
    Transforma una lista de work items en crudo en un DataFrame
    limpio y validado, listo para su carga en SQL Server.

    Uso típico:
        transformer = WorkItemTransformer()
        df = transformer.transform(work_items)
    """

    def transform(self, work_items: List[Dict[str, Any]]) -> pd.DataFrame:
        """
        Ejecuta el pipeline completo de transformación y validación.

        Pasos que se aplican en orden:
            1. Conversión a DataFrame.
            2. Validaciones de calidad (nulos y duplicados en 'id').
            3. Eliminación de columnas innecesarias.
            4. Limpieza de HTML en campos de texto.
            5. Normalización del campo de etiquetas.

        Args:
            work_items: Lista de diccionarios devuelta por AzureDevOpsExtractor.

        Returns:
            DataFrame de pandas con los datos transformados y validados.

        Raises:
            ValueError: Si la lista de work items está vacía.
        """
        if not work_items:
            raise ValueError("La lista de work items está vacía. No hay datos que transformar.")

        logger.debug("Iniciando transformación de %d work items...", len(work_items))

        df = pd.DataFrame(work_items)
        logger.debug("DataFrame creado con %d filas y %d columnas.", len(df), len(df.columns))

        df = self._validate_quality(df)
        df = self._drop_unnecessary_columns(df)
        df = self._clean_html_fields(df)
        df = self._normalize_tags(df)

        logger.debug("Transformación completada: %d filas listas para carga.", len(df))
        return df

    # ── Pasos del pipeline ───────────────────────────────────────────────────

    def _validate_quality(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Aplica validaciones de calidad sobre el DataFrame.

        Validaciones:
            - Elimina filas cuyo campo 'id' sea nulo.
            - Elimina filas duplicadas por 'id', conservando
              la primera ocurrencia (la más reciente según el orden
              de extracción).

        Ambas situaciones se registran en el log con el número de
        filas descartadas para trazabilidad.

        Args:
            df: DataFrame con los work items en crudo.

        Returns:
            DataFrame validado y sin filas problemáticas.
        """
        initial_count = len(df)

        # 1. Eliminar filas con id nulo
        null_ids = df[_PK_COLUMN].isna().sum()
        if null_ids > 0:
            df = df.dropna(subset=[_PK_COLUMN])
            logger.warning(
                "Calidad del dato: se han descartado %d fila(s) "
                "con '%s' nulo.", null_ids, _PK_COLUMN
            )

        # 2. Eliminar duplicados por id
        duplicate_ids = df.duplicated(subset=[_PK_COLUMN], keep="first").sum()
        if duplicate_ids > 0:
            df = df.drop_duplicates(subset=[_PK_COLUMN], keep="first")
            logger.warning(
                "Calidad del dato: se han descartado %d fila(s) "
                "duplicadas por '%s'.", duplicate_ids, _PK_COLUMN
            )

        total_discarded = initial_count - len(df)
        if total_discarded == 0:
            logger.debug("Validación de calidad superada. No se han descartado filas.")
        else:
            logger.warning(
                "Validación completada. Total de filas descartadas: %d "
                "(de %d originales).", total_discarded, initial_count
            )

        return df

    def _drop_unnecessary_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Elimina las columnas que no aportan valor en SQL Server.

        Las columnas eliminadas están definidas en ``_COLUMNS_TO_DROP``.
        Si alguna de ellas no existe en el DataFrame, se ignora
        silenciosamente para evitar errores en extracciones parciales.

        Args:
            df: DataFrame tras la validación de calidad.

        Returns:
            DataFrame sin las columnas innecesarias.
        """
        existing = [col for col in _COLUMNS_TO_DROP if col in df.columns]
        dropped = df.drop(columns=existing)

        if existing:
            logger.debug("Columnas eliminadas: %s", existing)

        return dropped

    def _clean_html_fields(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Limpia el HTML de los campos de texto enriquecido.

        Azure DevOps almacena 'description' y 'acceptance_criteria'
        en formato HTML. Esta función extrae el texto plano eliminando
        todas las etiquetas, normalizando espacios y saltos de línea.

        Los campos ausentes en el DataFrame se ignoran silenciosamente.

        Args:
            df: DataFrame tras la eliminación de columnas.

        Returns:
            DataFrame con los campos de texto en texto plano.
        """
        for col in _HTML_COLUMNS:
            if col not in df.columns:
                continue

            df[col] = df[col].apply(self._strip_html)
            logger.debug("HTML limpiado en columna '%s'.", col)

        return df

    def _normalize_tags(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Convierte el campo 'tags' de lista Python a VARCHAR separado por comas.

        Antes de la transformación:
            tags = ["backend", "api", "urgente"]

        Después de la transformación:
            tags = "backend, api, urgente"

        Si el campo 'tags' no existe o está vacío, se asigna
        una cadena vacía (nunca NULL) para consistencia en SQL Server.

        Args:
            df: DataFrame tras la limpieza de HTML.

        Returns:
            DataFrame con el campo 'tags' como VARCHAR.
        """
        if "tags" not in df.columns:
            return df

        df["tags"] = df["tags"].apply(
            lambda val: ", ".join(val) if isinstance(val, list) and val else ""
        )
        logger.debug("Campo 'tags' normalizado a VARCHAR separado por comas.")

        return df

    # ── Métodos estáticos auxiliares ─────────────────────────────────────────

    @staticmethod
    def _strip_html(value: Any) -> str:
        """
        Extrae el texto plano de un string HTML.

        Proceso:
            1. BeautifulSoup parsea el HTML y extrae el texto visible.
            2. Se normalizan los espacios múltiples y saltos de línea
               consecutivos para obtener un texto limpio y legible.

        Args:
            value: String HTML, None, o cualquier otro tipo.

        Returns:
            Texto plano limpio, o cadena vacía si el valor es nulo.

        Example:
            "<p>Descripción <b>importante</b></p>" → "Descripción importante"
        """
        if not value or not isinstance(value, str):
            return ""

        # Parsear el HTML y extraer el texto visible
        soup = BeautifulSoup(value, "html.parser")
        text = soup.get_text(separator=" ")

        # Normalizar espacios múltiples y saltos de línea consecutivos
        text = re.sub(r"\s+", " ", text).strip()

        return text
