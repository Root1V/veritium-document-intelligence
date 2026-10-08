# ADR-0008 · Tipos documentales como datos versionados

**Estado:** aceptada · 2026-10-08

## Contexto
Hasta v0.3.0, cada tipo documental se definía en código: un valor de enum, un esquema Pydantic, un extractor, una descripción para el clasificador y una pista para el agente. Crear o ajustar un tipo requería un desarrollador y un despliegue. Además, los 12 extractores eran idénticos: lo que cambiaba entre tipos siempre era dato (campos, descripciones, pistas), nunca lógica.

## Decisión
- **Un tipo es su definición**, versionada en `document_type_versions` (`draft → published → retired`, inmutable al publicarse). Incluye nombre visible, descripción (la lee el clasificador), pista de extracción y esquema.
- **El esquema es dato acotado:** campos `str | int | float | bool | enum`, cada uno envuelto en `Extracted[T]` (o simple si no se ancla al documento), más listas de sub-objetos con un solo nivel. Se **compila a un modelo Pydantic** al usarlo, porque la extracción, el anclaje y la revisión trabajan con instancias reales.
- **Un solo extractor agéntico** para todos los tipos del catálogo. `generic` queda en código, porque es una estrategia (una llamada, siempre a revisión), no un esquema.
- **Cada extracción registra la versión** que la produjo, y al reevaluar se relee con esa misma versión.
- **Publicar verifica las referencias:** un esquema nuevo no puede quitar campos que lee el catálogo semántico publicado.
- **La v1 se deriva de los esquemas de código.** Un test exige que produzca el mismo JSON Schema, así el comportamiento no cambia en la migración.

## Consecuencias
- Un tipo nuevo, o un cambio de esquema, es una operación de datos (VRT-33/34 le darán UI). El clasificador y el agente lo usan desde la siguiente corrida.
- Las reglas codificadas siguen nombrando tipos y campos. Las de formato pasan a validadores por atributo (VRT-35); las demás dejan de ser necesarias a medida que existan reglas sobre atributos (VRT-36).
- Los esquemas en `domain/schemas` quedan como origen del seed y como apoyo de tests; editarlos no cambia una base ya sembrada.
