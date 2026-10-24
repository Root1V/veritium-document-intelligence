"""Index for search (VRT-59) every case processed before it, of every
business unit: each run indexes its own case from then on. Safe to repeat —
a piece that did not change keeps its embedding.

    uv run python scripts/reindex_search.py
"""

from __future__ import annotations

import asyncio
import logging

from idp.config import get_settings
from idp.search.index import reindex_all
from idp.search.models import search_models_lifespan


async def main() -> None:
    settings = get_settings()
    async with search_models_lifespan(settings):
        pieces = await reindex_all(settings)
    print(f"{pieces} fragmentos indexados")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
