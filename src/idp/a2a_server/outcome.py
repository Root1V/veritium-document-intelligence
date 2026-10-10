"""How a case run becomes an A2A task's state (VRT-52), the same for the
executor that follows it live and the store that settles it after a restart:

- the run still going → ``working``, with what is happening now;
- the verdict asks for evidence the case lacks → ``input-required``: the
  missing items are named and the caller answers on the same task with the
  documents — the protocol's interrupted state is Veritium's "return to
  client" when there is something to hand back;
- any other verdict → ``completed``;
- a run that stopped on an error → ``failed``.

The outcome always travels as the ``resultado`` artifact: the data an agent
reads (``CaseOutcome``) and a one-line summary for a person."""

from __future__ import annotations

from dataclasses import dataclass

from a2a.helpers import new_artifact, new_data_part, new_text_message, new_text_part
from a2a.types import Artifact, Message, Task, TaskState
from sqlalchemy.ext.asyncio import AsyncSession

from idp.api.case_contract import latest_run
from idp.api.case_outcome import CaseOutcome, case_outcome
from idp.persistence.models import Case

ARTIFACT_ID = "resultado"


@dataclass(frozen=True)
class Final:
    state: TaskState
    text: str


def final(outcome: CaseOutcome) -> Final:
    if outcome.status == "failed":
        return Final(TaskState.TASK_STATE_FAILED, outcome.reasons[0] if outcome.reasons else "El proceso se detuvo por un error.")
    if outcome.verdict == "return_to_client" and outcome.missing:
        return Final(
            TaskState.TASK_STATE_INPUT_REQUIRED,
            f"Faltan: {'; '.join(outcome.missing)}. Envía esos documentos en esta misma tarea para completar el expediente.",
        )
    reasons = f" Motivos: {' | '.join(outcome.reasons)}" if outcome.reasons else ""
    return Final(TaskState.TASK_STATE_COMPLETED, f"Veredicto: {outcome.verdict_label}.{reasons}")


def artifact(outcome: CaseOutcome) -> Artifact:
    summary = final(outcome).text
    return new_artifact(
        [new_data_part(outcome.model_dump(mode="json")), new_text_part(summary)], name="Resultado del expediente", artifact_id=ARTIFACT_ID
    )


def agent_message(text: str, task: Task) -> Message:
    return new_text_message(text, context_id=task.context_id, task_id=task.id)


async def settle(session: AsyncSession, task: Task, case: Case) -> Task | None:
    """The task as its case's latest run left it, or None while that run goes on."""
    run = latest_run(case)
    if run is None or run.status not in ("completed", "failed"):
        return None
    outcome = await case_outcome(session, case)
    done = final(outcome)
    settled = Task()
    settled.CopyFrom(task)
    settled.status.state = done.state
    settled.status.message.CopyFrom(agent_message(done.text, task))
    settled.status.timestamp.GetCurrentTime()
    kept = [a for a in settled.artifacts if a.artifact_id != ARTIFACT_ID]
    del settled.artifacts[:]
    settled.artifacts.extend([*kept, artifact(outcome)])
    return settled
