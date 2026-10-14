# SPEC — Limpiar los 28 hallazgos de ruff en `app/` y `tests/`

(Sustituye al SPEC.md de la tarea anterior, que sigue en el historial de git.) Delegado con `/delegar`; Claude es el checker.

## Problema
`ruff check app tests` (ruff 0.17.0, reglas por defecto, sin archivo de configuración) devuelve 28 hallazgos que ya estaban en `main`:
UP006 ×7, UP045 ×2, UP035 ×1, BLE001 ×1 en `app/core/safety.py`; ISC004 ×5 y PLE2515 ×1 en `tests/test_safety_adversarial.py`;
I001 en 9 archivos (app y tests), F401 ×1 en `tests/test_safety.py`, SIM117 ×1 en `app/core/db.py`.

## Alcance
- Dejar `ruff check app tests` en 0 hallazgos corrigiendo el código, sin cambiar comportamiento.
- `ruff check --fix` sirve para lo mecánico (I001, UP006/UP035/UP045, F401, SIM117). Revisa cada cambio.
- Solo `app/` y `tests/`. Ya existen otros hallazgos en `scripts/`: fuera de alcance.

## Reglas duras (la prueba de aceptación las verifica)
- **Prohibido debilitar el lint:** no crear `ruff.toml`/`.ruff.toml`, no añadir `[tool.ruff]` a ningún `pyproject.toml`, no usar `# ruff: noqa`, `per-file-ignores` ni `--ignore`/`--extend-ignore` en ningún comando.
- **Único `# noqa` permitido:** `# noqa: BLE001` en la línea `except Exception:` de `is_safe_select` (`app/core/safety.py`), con un comentario que explique por qué: es un cortafuegos que debe fallar cerrado (devolver `False`) ante cualquier error del parser. No estrechar esa excepción: cambiaría la seguridad. Ningún otro `noqa` en `app/` ni `tests/`.
- **Los payloads adversariales no cambian de valor.** En `tests/test_safety_adversarial.py`: el espacio de ancho cero se escribe como `"​"` (mismo carácter, ahora visible); las concatenaciones implícitas de `MUST_ACCEPT` se envuelven en paréntesis (mismo string). No toques los homoglifos (`ｐｇ_shadow`, `pg_shаdow` con "а" cirílica) ni ningún otro string. La prueba compara un hash del valor de las constantes del módulo.

## Fuera de alcance
- Cambiar la lógica de `safety.py`, `db.py` o cualquier otra cosa que no sea estilo.
- Renombrar, añadir, borrar o saltarse tests existentes (el conteo de tests existentes no cambia); solo se permiten cambios de estilo en ellos.
- `scripts/`, `NOTES.md`, `.env.example`, la configuración de ruff.

## Criterios de aceptación
Tests de aceptación en `tests/test_estilo_ruff.py` (no se modifican):
1. `python -m ruff check app tests` termina con código 0.
2. No existe configuración de ruff en el repo (`ruff.toml`, `.ruff.toml`, sección `[tool.ruff*]` en `pyproject.toml`).
3. En `app/` y `tests/` no hay `# ruff: noqa` ni más `noqa` que el de BLE001 en `app/core/safety.py` descrito arriba (con motivo escrito).
4. Los valores de las constantes de payloads de `tests/test_safety_adversarial.py` son idénticos a los de antes (hash `637a9963…`).
5. Sin regresiones: la suite completa sigue pasando (los 364 tests previos más los de esta prueba) y `compileall` limpio.

## Comandos
- Build: `/home/santiago/orca/workspaces/text-to-sql-rag/venv-shared/bin/python -m compileall -q app tests`
- Lint: `/home/santiago/orca/workspaces/text-to-sql-rag/venv-shared/bin/ruff check app tests`
- Tests: `/home/santiago/orca/workspaces/text-to-sql-rag/venv-shared/bin/pytest -q tests`
