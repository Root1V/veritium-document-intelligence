"""Unit tests for VRT-29's InferencePort, with a fake model behind
synaptum's LocalGateway (no prometheus): what reaches the model, the
re-ask on a validation error, and the bridge from the pipeline's threads."""

from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel
from synaptum import FinishReason, Image, Message, NoObjectGeneratedError, Request, Response, Role, Text

from idp.config import Settings
from idp.llm import port


class Clase(BaseModel):
    tipo: str


class FakeModel:
    def __init__(self, *answers: str, finish: FinishReason = FinishReason.STOP) -> None:
        self.answers, self.finish, self.requests = list(answers), finish, []

    async def __call__(self, request: Request, ctx: object = None) -> Response:
        self.requests.append(request)
        return Response(message=Message(Role.ASSISTANT, (Text(self.answers.pop(0)),)), finish_reason=self.finish, model=request.model)


MODELS = {"reasoning": "razonador", "vision": "vlm"}


def _settings() -> Settings:
    return Settings(_env_file=None)


def _texts(request: Request) -> str:
    return " ".join(p.text for m in request.messages for p in m.content if isinstance(p, Text))


@pytest.mark.asyncio
async def test_structured_sends_instructions_task_and_temperature_zero():
    fake = FakeModel('{"tipo": "boleta"}')
    async with port.inference_lifespan(_settings(), model=fake, models=MODELS) as inference:
        result = await inference.structured(purpose="classify", role="reasoning", output=Clase, instructions="Eres un clasificador", task="Texto: boleta de pago")
    assert result == Clase(tipo="boleta")
    (request,) = fake.requests
    assert request.model == "razonador" and request.temperature == 0 and request.max_output_tokens == 8192
    assert request.system.startswith("Eres un clasificador") and "boleta de pago" in _texts(request)


@pytest.mark.asyncio
async def test_an_invalid_answer_is_asked_again_showing_the_error():
    fake = FakeModel('{"otro": 1}', '{"tipo": "boleta"}')
    async with port.inference_lifespan(_settings(), model=fake, models=MODELS) as inference:
        result = await inference.structured(purpose="classify", role="reasoning", output=Clase, instructions="x", task="y")
    assert result == Clase(tipo="boleta") and len(fake.requests) == 2
    assert "tipo" in _texts(fake.requests[1])  # the second turn carries the validation error


@pytest.mark.asyncio
async def test_a_truncated_answer_is_not_half_an_object():
    fake = FakeModel('{"tipo": "bol', '{"tipo": "bol', '{"tipo": "bol', finish=FinishReason.LENGTH)
    async with port.inference_lifespan(_settings(), model=fake, models=MODELS) as inference:
        with pytest.raises(NoObjectGeneratedError):
            await inference.structured(purpose="classify", role="reasoning", output=Clase, instructions="x", task="y")


@pytest.mark.asyncio
async def test_vision_sends_the_image_to_the_vision_model():
    fake = FakeModel("Boleta de pago.")
    async with port.inference_lifespan(_settings(), model=fake, models=MODELS) as inference:
        text = await inference.vision(purpose="read_table_region", image_b64="aGVsbG8=", prompt="¿Qué es?")
    assert text == "Boleta de pago."
    (request,) = fake.requests
    images = [p for m in request.messages for p in m.content if isinstance(p, Image)]
    assert request.model == "vlm" and images[0].data == "aGVsbG8=" and images[0].media_type == "image/png"


@pytest.mark.asyncio
async def test_sync_callers_in_threads_run_on_the_ports_loop():
    fake = FakeModel('{"tipo": "boleta"}')
    async with port.inference_lifespan(_settings(), model=fake, models=MODELS):
        result = await asyncio.to_thread(port.structured, purpose="classify", role="reasoning", output=Clase, instructions="x", task="y")
        assert result.tipo == "boleta"
        with pytest.raises(RuntimeError, match="propio loop"):
            port.structured(purpose="classify", role="reasoning", output=Clase, instructions="x", task="y")


def test_calling_before_the_port_is_open_says_where_it_opens():
    with pytest.raises(RuntimeError, match="lifespan"):
        port.structured(purpose="classify", role="reasoning", output=Clase, instructions="x", task="y")


class _Granted:
    def __init__(self, id: str, modality: str) -> None:
        self.id, self.modality = id, modality


def test_each_role_gets_the_one_granted_model_of_its_modality():
    granted = [_Granted("qwen3vl-30b-a3b", "vision"), _Granted("bge", "embedding"), _Granted("gpt-oss-20b-mxfp4", "text")]
    assert port.pick_models(granted) == {"reasoning": "gpt-oss-20b-mxfp4", "vision": "qwen3vl-30b-a3b"}


def test_missing_or_ambiguous_grants_say_what_to_ask_for():
    with pytest.raises(port.ModelResolutionError, match="ningún modelo de modalidad 'vision'"):
        port.pick_models([_Granted("gpt-oss", "text")])
    with pytest.raises(port.ModelResolutionError, match="varios modelos de modalidad 'text' \\(a, b\\)"):
        port.pick_models([_Granted("b", "text"), _Granted("a", "text"), _Granted("v", "vision")])


@pytest.mark.asyncio
async def test_the_models_are_discovered_from_prometheus_through_axonium(monkeypatch):
    class Catalog:
        async def mine(self):
            return [_Granted("gpt-oss-20b-mxfp4", "text"), _Granted("qwen3vl-30b-a3b", "vision")]

    class Client:
        def __init__(self, **_):
            self.models = Catalog()

        async def aclose(self):
            pass

    monkeypatch.setattr(port, "AsyncAxonium", Client)
    settings = Settings(_env_file=None, axonium_client_id="veritium", axonium_client_secret="s")
    async with port.inference_lifespan(settings) as inference:
        assert inference.models == {"reasoning": "gpt-oss-20b-mxfp4", "vision": "qwen3vl-30b-a3b"}
        assert port.model_for("vision") == "qwen3vl-30b-a3b" and port.resolved_models() == inference.models
    assert port.resolved_models() is None
