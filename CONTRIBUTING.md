# Guía de contribución — Azure Boards Manager

Gracias por tu interés en contribuir al proyecto. Esta guía explica cómo está organizado el repositorio y cómo trabajar con él de forma segura.

---

## Estructura de ramas

El repositorio utiliza un modelo de ramas sencillo con dos niveles:

```
main        ← Código estable. Lo que los usuarios finales instalan.
│
└── dev     ← Rama de desarrollo activo. Aquí se integran los cambios.
    │
    ├── feature/nombre-funcionalidad   ← Una rama por cada nueva funcionalidad
    ├── fix/nombre-del-error           ← Una rama por cada corrección de error
    └── docs/nombre-del-cambio         ← Una rama para cambios de documentación
```

### Reglas de cada rama

| Rama | Propósito | ¿Quién puede hacer push directo? |
|---|---|---|
| `main` | Versiones estables y probadas | Nadie. Solo acepta Pull Requests desde `dev` |
| `dev` | Integración de cambios en curso | El equipo de desarrollo |
| `feature/*` | Desarrollo de una nueva funcionalidad | El autor de la funcionalidad |
| `fix/*` | Corrección de un error concreto | El autor de la corrección |
| `docs/*` | Mejoras de documentación | Cualquier colaborador |

---

## Cómo contribuir paso a paso

### 1. Clona el repositorio y posiciónate en `dev`

```bash
git clone https://github.com/tu-usuario/azure-boards-manager.git
cd azure-boards-manager
git checkout dev
```

### 2. Crea una rama para tu cambio

```bash
# Para una nueva funcionalidad
git checkout -b feature/nombre-descriptivo

# Para corregir un error
git checkout -b fix/descripcion-del-error

# Para documentación
git checkout -b docs/seccion-a-mejorar
```

### 3. Trabaja en tu rama y haz commits descriptivos

Usa mensajes de commit claros en español o inglés:

```bash
git add .
git commit -m "feat: añadir soporte para campos personalizados de tipo fecha"
git commit -m "fix: corregir error al parsear IDs con espacios en AZURE_ROOT_IDS"
git commit -m "docs: actualizar guía de instalación con pasos para uv"
```

**Prefijos recomendados para los commits:**

| Prefijo | Cuándo usarlo |
|---|---|
| `feat:` | Nueva funcionalidad |
| `fix:` | Corrección de error |
| `docs:` | Solo documentación |
| `refactor:` | Reorganización de código sin cambiar comportamiento |
| `test:` | Añadir o modificar tests |
| `chore:` | Tareas de mantenimiento (dependencias, configuración) |

### 4. Abre un Pull Request hacia `dev`

Una vez terminado tu cambio, abre un Pull Request en GitHub desde tu rama hacia `dev`. Describe brevemente qué cambia y por qué.

### 5. El mantenedor integrará `dev` en `main`

Cuando `dev` tenga suficientes cambios estables y probados, el mantenedor del proyecto creará un Pull Request de `dev` → `main` y creará una nueva release.

---

## Qué NO incluir en un commit

- El fichero `.env` con credenciales reales
- La carpeta `.venv/` del entorno virtual
- Ficheros de log (`.log`)
- Ficheros JSON de la carpeta `output/`
- Contraseñas, tokens o claves de cifrado de ningún tipo

Todo lo anterior ya está en el `.gitignore` y Git los ignora automáticamente. Aun así, revisa siempre con `git status` antes de hacer un commit.

---

## Reportar un error o sugerir una mejora

Usa la sección [Issues](../../issues) de GitHub. Antes de abrir uno nuevo, comprueba que no existe ya un issue similar abierto.

Al abrir un issue, incluye:
- Qué esperabas que ocurriera
- Qué ocurrió realmente
- El mensaje de error completo (puedes encontrarlo en el fichero `.log`)
- Tu versión de Python (`python --version`) y sistema operativo
