# Eficiencia de los modelos de IA: lo que medimos y aprendimos

Octubre de 2026 · VRT-68, VRT-69, VRT-70 · canal: `PRM-VRT-001`, `VRT-PRM-005/006`, `PRM-VRT-002/003`

## La pregunta

¿Dónde se va el tiempo de un expediente y qué modelos conviene correr dentro de Veritium y cuáles servir aparte? La respuesta corta: casi todo el tiempo lo consumían dos cosas, **el agente de extracción y el OCR**, y en ambos casos el problema no era el que suponíamos.

## Dónde estaba el costo (antes)

| Etapa | Modelo | Dónde corre | Costo medido |
|---|---|---|---|
| Lectura | PaddleOCR (detección, reconocimiento, orientación) + layout | Veritium, CPU | 13,9 s por página A4 |
| Clasificación | gpt-oss-20b | prometheus | ~1 s |
| **Extracción** | gpt-oss-20b, y qwen3vl en tablas y figuras | prometheus | **84–2.079 s por documento** |
| Validación | reglas; gpt-oss solo para nombres dudosos | Veritium | casi nada |
| Decisión | ninguno, a propósito | Veritium | — |

Los modelos generativos (decenas de GB, GPU) se sirven aparte, como ya estaba. Los tradicionales del OCR resultaron baratos **con el runtime correcto** (ver VRT-70).

## Cómo medimos

- **Documentos reales, no sintéticos:** 4 documentos y 9 páginas (boleta, solicitud de préstamo, carnet de extranjería, carta de autorización).
- **Valores correctos verificados a mano en las imágenes:** 42 campos. La salida de una corrida anterior **no** sirve de referencia: la línea base también se equivocaba. Por ejemplo, mezclaba los reversos de dos personas en el carnet. Los valores correctos viven fuera del repo porque tienen datos personales.
- **Varias corridas por variante, intercaladas:** de una corrida a otra, con la misma configuración, la exactitud varía hasta 15 puntos. Una corrida sola no decide nada.
- **Tokens por turno, no solo segundos:** el tiempo depende de la carga de prometheus, que es compartido. Los tokens y la exactitud no.
- **Sin la caché de idempotencia:** el gateway devuelve la respuesta guardada si la petición es idéntica, así que repetir un documento puede medir 0 s.

**Para repetirlo:** los scripts están en `scripts/`. Los datos (lista de documentos y valores verificados) viven fuera del repo, en `~/.veritium/bench/`; el formato está en la ayuda de `bench_score.py`.

```bash
uv run python scripts/bench_extraction.py antes1          # una corrida; repetir e intercalar variantes
uv run python scripts/bench_score.py --group antes=antes* --group ahora=ahora*
uv run python scripts/bench_ocr.py paddleocr rapidocr     # lectores de OCR: tiempo y coincidencia de líneas
```

## VRT-69 · El agente de extracción

**Lo que suponíamos:** que el costo era lo que se le envía, porque reenvía el documento en cada turno.

**Lo que medimos:** la entrada es chica (≤13k tokens) y ~95% sale de caché. **El costo es lo que el modelo escribe.** Y la mayor pérdida eran turnos en que gpt-oss, a temperatura 0, entra en un bucle («The numeric might be region 337?…») hasta el tope de 8.192 tokens. La peor corrida tuvo 10 turnos así: 2.079 s.

| Variante (3 corridas c/u) | Exactitud | Tiempo medio | Tokens de salida |
|---|---|---|---|
| Antes | 65% | 1.073 s | 62,7k |
| Razonamiento «low» | 74% (1 corrida) | −86% | — |
| Temperatura 1.0 en todo | 69% (1 corrida) | sin bucles | — |
| **Elegida: reintento del turno cortado + esquema liviano + lista de regiones depurada** | **84%** | **665 s** | **30,1k** |

- **Reintento:** si un turno termina por tope, se repite una vez con temperatura 0.6. El resto sigue a temperatura 0, que es la más exacta.
- **Esquema liviano:** el agente escribe valor, confianza, texto y región. La página y la caja las pone Veritium a partir de la región.
- **Lista depurada:** sin regiones vacías y con «…» en los textos recortados, para que no relea lo que ya tiene.

## VRT-70 · El OCR

**La pista vino de prometheus** (`PRM-VRT-002`): antes de construir un servicio, preguntaron cómo lo teníamos montado. Estábamos en el runtime más lento para Mac.

| Variante (9 páginas) | s/página | Líneas iguales a Paddle | Exactitud de la extracción |
|---|---|---|---|
| PaddlePaddle (antes) | 13,9 | — | 84% |
| Paddle, detector `mobile` | 7,3 | — | pierde valores |
| ONNX Runtime con CoreML | 4,5 | — | — |
| ONNX Runtime con modelos y valores por defecto de RapidOCR | 1,1 | 354/507 | **69–71%** |
| **Elegida: ONNX Runtime con nuestra conversión de los modelos de Paddle y su configuración** | **1,1** | **470/507** | **82%** |

**La trampa:** «los mismos modelos en ONNX» no eran los mismos.
- Los archivos publicados por RapidOCR leen distinto que los de Paddle, aun sobre recortes idénticos.
- RapidOCR detecta con otra normalización, otros umbrales y dilatación.

Las coordenadas coincidían (1 px) y una métrica gruesa («¿aparecen los valores clave en el texto?») daba 35/37. Solo la exactitud de la extracción de punta a punta mostró la caída de 14 puntos. Con nuestra conversión (`scripts/export_ocr_onnx.sh`) y los parámetros de Paddle, la lectura queda equivalente. La memoria baja de picos de 17–21 GB a ~6 GB; lo que queda es el layout, que sigue en Paddle.

## Lo que aprendimos

1. **Medir antes de optimizar, y desconfiar de la premisa.** Las dos hipótesis de partida —recortar lo que se envía al agente, y que el OCR necesitaba GPU— eran falsas.
2. **La referencia son valores verificados, no la versión anterior.** Comparar contra la línea base hubiera premiado repetir sus errores.
3. **Una corrida no es una medición.** El agente varía mucho entre corridas; sin repetir, habríamos adoptado y descartado variantes al azar.
4. **Medir punta a punta.** Una métrica intermedia (coordenadas, valores clave) puede verse bien mientras el resultado final empeora.
5. **Los valores por defecto de una librería no son los del modelo original.** Antes de comparar runtimes, igualar pesos y pre y postprocesamiento.
6. **Los modelos de razonamiento a temperatura 0 entran en bucle.** Cortar el turno y reintentar con otra temperatura recupera la exactitud sin pagar la variabilidad de subir la temperatura en todo.
7. **Lo compartido distorsiona.** Otros modelos cargados en prometheus bajaron la generación a un tercio y provocaron timeouts. La caché de idempotencia devolvía respuestas viejas, tanto al medir como al asistente.
8. **Preguntar a otro equipo antes de construir** ahorró una migración que no aceleraba nada (OCR en prometheus sin GPU).

## Pendiente

- **Cortar el bucle apenas empieza**, con streaming, y no al llegar al tope: cada bucle aún cuesta ~80 s.
- **Devolver el razonamiento al modelo entre turnos** (`PRM-VRT-003`): synaptum lo omite hoy. Upstream mide 7/120 turnos fallidos sin él y 0/120 con él; puede explicar también los bucles. Lo mediremos con el mismo banco cuando SYN lo publique.
- **El layout sigue en Paddle** (0,6 s por página, la mayor parte de la memoria). Servir el OCR desde prometheus (`VRT-PRM-006`) queda en espera: ya no hay latencia que ganar, solo la copia por proceso.
- **Errores que ninguna variante resuelve:** montos manuscritos («132 500») y el carnet que mezcla los datos de dos personas.
