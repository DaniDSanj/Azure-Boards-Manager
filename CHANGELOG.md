# Changelog

Todos los cambios relevantes de este proyecto quedan documentados en este fichero.

El formato sigue el estándar [Keep a Changelog](https://keepachangelog.com/es/1.0.0/) y el versionado sigue [Semantic Versioning](https://semver.org/lang/es/).

---

## [v1.0.0-rc.1] — 2026-03-15

### Primera versión estable (Pre-release v1)

#### Añadido
- **`install.bat`** — Instalador automático idempotente para Windows. Instala `uv`, Python 3.14, valida el fichero `.env` y crea el entorno virtual con todas las dependencias. No requiere conocimientos técnicos.
- **`exec.bat`** — Lanzador del proceso principal con comprobaciones previas, salida en tiempo real, marcas de tiempo y orientación en caso de error.
- **`CONTRIBUTING.md`** — Guía de contribución con modelo de ramas (`main` / `develop` / `feature` / `fix` / `docs`) y convención de commits.
- **`.env.example`** — Plantilla de configuración con instrucciones en lenguaje llano para usuarios no técnicos.
- **`.github/workflows/ci.yml`** — Workflow de integración continua con GitHub Actions sobre `windows-latest`, usando `uv` para validar sintaxis e imports en cada push o Pull Request a `main` y `develop`.
- **Módulo `pipeline`** — Extracción de work items desde Azure DevOps Boards por jerarquía, con soporte para campos personalizados y exportación a JSON.
- **Módulo `sql`** — Conexión a SQL Server con detección automática de Windows Authentication, carga de DataFrames y ejecución de procedimientos almacenados.
- **Módulo `credentials`** — Gestión segura de credenciales mediante Windows Credential Manager con cifrado Fernet y derivación PBKDF2.
- **Módulo `utils`** — Configuración centralizada (`config.py`), sistema de logging con captura a DataFrame (`logger.py`) y funciones auxiliares de formateo (`formatters.py`).
- **Documentación completa** de todos los módulos en sus respectivos `README.md`.

---

*Para versiones futuras, consulta la sección [Releases](../../releases) del repositorio.*
