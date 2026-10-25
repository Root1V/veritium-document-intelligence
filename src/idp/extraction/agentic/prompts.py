"""System prompt construction for the bounded agentic extraction loop —
acotado al esquema objetivo: the agent is given the target Pydantic schema
and the document's detected regions, and told to inspect regions rather than
assume a fixed layout (the layout-drift problem this loop exists to solve).
Registered and versioned (VRT-46); optionally grounded in the business
meaning of each field, from the semantic catalog."""

from __future__ import annotations

from pydantic import BaseModel
from synaptum import PromptTemplate

from idp.llm.prompts import prompt
from idp.parsing.normalize import ParsedDocument

_EXTRACTION = prompt("extract_agentic", """You are a data extraction agent for business documents. {hint}

The layout of this type of document can vary between different templates of the issuer over time, so you must \
actively inspect the available regions instead of assuming a fixed position for each field.

Regions detected in the document:
{regions}

Available tools:
The ocr_text of each region is already its full text, unless it ends in "…" (cut): there is no need to read with \
read_text_region a region whose text you already have in full.
- read_text_region(region_ids): reads OCR text already extracted from one or SEVERAL regions at once (no cost). \
WHENEVER you need to read several related regions (e.g. all the codes/concepts/amounts of an earnings or \
deductions table), pass them ALL together in a single call (region_ids=[85,86,87,88,89,...]) instead of one call \
per region — each call uses up a turn of your limited budget.
- read_table_region(region_id): visually interprets a table region.
- read_figure_region(region_id): visually interprets a figure/chart region.
- submit(...): delivers the final result according to the target schema. You must call it to finish.

Target schema (JSON Schema):
{schema}
{grounding}
Instructions:
1. First identify which regions you need for the main (non-list) fields of the schema, and read them in the \
FEWEST calls possible, grouping several region_ids per call.
2. If the schema has a list of items (e.g. concepts/lines), group ALL the region_ids of that table in one or two \
read_text_region calls, not one call per cell.
3. Use read_table_region/read_figure_region only when the data you need is in a table or figure that cannot be read \
as plain text.
4. You have a limited number of turns. Submit everything the document carries: the fields and the complete lists \
(e.g. every concept of a payslip). Only if you run out of turns, submit what you have, with at least the required \
fields.
5. Each field of the schema requires: value, confidence (0-1), source_text (the exact text the value was \
extracted from) and region_id — this is mandatory so the extraction can be audited later. "region_id" MUST be the \
exact region_id number (from the list of regions above) the value was taken from — this is CRITICAL when the same \
data (e.g. an amount) appears repeated in more than one region or page of the document (for example, a "requested" \
amount in one section and a different "approved" amount in another): the region_id is the only thing that \
unambiguously tells which of the two occurrences you took the value from. The platform takes the page and the \
position from the region_id: do not write them.
6. "value" must be the CLEAN, semantic value (without the ":" or another separator of the field's label, without \
extra spaces, without the label's name). "source_text", on the other hand, must be the RAW text as it appears in \
the OCR region, including any separator or label — do not make them the same. Example: if the region says \
"Apellidos y Nombres : SALAS SIGUAS, KATERIN KAROLA", value must be "SALAS SIGUAS, KATERIN KAROLA" (without the \
leading ":") and source_text can keep the full text.
7. The documents are in Spanish: copy names, codes, dates and amounts exactly as the document writes them. Never \
translate a value.
{self_check}""", filled=('hint', 'regions', 'schema', 'grounding', 'self_check'))


_SELF_CHECK = (
    "8. Before calling submit, call check_draft ONCE with the values you are going to submit ({field: value}). If it reports problems, "
    "re-read those fields' regions and correct them; if the document really says that, submit it anyway — do not invent values to make it add up.\n"
)


_SHOWN = 120


def _shown(text: str) -> str:
    """A region's text as listed: whole, or cut with a mark the agent knows means 'read it'."""
    return text if len(text) <= _SHOWN else text[:_SHOWN] + "…"


def build_system_prompt(
    hint: str, schema_cls: type[BaseModel], parsed: ParsedDocument, grounding: dict[str, str] | None = None, *, self_check: bool = False
) -> PromptTemplate:
    """``hint`` is the document type's extraction hint (catalog, VRT-32);
    ``grounding`` the business meaning of each field (VRT-46); ``self_check``
    adds the step that reviews the draft before submitting (VRT-67)."""
    # A layout box without text tells the agent nothing; a table or figure does (it can be read visually).
    regions = "\n".join(
        f"- region_id={b.region_id} type={b.block_type} page={b.page} ocr_text={_shown(b.text)!r}" for b in parsed.blocks if b.text or b.block_type != "text"
    )
    meaning = ""
    if grounding:
        lines = "\n".join(f"- {field}: {text}" for field, text in grounding.items())
        meaning = f"\nBusiness meaning of the fields (it helps you find the right data; it does not change the schema's format):\n{lines}\n"
    return _EXTRACTION.render(hint=hint, regions=regions, schema=schema_cls.model_json_schema(), grounding=meaning, self_check=_SELF_CHECK if self_check else "")
