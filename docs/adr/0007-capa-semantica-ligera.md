# ADR-0007 · Capa semántica ligera (ontología) como base del modelo

**Estado:** aceptada · 2026-10-07

## Contexto
Para reutilizar entre procesos, validar entre documentos y dar un contrato estable, hace falta un significado compartido. En 2026, "capa semántica" abarca desde métricas de BI (OSI, hoy Apache Ossie) hasta ontologías formales (FIBO, OWL) y knowledge graphs. Gran parte de lo que se publica es material de proveedores, con beneficios argumentados más que medidos.

## Decisión
- Una **ontología ligera** propia, versionada como catálogo completo (`semantic_catalog_versions`), con:
  - **entidades** (`persona`, `empleador`, `credito`, `ingreso`…);
  - **atributos** (definición, tipo, formato, unidad, cardinalidad, **clase PII**);
  - **roles** (titular, cónyuge, aval, asesor…);
  - **mapeos** campo de documento → atributo + rol.
- Cada versión de perfil **fija** una versión del catálogo, y eso da la reproducibilidad.
- Habilita:
  - la vista consolidada por expediente (resolución de entidades con estados `consistent` / `conflict` / `single_source`);
  - requisitos por atributo con documentos alternativos;
  - reglas sobre atributos;
  - el contrato estable `entities` (ADR-0005);
  - enmascaramiento de PII derivado.
- **No se adoptan** FIBO completo, triple store ni Apache Ossie. FIBO se usa solo como referencia de nombres; Ossie es para métricas de BI.

## Consecuencias
- El núcleo entra en F1 (VRT-23); la UI y las reglas sobre atributos llegan en F2.
- El valor se **mide** en F4 (exactitud por campo con y sin definiciones semánticas, reutilización de reglas entre perfiles).
