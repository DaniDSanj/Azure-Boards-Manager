"""Orquesta la extracción de tarjetas desde Azure Boards."""

from typing import Any, Dict, List

from modules.pipeline.azure_extractor import AzureDevOpsExtractor
from modules.pipeline.transformer import WorkItemTransformer
from modules.sql import LoadStrategy, create_sql_client
from modules.utils.config import AppConfig , load_config
from modules.utils.logger import Dest, get_log_dataframe, get_logger

logger = get_logger(__name__, capture_to_df=True)

def _resolve_root_ids(config_ids: List[int]) -> List[int]:
    """
    Determina la lista de IDs a procesar.

    Si el .env define AZURE_ROOT_IDS, se usa esa lista directamente.
    Si no, se solicita un único ID al usuario por consola.

    Args:
        config_ids: Lista de IDs cargada desde AppConfig (puede estar vacía).

    Returns:
        Lista de enteros con los IDs a procesar. Nunca vacía.

    Raises:
        ValueError: Si el usuario introduce un valor no numérico.
        SystemExit: Si el usuario no introduce ningún valor.
    """
    if config_ids:
        logger.info(
            "IDs cargados desde .env: %s (%d tarjeta(s)).",
            config_ids, len(config_ids),
        )
        return config_ids

    logger.info("No se encontró AZURE_ROOT_IDS en el .env. Modo de ejecución individual.")
    raw = input("\n  Introduce el ID de la tarjeta raíz a procesar: ").strip()

    if not raw:
        raise SystemExit("No se introdujo ningún ID. Ejecución cancelada.")

    try:
        root_id = int(raw)
    except ValueError as exc:
        raise ValueError( f"El valor introducido '{raw}' no es un número entero válido." ) from exc

    logger.info("ID introducido por el usuario: %d", root_id)
    return [root_id]

def _extract_all(
    extractor: AzureDevOpsExtractor,
    root_ids: List[int],
) -> List[Dict[str, Any]]:
    """
    Itera sobre todos los IDs, extrae sus tarjetas y genera un JSON por ID.

    Si la extracción de un ID falla, registra el error en el log y continúa
    con el siguiente, de forma que un fallo parcial no bloquea el proceso.

    Args:
        extractor: Instancia de AzureDevOpsExtractor ya conectada.
        root_ids:  Lista de IDs raíz a procesar.

    Returns:
        Lista acumulada de todos los work items extraídos correctamente.
    """
    all_work_items: List[Dict[str, Any]] = []
    failed_ids: List[int] = []

    for root_id in root_ids:
        logger.info("--- Procesando ID: %d ---", root_id)

        try:
            items = extractor.get_work_items_by_id(root_id=root_id)

            if not items:
                logger.warning("ID %d: no se encontraron tarjetas. Se omite.", root_id)
                continue

            logger.info("ID %d: %d tarjetas extraídas.", root_id, len(items))

            # Exportar JSON individual en crudo (sin transformaciones),
            # con nombre estructurado: work_items_{root_id}_{yyyymmdd_hhmmss}.json
            extractor.export_to_json(items, root_id=root_id)

            all_work_items.extend(items)

        except (ValueError, KeyError, TimeoutError, ConnectionError) as e:
            logger.error("ID %d: fallo durante la extracción → %s. Se continúa.", root_id, e)
            failed_ids.append(root_id)

    logger.info(
        "Extracción completada: %d tarjetas acumuladas de %d/%d IDs procesados.",
        len(all_work_items),
        len(root_ids) - len(failed_ids),
        len(root_ids),
    )

    if failed_ids:
        logger.warning("IDs con error durante la extracción: %s", failed_ids)

    return all_work_items


def _flush_logs_to_sql( loader , config: AppConfig ) -> None:
    """
    Vuelca el DataFrame de logs de la ejecución actual a SQL Server.

    Usa la estrategia INSERT para acumular el historial de ejecuciones
    sin borrar registros anteriores. La tabla [logs].[ejecuciones] se
    crea automáticamente si no existe.

    Si el volcado falla, registra el error pero no interrumpe el proceso:
    el fichero .log sigue siendo el respaldo primario.

    Args:
        loader: Instancia de SqlLoader ya inicializada y conectada.
        config (AppConfig): Configuración de la ejecución actual.
    """
    try:
        log_df = get_log_dataframe()

        if log_df.empty:
            logger.warning(
                "El DataFrame de logs está vacío. No se realizará la carga a SQL.",
                dest=Dest.FILE,
            )
            return

        logger.info(
            "Volcando %d registros de log a [%s].[%s]...",
            len(log_df), config.sql_log_schema, config.sql_log_table,
            dest=Dest.FILE,
        )

        loader.load(
            log_df,
            schema=config.sql_log_schema,
            table=config.sql_log_table,
            strategy=LoadStrategy.INSERT,
        )

    except (ValueError, KeyError, TimeoutError, ConnectionError) as e:
        logger.error(
            "No se pudo volcar el DataFrame de logs a SQL Server: %s. "
            "Los logs están disponibles en el fichero .log como respaldo.",
            e,
        )


def main() -> None:
    """Función principal de orquestación."""

    logger.info("Iniciando ejecución...")

    # 1. Cargar configuración desde .env y Credential Manager
    config = load_config()

    # 2. Resolver IDs: desde .env o solicitando al usuario
    root_ids = _resolve_root_ids(config.azure_root_ids)
    logger.info("IDs a procesar: %s", root_ids)

    # 3. Inicializar el extractor de Azure Boards
    logger.info("Conectando con Azure DevOps...")
    extractor = AzureDevOpsExtractor(
        organization_url=config.azure_org_url,
        project_name=config.azure_project,
        personal_access_token=config.azure_pat,
        fields=config.azure_fields or None,
    )

    # 4. Extraer tarjetas de todos los IDs (JSON individual por cada uno)
    logger.info("Extrayendo tarjetas de Azure Boards...")
    all_work_items = _extract_all(extractor, root_ids)
    logger.info("Total de tarjetas extraídas: %d", len(all_work_items))

    if not all_work_items:
        logger.warning("No se han extraído tarjetas de ningún ID. Proceso finalizado sin carga.")
        return

    # 5. Transformar: limpiar, validar y preparar el DataFrame para SQL Server
    logger.info("Transformando tarjetas...")
    transformer = WorkItemTransformer()
    df = transformer.transform(all_work_items)
    logger.info("Total de tarjetas transformadas: %d", len(df))

    # 6. Inicializar el módulo SQL (loader + executor comparten la misma conexión)
    loader, executor = create_sql_client(
        server=config.sql_server,
        database=config.sql_database,
        username=config.sql_user,
        password=config.sql_password,
    )
    logger.ok("Conexión a SQL Server establecida.")

    # 7. Cargar el DataFrame en SQL Server (truncar y recargar completamente)
    logger.info("Cargando tarjetas a SQL Server...")
    loader.load(
        df,
        schema=config.sql_dest_schema,
        table=config.sql_dest_table,
        strategy=LoadStrategy.TRUNCATE_INSERT,
    )
    logger.ok("Tarjetas cargadas correctamente.")

    # 8. Ejecutar el procedimiento almacenado de lógica incremental
    logger.info("Ejecutando procedimiento '%s'...", config.sql_stored_procedure)
    result = executor.execute_procedure(config.sql_stored_procedure)

    if result is False:
        logger.error(
            "El procedimiento '%s' falló. Revisa el log para más detalles.",
            config.sql_stored_procedure,
        )
    else:
        logger.ok("Procedimiento '%s' ejecutado correctamente.", config.sql_stored_procedure)

    logger.ok("Proceso finalizado correctamente")

    # 9. Volcar el DataFrame de logs a SQL Server (INSERT acumulativo).
    _flush_logs_to_sql(loader,config)

if __name__ == "__main__":
    main()
