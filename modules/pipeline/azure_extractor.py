"""Clase principal para la extracción de tarjetas (work items) desde Azure DevOps Boards."""

from datetime import datetime
import os
import json
from typing import Any, Dict, List, Optional
from azure.devops.connection import Connection
from azure.devops.exceptions import AzureDevOpsServiceError
from msrest.authentication import BasicAuthentication

from modules.utils.formatters import extract_identity, extract_parent_id, format_date, parse_tags
from modules.utils.logger import get_logger

logger = get_logger(__name__)

# Límite de IDs por petición de detalle (restricción de la API)
_BATCH_SIZE = 200

# Límite de resultados por consulta WIQL (restricción de la API)
_WIQL_MAX_RESULTS = 20_000

# Campos predeterminados que se usan cuando AZURE_FIELDS no está definido en el .env.
_DEFAULT_FIELDS: List[str] = [
    "System.Id",
    "System.WorkItemType",
    "System.Title",
    "System.State",
    "System.AssignedTo",
    "System.CreatedBy",
    "System.CreatedDate",
    "System.ChangedDate",
    "System.Tags",
    "System.AreaPath",
    "System.IterationPath",
    "System.Description",
    "Microsoft.VSTS.Common.Priority",
    "Microsoft.VSTS.Common.AcceptanceCriteria",
]

class AzureDevOpsExtractor:
    """
    Extractor de work items desde Azure DevOps Boards.

    Soporta filtrado por épica, etiquetas, tipo de work item
    y consultas WIQL personalizadas.
    """

    def __init__(
        self,
        organization_url: str,
        project_name: str,
        personal_access_token: str,
        fields: Optional[List[str]] = None,
    ) -> None:
        """
        Inicializa la conexión con Azure DevOps.

        Args:
            organization_url:      URL base de la organización
                                   (ej. 'https://dev.azure.com/mi-org').
            project_name:          Nombre del proyecto en Azure DevOps.
            personal_access_token: PAT con permisos de lectura en Work Items.
            fields:                Lista de campos a extraer en cada petición.
                                   Si es None o lista vacía, se utiliza
                                   _DEFAULT_FIELDS como fallback.

        Raises:
            ConnectionError: Si la conexión con Azure DevOps falla.
        """
        self.organization_url = organization_url
        self.project_name = project_name
        self._fields: List[str] = _DEFAULT_FIELDS + fields if fields else _DEFAULT_FIELDS

        if fields:
            logger.debug(
                "Campos de extracción cargados desde AZURE_FIELDS (%d campos).",
                len(self._fields),
            )
        else:
            logger.debug(
                "AZURE_FIELDS no definido en el .env. "
                "Usando _DEFAULT_FIELDS (%d campos).",
                len(self._fields),
            )

        # La autenticación con PAT usa string vacío como nombre de usuario
        credentials = BasicAuthentication("", personal_access_token)

        try:
            self.connection = Connection(base_url=organization_url, creds=credentials)
            self.wit_client = self.connection.clients.get_work_item_tracking_client()

            logger.debug("Conexión establecida con %s", organization_url)
            logger.debug("Proyecto activo: %s", project_name)

        except Exception as e:
            raise ConnectionError(f"No se pudo conectar a Azure DevOps: {e}") from e

    # ------------------------------------------------------------------
    # Métodos públicos de consulta
    # ------------------------------------------------------------------

    def get_all_work_items(
        self, fields: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Recupera todos los work items del proyecto.

        Args:
            fields: Lista de campos a recuperar. Si es None, devuelve todos.
                    Campos comunes: 'System.Id', 'System.Title',
                    'System.State', 'System.AssignedTo', 'System.Tags',
                    'System.WorkItemType'.

        Returns:
            Lista de diccionarios con los datos de cada work item.
        """
        wiql_query = f"""
            SELECT [System.Id]
            FROM WorkItems
            WHERE [System.TeamProject] = '{self.project_name}'
            ORDER BY [System.CreatedDate] DESC
        """
        return self._execute_flat_query(wiql_query, fields, context="todos los work items")

    def get_work_items_by_id(
        self, root_id: int, fields: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Recupera una tarjeta y todos sus descendientes en cualquier nivel
        de jerarquía (Epic → Feature → User Story → Task → Sub-task...).

        La tarjeta raíz indicada por ``root_id`` se incluye siempre
        en los resultados, independientemente de su tipo.

        La búsqueda de hijos es recursiva: se obtienen todos los
        niveles de profundidad en una sola consulta WIQL gracias
        al modificador ``MODE (Recursive)``.

        Args:
            root_id: ID numérico de la tarjeta raíz (puede ser cualquier
                     tipo: Epic, Feature, User Story, etc.).
            fields:  Lista opcional de campos a recuperar.
                     Si es None, se devuelven todos los campos disponibles.

        Returns:
            Lista de diccionarios que incluye la tarjeta raíz y todos
            sus descendientes, en orden de creación descendente.

        Raises:
            Exception: Si la consulta a Azure DevOps falla.

        Example:
            >>> # Obtener una épica con todas sus features, historias y tareas
            >>> items = extractor.get_work_items_by_id(root_id=12120)
        """
        logger.debug("Buscando tarjeta ID %s y todos sus descendientes...", root_id)

        # Consulta jerárquica recursiva: obtiene todas las relaciones
        # padre → hijo en todos los niveles a partir del ID raíz
        wiql_query = f"""
            SELECT [System.Id]
            FROM WorkItemLinks
            WHERE ([Source].[System.Id] = {root_id})
              AND ([System.Links.LinkType] = 'System.LinkTypes.Hierarchy-Forward')
              AND ([Target].[System.TeamProject] = '{self.project_name}')
            MODE (Recursive)
        """

        try:
            wiql_result = self.wit_client.query_by_wiql(wiql={"query": wiql_query})

            # Recoger los IDs de todos los descendientes (relaciones target)
            child_ids: List[int] = []
            if wiql_result.work_item_relations:
                child_ids = [
                    relation.target.id
                    for relation in wiql_result.work_item_relations
                    if relation.target
                ]

            # Añadir siempre la tarjeta raíz al conjunto de IDs a recuperar
            # Usamos un set para evitar duplicados en caso de referencias cruzadas
            all_ids = list({root_id, *child_ids})

            logger.debug(
                "Tarjeta raíz + %d descendientes encontrados (total: %d tarjetas).",
                len(child_ids),
                len(all_ids),
            )

            return self._fetch_work_items_batch(all_ids, fields)

        except Exception as e:
            logger.error("Error al recuperar la tarjeta %s y sus hijos: %s", root_id, e)
            raise

    def get_work_items_by_tags(
        self,
        tags: List[str],
        match_all: bool = False,
        fields: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Recupera work items filtrados por etiquetas.

        Args:
            tags:      Lista de etiquetas (ej. ['urgente', 'backend']).
            match_all: True  → el work item debe tener TODAS las etiquetas.
                       False → basta con que tenga ALGUNA de ellas.
            fields:    Lista opcional de campos a recuperar.

        Returns:
            Lista de work items que cumplen el criterio de etiquetas.
        """
        logger.debug("Buscando work items con etiquetas %s (match_all=%s)", tags, match_all)

        operator = " AND " if match_all else " OR "
        tag_conditions = operator.join(
            [f"[System.Tags] CONTAINS '{tag}'" for tag in tags]
        )

        wiql_query = f"""
            SELECT [System.Id]
            FROM WorkItems
            WHERE [System.TeamProject] = '{self.project_name}'
              AND ({tag_conditions})
            ORDER BY [System.CreatedDate] DESC
        """
        return self._execute_flat_query(wiql_query, fields, context=f"etiquetas {tags}")

    def get_work_items_by_type(
        self,
        work_item_type: str,
        fields: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Recupera work items de un tipo específico.

        Args:
            work_item_type: Tipo exacto del work item
                            (ej. 'Bug', 'User Story', 'Task', 'Epic').
            fields:         Lista opcional de campos a recuperar.

        Returns:
            Lista de work items del tipo indicado.
        """
        wiql_query = f"""
            SELECT [System.Id]
            FROM WorkItems
            WHERE [System.TeamProject] = '{self.project_name}'
              AND [System.WorkItemType] = '{work_item_type}'
            ORDER BY [System.CreatedDate] DESC
        """
        return self._execute_flat_query(
            wiql_query, fields, context=f"tipo '{work_item_type}'"
        )

    def get_work_items_by_query(
        self,
        wiql_query: str,
        fields: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Ejecuta una consulta WIQL personalizada.

        Útil para casos de uso avanzados no cubiertos por los métodos anteriores.

        Args:
            wiql_query: Consulta WIQL completa en formato string.
            fields:     Lista opcional de campos a recuperar.

        Returns:
            Lista de work items resultado de la consulta.
        """
        return self._execute_flat_query(wiql_query, fields, context="consulta personalizada")

    # ------------------------------------------------------------------
    # Exportación
    # ------------------------------------------------------------------

    def export_to_json(
        self,
        work_items: List[Dict[str, Any]],
        root_id: int,
        output_dir: str = "output",
    ) -> str:
        """
        Exporta los work items a un fichero JSON con nombre estructurado.

        El nombre del fichero sigue el patrón:
            work_items_{root_id}_{yyyymmdd_hhmmss}.json

        Ejemplo:
            work_items_12120_20260217_143022.json

        Args:
            work_items:  Lista de work items a exportar.
            root_id:     ID de la tarjeta raíz ejecutada, incluido en el nombre.
            output_dir:  Directorio de salida. Por defecto 'output/'.
                         Se crea automáticamente si no existe.

        Returns:
            Ruta completa del fichero generado.

        Raises:
            Exception: Si la escritura del fichero falla.
        """

        # Construir el nombre con la estructura requerida
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"work_items_{root_id}_{timestamp}.json"

        os.makedirs(output_dir, exist_ok=True)
        filepath = os.path.join(output_dir, filename)

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(work_items, f, indent=2, ensure_ascii=False, default=str)

            logger.debug("Exportados %d work items a '%s'", len(work_items), filepath)
            return filepath

        except Exception as e:
            logger.error("Error al exportar a JSON: %s", e)
            raise

    # ------------------------------------------------------------------
    # Métodos privados
    # ------------------------------------------------------------------

    def _execute_flat_query(
        self,
        wiql_query: str,
        fields: Optional[List[str]],
        context: str = "",
    ) -> List[Dict[str, Any]]:
        """
        Ejecuta una consulta WIQL plana (FROM WorkItems) y devuelve
        los work items con detalle completo.

        Controla el límite de 20.000 resultados de la API: si se alcanza,
        emite una advertencia en el log indicando que los datos pueden
        estar incompletos.

        Args:
            wiql_query: Consulta WIQL a ejecutar.
            fields:     Campos a recuperar (None = todos).
            context:    Descripción del contexto para el log.

        Returns:
            Lista de work items formateados.
        """
        try:
            logger.debug("Ejecutando consulta WIQL [%s]", context)

            wiql_result = self.wit_client.query_by_wiql(
                wiql={"query": wiql_query},
                project=self.project_name,
            )

            work_item_ids = [item.id for item in wiql_result.work_items]

            if not work_item_ids:
                logger.warning("La consulta [%s] no devolvió resultados.", context)
                return []

            # Control del límite de 20.000 resultados de la API WIQL.
            # Si se alcanza exactamente, es probable que haya más tarjetas
            # que no se están recuperando.
            if len(work_item_ids) >= _WIQL_MAX_RESULTS:
                logger.warning(
                    "[%s] La consulta ha devuelto %d resultados, "
                    "lo que indica que se ha alcanzado el límite máximo de la API "
                    "(%d items). Es posible que existan tarjetas "
                    "adicionales que no se están recuperando. "
                    "Considera acotar la consulta con filtros de fecha, estado u otros criterios.",
                    context,
                    len(work_item_ids),
                    _WIQL_MAX_RESULTS,
                )
            else:
                logger.debug("Encontrados %d work items [%s].", len(work_item_ids), context)

            return self._fetch_work_items_batch(work_item_ids, fields)

        except Exception as e:
            logger.error("Error en consulta [%s]: %s", context, e)
            raise

    def _fetch_work_items_batch(
        self,
        work_item_ids: List[int],
        fields: Optional[List[str]],
    ) -> List[Dict[str, Any]]:
        """
        Recupera los detalles completos de una lista de work items
        en lotes de {_BATCH_SIZE} para respetar el límite de la API.

        Args:
            work_item_ids: Lista de IDs de work items a recuperar.
            fields:        Campos a incluir (None = todos).

        Returns:
            Lista de diccionarios formateados con los datos de cada work item.
        """
        all_work_items: List[Dict[str, Any]] = []
        effective_fields = fields if fields is not None else self._fields

        for i in range(0, len(work_item_ids), _BATCH_SIZE):
            batch_ids = work_item_ids[i: i + _BATCH_SIZE]

            try:
                # ── Llamada 1: campos de datos ──────────────────────────────────
                items_data = self.wit_client.get_work_items(
                    ids=batch_ids,
                    fields=effective_fields,
                )

                # ── Llamada 2: relaciones (para extraer parent_id) ──────────────
                items_relations = self.wit_client.get_work_items(
                    ids=batch_ids,
                    fields=None,
                    expand="Relations",
                )

                # Indexar las relaciones por ID para el cruce posterior
                relations_by_id = {item.id: item.relations for item in items_relations}

                for item in items_data:
                    item.relations = relations_by_id.get(item.id)
                    all_work_items.append(self._format_work_item(item))

            except AzureDevOpsServiceError as e:
                logger.warning(
                    "Fallo en el lote de IDs [%d:%d]: %s. Se continúa con el siguiente lote.",
                    i,
                    i + _BATCH_SIZE,
                    e,
                )

        logger.debug("Recuperados %d work items en total.", len(all_work_items))
        return all_work_items

    def _format_work_item(self, work_item: Any) -> Dict[str, Any]:
        """
        Convierte un objeto work item de la API en un diccionario limpio.

        El campo ``parent_id`` contiene únicamente el ID numérico de la
        tarjeta padre, lo que permite construir directamente la clave
        foránea en SQL Server sin procesamiento adicional.

        Args:
            work_item: Objeto work item devuelto por la API de Azure DevOps.

        Returns:
            Diccionario estructurado con los campos relevantes del work item.
        """
        fields = work_item.fields
        work_item_dict = {
            "Id": work_item.id ,
            "Tipo": fields.get("System.WorkItemType") ,
            "Titulo": fields.get("System.Title") ,
            "Estado": fields.get("System.State") ,
            "UsuarioAsignado": extract_identity(fields.get("System.AssignedTo")) ,
            "UsuarioCreacion": extract_identity(fields.get("System.CreatedBy")) ,
            "FechaCreacion": format_date(fields.get("System.CreatedDate")) ,
            "FechaModificacion": format_date(fields.get("System.ChangedDate")) ,
            "Etiquetas": parse_tags(fields.get("System.Tags")) ,
            "Area": fields.get("System.AreaPath") ,
            "Iteracion": fields.get("System.IterationPath") ,
            "Prioridad": fields.get("Microsoft.VSTS.Common.Priority") ,
            "Descripcion": fields.get("System.Description") ,
            "CriteriosAceptacion": fields.get("Microsoft.VSTS.Common.AcceptanceCriteria") ,
            "IdPadre": extract_parent_id(work_item.relations) ,
            "HitoArea": fields.get("Custom.Area") ,
            "HitoSubArea": fields.get("Custom.Subarea") ,
            "HitoCategoria": fields.get("Custom.CategoriaHito") ,
            "HitoResponsable": extract_identity(fields.get("Custom.Responsable")) ,
            "HitoEstado": fields.get("Custom.Estado") ,
            "HitoMotivoEstado": fields.get("Custom.MotivoEstado") ,
            "HitoFechaAlta": format_date(fields.get("Custom.FechadeAlta")) ,
            "HitoFechaBaja": format_date(fields.get("Custom.FechaBaja")) ,
            "HitoObjetivoApp": fields.get("Custom.ObjetivoAprobacion") ,
            "HitoObjetivoRiesgo": fields.get("Custom.ObjetivoRiesgo") ,
            "HitoObjetivoVolumen": fields.get("Custom.ObjetivoVolumen") ,
        }

        return work_item_dict
