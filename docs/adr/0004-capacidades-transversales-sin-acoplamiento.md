# ADR-0004 · Las capacidades del ecosistema son transversales: cero acoplamiento

**Estado:** aceptada · 2026-10-07

## Contexto
Veritium se construye sobre el ecosistema del autor: **aeon** (ejecución durable y gobierno), **synaptum** (framework de agentes), **axonium** (SDK de inferencia, obligatorio hacia prometheus), **prometheus** (inferencia local) y **argus** (observabilidad). Cada uno sirve a **varios proyectos**, y sus equipos aceptan ajustes puntuales.

## Decisión
1. **Nada de Veritium vive en esos repos:** ni código, ni nombres, ni semántica de documentos. Veritium se integra solo por sus contratos públicos y versionados.
2. **Toda solicitud de ajuste es una capacidad genérica,** formulada en el vocabulario del destinatario, con un criterio de aceptación que el equipo dueño puede verificar sin Veritium.
3. **Cada capacidad se consume detrás de un puerto propio** (hexagonal): `CaseExecutionPort` → aeon · `InferencePort` → axonium / modelgw · `AgentRuntime` → synaptum · `Telemetry` → argus.
4. **La incorporación es por configuración estándar:** caller y manifiesto en aeon, credenciales `client_credentials` en prometheus, registro de app en argus.
5. **La coordinación es por el canal compartido** (`canal.md` + `solicitudes/`), con IDs `<EMISOR>-<DESTINO>-<NNN>`. El repo solo referencia esos IDs.

## Consecuencias
- Hay que escribir y mantener adaptadores, pero cada pieza se puede versionar o reemplazar sin tocar el dominio.
- Las dependencias de calendario con otros equipos se hacen visibles en el roadmap (`blocked`).
