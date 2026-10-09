"""How a bulk archive becomes cases (VRT-48): one folder per case, an
optional manifest, and what cannot be used skipped with a reason."""

from __future__ import annotations

import pytest

from idp.domain.bulk_archive import plan

MB = 1024 * 1024


def _plan(files, rows=None, *, default_profile="convenios", max_cases=10):
    return plan([(p, 100) for p in files], rows, default_profile=default_profile, max_cases=max_cases, max_file_bytes=MB)


def test_one_case_per_folder_with_its_documents():
    planned, skipped = _plan(["EXP-2/boleta.pdf", "EXP-1/dni.jpg", "EXP-1/solicitud.pdf"])
    assert [(c.reference, c.files) for c in planned] == [("EXP-1", ["EXP-1/dni.jpg", "EXP-1/solicitud.pdf"]), ("EXP-2", ["EXP-2/boleta.pdf"])]
    assert all(c.profile == "convenios" and c.process_data == {} for c in planned) and skipped == []


def test_a_zipped_parent_folder_is_looked_through():
    planned, _ = _plan(["lote/EXP-1/a.pdf", "lote/EXP-2/b.pdf"])
    assert [(c.reference, c.files) for c in planned] == [("EXP-1", ["lote/EXP-1/a.pdf"]), ("EXP-2", ["lote/EXP-2/b.pdf"])]


def test_manifest_gives_profile_and_process_data():
    rows = [{"Expediente": "EXP-1", "Perfil": "otro", "nacionalidad": "PE", "plazo": 30.0}, {"expediente": "EXP-9", "perfil": ""}]
    planned, skipped = _plan(["manifiesto.csv", "EXP-1/a.pdf", "EXP-2/b.pdf"], rows)
    assert [(c.reference, c.profile, c.process_data) for c in planned] == [("EXP-1", "otro", {"nacionalidad": "PE", "plazo": "30"}), ("EXP-2", "convenios", {})]
    assert [s.reference for s in skipped] == ["EXP-9"]


def test_what_cannot_be_used_is_skipped_with_a_reason():
    files = [("suelto.pdf", 100), ("EXP-1/notas.docx", 100), ("EXP-1/grande.pdf", 2 * MB), ("EXP-2/a.pdf", 100), ("__MACOSX/EXP-2/._a.pdf", 1), ("EXP-2/.DS_Store", 1)]
    planned, skipped = plan(files, None, default_profile="convenios", max_cases=10, max_file_bytes=MB)
    assert [c.reference for c in planned] == ["EXP-2"]
    assert [(s.reference, s.reason.split(":")[0]) for s in skipped] == [(None, "suelto.pdf"), ("EXP-1", "notas.docx"), ("EXP-1", "grande.pdf")]


def test_without_any_profile_the_case_is_skipped():
    planned, skipped = _plan(["EXP-1/a.pdf"], default_profile=None)
    assert planned == [] and "perfil" in skipped[0].reason


def test_whole_archive_rejected_when_too_many_cases_or_manifest_without_reference():
    with pytest.raises(ValueError, match="máximo"):
        _plan(["A/a.pdf", "B/b.pdf"], max_cases=1)
    with pytest.raises(ValueError, match="expediente"):
        _plan(["manifiesto.csv", "A/a.pdf"], [{"caso": "A"}])
