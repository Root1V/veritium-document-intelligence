"""POST /v1/events — commands as CloudEvents over HTTP (VRT-49): the same
commands the bus consumer takes (events/inbound.py), for a sender — or a
bus that pushes over HTTP — without Kafka. Structured mode
(``Content-Type: application/cloudevents+json``) or binary mode
(``ce-*`` headers, the data as the JSON body). 202 with the case when
accepted; 422 with the reason when not. Either way the answer also goes
out as an event."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from idp.api.deps import get_app_settings, require_role
from idp.config import Settings
from idp.events.inbound import Answer, binary, handle, structured

router = APIRouter(prefix="/v1/events", tags=["events"])


@router.post("", response_model=Answer, status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(require_role("integracion", "operador", "admin"))])
async def receive(request: Request, settings: Settings = Depends(get_app_settings)) -> Answer:
    body = await request.body()
    try:
        if request.headers.get("content-type", "").startswith("application/cloudevents+json"):
            event = structured(body)
        else:
            event = binary({k.removeprefix("ce-"): v for k, v in request.headers.items() if k.startswith("ce-")}, body)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    answer = await handle(settings, event)
    if not answer.accepted:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=answer.reason)
    return answer
