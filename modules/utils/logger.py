"""Sistema de logging centralizado y reutilizable."""

from __future__ import annotations

import getpass
import logging
import os
import uuid
from datetime import datetime
from enum import Enum
from logging.handlers import RotatingFileHandler
from typing import Any

import pandas as pd
import psutil
import tqdm as tqdm_module

# Configuración del proyecto
_PROJECT_NAME:  str = "Azure-Boards-Manager"
_LOG_FILE_NAME: str = f"{_PROJECT_NAME}.log"

_LOG_DIR  = os.getcwd() # os.path.join(os.path.dirname( os.path.dirname(__file__)), "logs" )
_LOG_FILE = os.path.join(_LOG_DIR, _LOG_FILE_NAME)

_MAX_BYTES    = 5 * 1024 * 1024
_BACKUP_COUNT = 3
_DATE_FORMAT  = "%Y-%m-%d %H:%M:%S"

# Nivel OK personalizado
_OK_LEVEL      = 25
_OK_LEVEL_NAME = "OK"

logging.addLevelName(_OK_LEVEL, _OK_LEVEL_NAME)

# Mapeo niveles → códigos HTTP
_HTTP_STATUS: dict[int, tuple[int, str]] = {
    logging.DEBUG:   (102, "Debugging             "),
    logging.INFO:    (200, "Information           "),
    _OK_LEVEL:       (201, "Success               "),
    logging.WARNING: (400, "Bad Request           "),
    logging.ERROR:   (500, "Internal Server Error "),
}
_HTTP_STATUS_DEFAULT: tuple[int, str] = (0, "Unknown               ")

# Columnas del DataFrame
_DF_COLUMNS: list[str] = [
    "Id_Ejecucion",
    "Usuario_Ejecucion",
    "Nombre_Proyecto",
    "Timestamp",
    "Nivel",
    "Codigo_HTTP",
    "Modulo",
    "Mensaje",
    "CPU_Porcentaje",
    "RAM_Porcentaje",
]

# Estado global de la ejecución
_execution_id:   str        = ""
_execution_user: str        = ""
_capture_active: bool       = False
_log_records:    list[dict] = []

# Enum de destinos
class Dest(Enum):
    """
    Destino de salida de un mensaje de log.

    Atributos:
        CONSOLE: El mensaje se muestra únicamente en pantalla.
                 NO se escribe en fichero NI se captura en el DataFrame.
                 Úsalo para separadores visuales o banners que solo
                 tienen sentido en la salida de consola.
        FILE:    El mensaje se escribe en fichero y se captura en el
                 DataFrame. No aparece en pantalla.
        BOTH:    El mensaje va a pantalla, fichero y DataFrame
                 (comportamiento por defecto).

    Uso:
        logger.info("Solo pantalla",  dest=Dest.CONSOLE)
        logger.ok("Solo fichero",     dest=Dest.FILE)
        logger.warning("En ambos",    dest=Dest.BOTH)
    """
    CONSOLE = "console"
    FILE    = "file"
    BOTH    = "both"

# Proceso actual para métricas de sistema
# _process = psutil.Process(os.getpid())

def _get_system_metrics() -> tuple[float, float]:
    """
    Obtiene el consumo actual de CPU y RAM de forma global.

    Returns:
        Tupla (cpu_percent, ram_percent) como float con 4 decimales.
    """
    cpu = round( psutil.cpu_percent( interval= 0.05 ) / 100 , 4 )
    ram = round( psutil.virtual_memory().percent/100 , 4 )
    # process_ram = round( _process.memory_percent()/100 , 4 )

    return cpu, ram

def _is_tqdm_active() -> bool:
    """
    Detecta si hay alguna barra de progreso tqdm activa en este momento.
    """
    try:
        return bool(tqdm_module.tqdm._instances) # type: ignore
    except AttributeError:
        return False

def _init_execution_context() -> None:
    """
    Inicializa el contexto de ejecución una única vez por proceso.

    Genera el UUID v4 de la ejecución y obtiene el usuario del SO.
    Es idempotente: llamadas sucesivas no regeneran el UUID.
    """
    global _execution_id, _execution_user, _capture_active, _log_records

    if _capture_active:
        return

    _execution_id   = str(uuid.uuid4())
    _execution_user = getpass.getuser()
    _capture_active = True
    _log_records    = []

def _print_execution_banner() -> None:
    """
    Imprime en pantalla el banner de inicio de ejecución.

    Solo aparece en consola vía print(), nunca en el fichero .log
    ni en el DataFrame, ya que es contenido puramente visual.
    """
    sep = "═" * 99
    print("\n" + "\n".join([
        sep,
        f"  Proyecto    : {_PROJECT_NAME}",
        f"  IdEjecucion : {_execution_id}",
        f"  Usuario     : {_execution_user}",
    ]) + "\n")

# Formatter personalizado
class _RichFormatter(logging.Formatter):
    """
    Formatter que enriquece cada línea de log con código HTTP,
    métricas de CPU y RAM del proceso.

    IMPORTANTE: La captura al DataFrame NO ocurre aquí. El formatter
    se ejecuta una vez por handler (consola + fichero = 2 veces), lo
    que causaría duplicados. La captura se realiza en _log_with_dest(),
    que se ejecuta exactamente una vez por mensaje.
    """

    def format(self, record: logging.LogRecord) -> str:
        http_code, http_text = _HTTP_STATUS.get(record.levelno, _HTTP_STATUS_DEFAULT)
        cpu, ram             = _get_system_metrics()
        module_name          = record.name.replace(f"{_PROJECT_NAME}.", "", 1)
        level_name           = record.levelname.ljust(7)
        timestamp_str        = self.formatTime(record, _DATE_FORMAT)
        message              = record.getMessage()

        return (
            f"{timestamp_str} | "
            f"{level_name} | "
            f"{http_code} | "
            f"{http_text}| "
            f"CPU: {cpu*100:>5.2f}% | "
            f"RAM: {ram*100:>5.2f}% | "
            f"{module_name} | "
            f"{message}"
        )

# Handlers con filtro de destino
class _DestFilter(logging.Filter):
    """
    Filtro que permite o bloquea un registro según el destino solicitado.

    Cada handler lleva un filtro propio. El campo ``dest`` se inyecta
    en el LogRecord desde _ProjectLogger._log_with_dest().
    """

    def __init__(self, allowed_dest: Dest) -> None:
        super().__init__()
        self._allowed = allowed_dest

    def filter(self, record: logging.LogRecord) -> bool:
        dest: Dest = getattr(record, "dest", Dest.BOTH)
        return dest in (Dest.BOTH, self._allowed)


# Handler de consola compatible con tqdm
class _TqdmConsoleHandler(logging.StreamHandler):
    """
    Handler de consola que usa tqdm.write() cuando hay una barra activa.
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            if _is_tqdm_active():
                tqdm_module.tqdm.write(msg)
            else:
                self.stream.write(msg + self.terminator)
                self.flush()
        except Exception:
            self.handleError(record)

# Logger enriquecido
class _ProjectLogger(logging.Logger):
    """
    Subclase de logging.Logger que añade:

        1. El método ``ok()`` para el nivel personalizado OK (25).
        2. El parámetro ``dest`` en todos los métodos de log.
        3. La captura al DataFrame en _log_with_dest(), ejecutada
           exactamente UNA VEZ por mensaje antes de que actúen
           los handlers, eliminando cualquier posibilidad de duplicados.

    No se instancia directamente: se obtiene a través de get_logger().
    """

    def _log_with_dest(
        self,
        level:  int,
        msg:    str,
        args:   tuple[Any, ...],
        dest:   Dest,
        kwargs: dict[str, Any],
    ) -> None:
        """
        Punto central de captura y enrutado de cada mensaje de log.

        Se ejecuta exactamente UNA VEZ por mensaje, independientemente
        de cuántos handlers estén configurados o del destino elegido.
        Esto garantiza que el DataFrame nunca contenga duplicados.

        La captura solo se realiza para dest != Dest.CONSOLE, ya que
        CONSOLE indica contenido puramente visual (separadores, banners)
        sin valor analítico para la tabla SQL.

        Args:
            level:  Nivel numérico del log.
            msg:    Mensaje (con placeholders % si se usan args).
            args:   Argumentos para el formateo del mensaje.
            dest:   Destino de salida.
            kwargs: Kwargs restantes para logging.Logger._log().
        """
        if not self.isEnabledFor(level):
            return

        # ── Captura al DataFrame (una sola vez por mensaje) ───────────────────
        if _capture_active and dest != Dest.CONSOLE and level != logging.DEBUG:
            http_code, _ = _HTTP_STATUS.get(level, _HTTP_STATUS_DEFAULT)
            cpu, ram     = _get_system_metrics()
            module_name  = self.name.replace(f"{_PROJECT_NAME}.", "", 1)

            try:
                message = msg % args if args else str(msg)
            except (TypeError, ValueError):
                message = str(msg)

            _log_records.append({
                "Id_Ejecucion":      _execution_id,
                "Usuario_Ejecucion": _execution_user,
                "Nombre_Proyecto":   _PROJECT_NAME,
                "Timestamp":         datetime.now(),
                "Nivel":             logging.getLevelName(level),
                "Codigo_HTTP":       http_code,
                "Modulo":            module_name,
                "Mensaje":           message,
                "CPU_Porcentaje":    cpu,
                "RAM_Porcentaje":    ram,
            })

        # Enrutado al sistema de logging de Python
        extra = kwargs.pop("extra", {})
        extra["dest"] = dest
        self._log(level, msg, args, extra=extra, **kwargs)

    def debug(self, msg: str, *args: Any, dest: Dest = Dest.BOTH, **kwargs: Any) -> None:
        """
        Registra un mensaje de nivel DEBUG (102 Processing).
        Solo aparece en fichero, no en consola (nivel mínimo INFO).
        """
        self._log_with_dest(logging.DEBUG, msg, args, dest, kwargs)

    def info(self, msg: str, *args: Any, dest: Dest = Dest.BOTH, **kwargs: Any) -> None:
        """Registra un mensaje de nivel INFO (200 OK)."""
        self._log_with_dest(logging.INFO, msg, args, dest, kwargs)

    def ok(self, msg: str, *args: Any, dest: Dest = Dest.BOTH, **kwargs: Any) -> None:
        """
        Registra un mensaje de nivel OK (201 Created).

        Úsalo para confirmar que una operación relevante ha completado
        con éxito: cargas a SQL, SPs, exportaciones, conexiones verificadas.

        Example:
            >>> logger.ok("Carga completada: %d filas en raw.work_items", 342)
        """
        self._log_with_dest(_OK_LEVEL, msg, args, dest, kwargs)

    def warning(self, msg: str, *args: Any, dest: Dest = Dest.BOTH, **kwargs: Any) -> None:
        """Registra un mensaje de nivel WARNING (400 Bad Request)."""
        self._log_with_dest(logging.WARNING, msg, args, dest, kwargs)

    def error(self, msg: str, *args: Any, dest: Dest = Dest.BOTH, **kwargs: Any) -> None:
        """Registra un mensaje de nivel ERROR (500 Internal Server Error)."""
        self._log_with_dest(logging.ERROR, msg, args, dest, kwargs)

# Configuración del logger raíz
def _setup_root_logger() -> None:
    """
    Configura el logger raíz del proyecto una única vez (idempotente).
    """
    os.makedirs(_LOG_DIR, exist_ok=True)

    logging.setLoggerClass(_ProjectLogger)

    root_logger = logging.getLogger(_PROJECT_NAME)

    if root_logger.handlers:
        return

    root_logger.setLevel(logging.DEBUG)

    formatter = _RichFormatter()

    console_handler = _TqdmConsoleHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(_DestFilter(Dest.CONSOLE))

    file_handler = RotatingFileHandler(
        _LOG_FILE,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    file_handler.addFilter(_DestFilter(Dest.FILE))

    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    root_logger.propagate = False

# Interfaz pública
def get_logger(name: str, capture_to_df: bool = False) -> _ProjectLogger:
    """
    Devuelve un logger hijo del logger raíz del proyecto.

    Es el único punto de entrada que deben usar los módulos del proyecto.

    Cuando capture_to_df=True, activa la captura de mensajes en un
    DataFrame e imprime el banner de inicio. Esta decisión es global:
    todos los loggers del proceso capturan sus mensajes a partir de
    ese momento, aunque no pasen capture_to_df=True.

    Se recomienda pasar capture_to_df=True únicamente en main.py.

    Args:
        name:          Nombre del módulo. Usar siempre __name__.
        capture_to_df: Activa captura a DataFrame y banner de inicio.

    Returns:
        _ProjectLogger con debug(), info(), ok(), warning(), error()
        y el parámetro dest disponibles.

    Raises:
        TypeError: Si name no es un string no vacío.
    """
    if not isinstance(name, str) or not name:
        raise TypeError(
            "El parámetro 'name' debe ser un string no vacío. "
            "Usa siempre get_logger(__name__)."
        )

    _setup_root_logger()

    if capture_to_df:
        already_active = _capture_active
        _init_execution_context()
        if not already_active:
            _print_execution_banner()

    logger = logging.getLogger(f"{_PROJECT_NAME}.{name}")

    if not isinstance(logger, _ProjectLogger):
        logger.__class__ = _ProjectLogger

    return logger  # type: ignore[return-value]

def get_log_dataframe():
    """
    Construye y devuelve el DataFrame con todos los mensajes capturados.

    Llámalo al final del proceso, antes de volcar los datos a SQL.

    Returns:
        pandas.DataFrame con las columnas de _DF_COLUMNS y tipos
        correctos para SQL Server. DataFrame vacío si no hay registros.

    Raises:
        ImportError: Si pandas no está instalado.
    """

    if not _log_records:
        return pd.DataFrame(columns=_DF_COLUMNS)

    df = pd.DataFrame(_log_records, columns=_DF_COLUMNS)
    df["Timestamp"]      = pd.to_datetime(df["Timestamp"])
    df["Codigo_HTTP"]    = df["Codigo_HTTP"].astype("int64")
    df["CPU_Porcentaje"] = df["CPU_Porcentaje"].astype("float64")
    df["RAM_Porcentaje"] = df["RAM_Porcentaje"].astype("float64")

    return df

def get_execution_id() -> str:
    """Devuelve el UUID v4 de la ejecución actual, o '' si no está activo."""
    return _execution_id

def get_execution_user() -> str:
    """Devuelve el usuario del SO de la ejecución actual, o '' si no está activo."""
    return _execution_user

# ── Exportaciones públicas ────────────────────────────────────────────────────
__all__ = [
    "get_logger",
    "get_log_dataframe",
    "get_execution_id",
    "get_execution_user",
    "Dest",
]
