"""``InferencePort`` (VRT-29): every model call goes through synaptum
(ADR-0006) — ``generate()``, journaled — over ``LocalGateway`` + axonium's
``AxoniumModel`` to prometheus's gateway. Moving to the governed route
(VRT-56) only swaps the ``Gateway``.

Three rules from the teams that own the pieces (canal VRT-AXO-001,
VRT-SYN-003):

- **One axonium client per event loop.** An async client belongs to the
  loop it was built in, so the port is opened by whoever owns a loop for the
  whole process — the API's lifespan, the worker's start — and closed with it.
- **Sync callers stay sync.** The pipeline stages run OCR and model calls
  in worker threads (``asyncio.to_thread``); they reach the port through
  ``structured()`` / ``vision()``, which run the call on the port's own loop.
- **Retries never pay twice.** ``AxoniumModel`` sends an ``Idempotency-Key``
  derived from the session's run id, the step and a hash of the request
  body. The run id here is the call's purpose, so the body hash is what
  tells two calls apart: a request repeated after a crash is served from
  prometheus (``idempotent_replay``) instead of generated again, and a
  different request is a new generation.

Structured output is validated by synaptum, which asks again showing the
validation error (each retry costs a step of ``max_steps``); a truncated
generation (``finish_reason == "length"``) never validates, so it surfaces as
``NoObjectGeneratedError`` instead of half a JSON."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator, Coroutine, Iterable
from contextlib import asynccontextmanager
from typing import Any, Literal, TypeVar

from axonium import AsyncAxonium
from axonium.config import Timeouts
from pydantic import BaseModel
from synaptum import Agent, FinalStep, Image, Limits, LocalGateway, MemoryCheckpointer, Phase, PromptTemplate, Sampling, Session, Text, ToolStep, generate
from synaptum.providers.axonium import AxoniumModel

from idp.config import Settings

log = logging.getLogger(__name__)

Role = Literal["reasoning", "vision"]
T = TypeVar("T", bound=BaseModel)

# Which model serves each role is not configured here: it is the one model of
# that modality this client may call in prometheus (``models.mine()``), so
# the client's ``model:<id>`` grants decide it, in one place.
_MODALITY: dict[Role, str] = {"reasoning": "text", "vision": "vision"}


class ModelResolutionError(RuntimeError):
    pass


def pick_models(catalog: Iterable[Any]) -> dict[Role, str]:
    """The model for each role among the ones granted to this client: exactly
    one per modality, or an error saying what to ask the prometheus operator."""
    granted = list(catalog)
    models: dict[Role, str] = {}
    problems = []
    for role, modality in _MODALITY.items():
        ids = sorted(m.id for m in granted if m.modality == modality)
        if len(ids) == 1:
            models[role] = ids[0]
        elif not ids:
            problems.append(f"ningún modelo de modalidad '{modality}' (pide el permiso model:<id> para el rol {role})")
        else:
            problems.append(f"varios modelos de modalidad '{modality}' ({', '.join(ids)}): deja uno solo para el rol {role}")
    if problems:
        raise ModelResolutionError("las credenciales de prometheus (AXONIUM_CLIENT_ID) tienen " + "; ".join(problems))
    return models

# Turns for a structured call: the first answer plus two corrections shown
# the validation error (what instructor's max_retries=2 used to give).
STRUCTURED_MAX_STEPS = 3


class Inference:
    def __init__(self, settings: Settings, *, model: Any = None, models: dict[Role, str] | None = None) -> None:
        """``model`` replaces axonium with any ``(Request) -> Response``
        callable, and ``models`` the role → model id discovery — for tests."""
        self._settings = settings
        self._models = models
        self._loop = asyncio.get_running_loop()
        self._client = None
        if model is None:
            if not settings.axonium_client_id or settings.axonium_client_secret is None:
                raise RuntimeError("faltan AXONIUM_CLIENT_ID / AXONIUM_CLIENT_SECRET (credenciales de prometheus)")
            timeout = settings.llm_request_timeout_seconds
            self._client = AsyncAxonium(
                client_id=settings.axonium_client_id,
                client_secret=settings.axonium_client_secret.get_secret_value(),
                timeouts=Timeouts(read=timeout, write=timeout),
            )
            model = AxoniumModel(client=self._client).complete
        self._model_call = model
        self._gateway = LocalGateway(model=model, warn=False)

    async def open(self) -> None:
        if self._models is None:
            if self._client is None:
                raise RuntimeError("con un modelo falso, indica models={'reasoning': ..., 'vision': ...}")
            self._models = pick_models(await self._client.models.mine())
            log.info("inference: modelos por rol según prometheus %s", self._models)

    @property
    def models(self) -> dict[Role, str]:
        """Role → model id, as resolved at open."""
        if self._models is None:
            raise RuntimeError("InferencePort sin abrir")
        return self._models

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    def _sampling(self) -> Sampling:
        return Sampling(temperature=0, max_output_tokens=self._settings.llm_max_output_tokens)

    def _model(self, role: Role) -> str:
        return self.models[role]

    async def _generate(self, purpose: str, role: Role, task: Any, **kwargs: Any) -> Any:
        model = self._model(role)
        checkpointer = MemoryCheckpointer()
        session = Session(run_id=f"veritium/{purpose}", gateway=self._gateway, checkpointer=checkpointer)
        result = await generate(task, model=model, session=session, sampling=self._sampling(), **kwargs)
        state = await checkpointer.load(session.run_id)
        answered = {step.response.model for step in state.events if getattr(step, "response", None) is not None}
        if answered - {model}:
            log.warning("inference: se pidió %s y respondió %s (%s)", model, sorted(answered), purpose)
        return result

    async def structured(self, *, purpose: str, role: Role, output: type[T], instructions: str | PromptTemplate, task: str) -> T:
        return await self._generate(purpose, role, task, instructions=instructions, output=output, max_steps=STRUCTURED_MAX_STEPS)

    async def vision(self, *, purpose: str, image_b64: str, prompt: str, mime_type: str = "image/png") -> str:
        return await self._generate(purpose, "vision", [Text(prompt), Image(media_type=mime_type, data=image_b64)], max_steps=1)

    async def run_agent(
        self, *, purpose: str, instructions: str | PromptTemplate, task: str, tools: list[Any], output: type[T], max_steps: int
    ) -> tuple[T, list[ToolStep]]:
        """A bounded tool-using agent on the reasoning model (VRT-30). The
        result arrives through synaptum's submit tool, validated against
        ``output``; an invalid submission is shown its error and costs a turn.
        Raises ``LimitExceeded`` (never submitted) or ``NoObjectGeneratedError``
        (submitted, never valid). Returns the result and the completed tool
        steps, for the extraction's trace."""
        gateway = LocalGateway(model=self._model_call, tools=tools, warn=False)
        agent = Agent(
            "veritium-extractor",
            model=self._model("reasoning"),
            instructions=instructions,
            tools=tools,
            output=output,
            # A retryable refusal — e.g. the same request still running for an identical document — is waited out, not given up on.
            limits=Limits(max_steps=max_steps, max_retries=self._settings.llm_max_retries),
            sampling=self._sampling(),
            submit_tool=True,
        )
        session = Session(run_id=f"veritium/{purpose}", gateway=gateway, checkpointer=MemoryCheckpointer())
        names = {t.name for t in tools}  # not the submit tool: its call is the result
        steps: list[ToolStep] = []
        result: Any = None
        async for step in agent.run(task, session=session):
            if isinstance(step, ToolStep) and step.phase == Phase.COMPLETED and step.call.name in names:
                steps.append(step)
            elif isinstance(step, FinalStep) and step.phase == Phase.COMPLETED:
                result = step.output
        return result, steps

    def run_sync(self, call: Coroutine[Any, Any, Any]) -> Any:
        """Run a call from a worker thread on the port's loop and wait for it."""
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self._loop:
            call.close()
            raise RuntimeError("llamada síncrona al InferencePort desde su propio loop: usa await")
        return asyncio.run_coroutine_threadsafe(call, self._loop).result()


_current: Inference | None = None


@asynccontextmanager
async def inference_lifespan(settings: Settings, *, model: Any = None, models: dict[Role, str] | None = None) -> AsyncGenerator[Inference]:
    global _current
    _current = Inference(settings, model=model, models=models)
    try:
        await _current.open()
        yield _current
    finally:
        await _current.aclose()
        _current = None


def inference() -> Inference:
    if _current is None:
        raise RuntimeError("InferencePort no iniciado: se abre en el lifespan de la API o al arrancar el worker")
    return _current


def model_for(role: Role) -> str:
    """The model id serving ``role`` (for spans and records)."""
    return inference().models[role]


def resolved_models() -> dict[Role, str] | None:
    """Role → model id, or None when the port is not open (e.g. a test without models)."""
    return dict(_current.models) if _current is not None and _current._models is not None else None


def structured(*, purpose: str, role: Role, output: type[T], instructions: str | PromptTemplate, task: str) -> T:
    """Sync entry point for the pipeline's threads."""
    port = inference()
    return port.run_sync(port.structured(purpose=purpose, role=role, output=output, instructions=instructions, task=task))
