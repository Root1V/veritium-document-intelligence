# ADR-0009 · Embeddings y rerank directos a prometheus

**Estado:** aceptada · 2026-10-24

## Contexto
La búsqueda híbrida (VRT-59) necesita un modelo de embeddings y, opcionalmente, un reranker. prometheus los sirve y axonium (el SDK obligatorio para llegar a él) ya los expone. Por la regla de ADR-0006, en producción el tráfico de modelos va gobernado por aeon-modelgw, pero aeon-modelgw no expone `/v1/embeddings`. Su propio almacén RAG llama a prometheus directo y rechaza buscar con un modelo distinto del que indexó (`ErrEmbeddingModelMismatch`).

## Decisión
- **Embeddings y rerank van directo a prometheus**, por axonium y con la credencial de Veritium. No pasan por aeon-modelgw, ni siquiera en producción.
- **El modelo de embeddings se fija por id** (`SEARCH_EMBEDDING_MODEL`) y queda guardado en cada fragmento. Una búsqueda solo compara vectores de su mismo modelo, y cambiar de modelo obliga a re-indexar.
- **Ambos modelos son opcionales para buscar.** Sin ellos (sin permiso, caídos o sin configurar), la búsqueda sigue por palabras y por escritura parecida.

## Por qué no por aeon
- **Un perfil puede cambiar de modelo**, por respaldo o por política, y aeon está hecho para eso. Para embeddings, ese cambio es un error silencioso: vectores de otro modelo comparan y devuelven resultados con aparente seguridad, pero sin sentido.
- **Indexar no es la ejecución de un agente.** No hay run ni manifiesto al que cargarle presupuesto: es mantenimiento de un índice.
- **prometheus ya controla lo que importa aquí:** scopes `model:<id>`, límites por cliente y gasto por credencial.

## Consecuencias
- ADR-0006 sigue rigiendo para los modelos de conversación (extracción, clasificación, reglas). Esta es su única excepción, y es deliberada.
- El costo de los embeddings no aparece en el ledger de aeon por expediente: se ve por credencial en prometheus.
- Si la búsqueda necesitara alguna vez presupuesto por expediente, se pediría a aeon como capacidad genérica (`/v1/embeddings` gobernado con modelo fijado), no como ruta de chat.
