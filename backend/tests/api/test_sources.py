"""BE-03: /sources endpoints (contracts/openapi.yaml). Multipart error paths are bare form field
names (`file`, `delimiter`, ...); path/query errors are JSON Pointers (`/source_id`, `/limit`)."""

import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.settings import Settings
from app.models import DataSource, Pipeline

CSV = b"id,name,score\n1,Ada,9.5\n2,Grace,\n3,Linus,7\n"
BASE = "/api/v1/sources"


def upload(
    client: TestClient,
    content: bytes = CSV,
    filename: str = "people.csv",
    content_type: str = "text/csv",
    **fields: str,
) -> Any:
    return client.post(
        BASE, files={"file": (filename, content, content_type)}, data=dict(fields) or None
    )


def error(resp: Any, status: int, code: str) -> dict[str, Any]:
    assert resp.status_code == status, resp.text
    body: dict[str, Any] = resp.json()["error"]
    assert body["code"] == code
    return body


def leftovers(data_dir: Path) -> list[str]:
    tmp = data_dir / "tmp"
    return sorted(p.name for p in tmp.iterdir()) if tmp.exists() else []


def row_count(session: Session) -> int:
    return session.scalar(sa.select(sa.func.count()).select_from(DataSource)) or 0


# --- POST /sources ----------------------------------------------------------------------------


def test_upload_stores_profiles_and_returns_data_source(
    api_client: TestClient, api_session: Session, data_dir: Path
) -> None:
    resp = upload(api_client)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert set(body) == {
        "id", "name", "original_filename", "size_bytes", "csv_options", "columns", "row_count",
        "created_at",
    }  # fmt: skip
    assert body["name"] == "people.csv" == body["original_filename"]
    assert body["size_bytes"] == len(CSV)
    assert body["row_count"] == 3
    assert body["csv_options"] == {
        "encoding": "utf-8", "delimiter": ",", "has_header": True, "quote_char": '"',
    }  # fmt: skip
    assert body["columns"] == [
        {"name": "id", "inferred_type": "integer", "null_count": 0},
        {"name": "name", "inferred_type": "string", "null_count": 0},
        {"name": "score", "inferred_type": "float", "null_count": 1},
    ]
    assert body["created_at"].endswith("Z")

    stored = data_dir / "sources" / f"{body['id']}.csv"
    assert stored.read_bytes() == CSV
    assert leftovers(data_dir) == []
    row = api_session.get(DataSource, uuid.UUID(body["id"]))
    assert row is not None
    assert row.stored_path == f"sources/{body['id']}.csv"
    assert len(row.sha256) == 64
    assert row.size_bytes == len(CSV)


def test_upload_name_and_csv_options(api_client: TestClient) -> None:
    content = "id;city\n1;Zürich\n".encode("latin-1")
    resp = upload(
        api_client, content, name="Cities", encoding="latin-1", delimiter=";", has_header="true"
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "Cities"
    assert body["csv_options"]["encoding"] == "latin-1"
    assert body["csv_options"]["delimiter"] == ";"
    assert [c["name"] for c in body["columns"]] == ["id", "city"]


def test_upload_without_header_names_columns(api_client: TestClient) -> None:
    resp = upload(api_client, b"1,a\n2,b\n", has_header="false")
    assert resp.status_code == 201, resp.text
    assert [c["name"] for c in resp.json()["columns"]] == ["column_1", "column_2"]
    assert resp.json()["row_count"] == 2


def test_upload_filename_path_components_are_dropped(api_client: TestClient) -> None:
    resp = upload(api_client, filename="../../etc/evil.csv")
    assert resp.status_code == 201
    assert resp.json()["original_filename"] == "evil.csv"


def test_upload_accepts_csv_content_type_without_csv_extension(api_client: TestClient) -> None:
    assert upload(api_client, filename="export.dat", content_type="text/csv").status_code == 201


def test_upload_accepts_csv_extension_with_generic_content_type(api_client: TestClient) -> None:
    resp = upload(api_client, filename="X.CSV", content_type="application/octet-stream")
    assert resp.status_code == 201


def test_malformed_records_count_in_row_count_but_not_in_preview(api_client: TestClient) -> None:
    resp = upload(api_client, b"a,b\n1,2\n3\n4,5\n")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["row_count"] == 3
    preview = api_client.get(f"{BASE}/{body['id']}/preview").json()
    assert preview["sampled_rows"] == 2
    assert preview["rows"] == [{"a": "1", "b": "2"}, {"a": "4", "b": "5"}]


def test_upload_at_exact_limit_is_accepted(api_client: TestClient, settings: Settings) -> None:
    line = b"x" * 1023 + b"\n"  # many short rows: a single field may not exceed 131,072 chars
    content = b"a\n" + line * ((settings.max_upload_bytes - 2) // len(line))
    content += b"y" * (settings.max_upload_bytes - len(content) - 1) + b"\n"
    assert len(content) == settings.max_upload_bytes
    assert upload(api_client, content).status_code == 201


def test_upload_over_limit_aborts_with_413_and_leaves_nothing(
    api_client: TestClient, api_session: Session, data_dir: Path, settings: Settings
) -> None:
    content = b"a\n" + (b"x" * 1023 + b"\n") * (settings.max_upload_bytes // 1024)
    body = error(upload(api_client, content), 413, "payload_too_large")
    assert "1 MB" in body["message"]
    assert leftovers(data_dir) == []
    assert not (data_dir / "sources").exists() or not list((data_dir / "sources").iterdir())
    assert row_count(api_session) == 0


def test_chunked_upload_over_limit_is_cut_off_while_streaming(
    api_client: TestClient, data_dir: Path, settings: Settings
) -> None:
    """No Content-Length: the limit must still stop the write part-way."""
    boundary = "b0undary"
    sent = {"bytes": 0}

    def body() -> Iterator[bytes]:
        yield (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="big.csv"\r\n'
            "Content-Type: text/csv\r\n\r\na\n"
        ).encode()
        for _ in range(40):  # 40 MiB offered against a 1 MiB limit
            sent["bytes"] += 1024 * 1024
            yield b"x" * 1024 * 1024
        yield f"\r\n--{boundary}--\r\n".encode()

    resp = api_client.post(
        BASE,
        content=body(),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    error(resp, 413, "payload_too_large")
    assert leftovers(data_dir) == []


def test_non_csv_is_415(api_client: TestClient, api_session: Session, data_dir: Path) -> None:
    error(
        upload(api_client, b"hello", filename="notes.txt", content_type="text/plain"),
        415,
        "unsupported_media_type",
    )
    assert leftovers(data_dir) == []
    assert row_count(api_session) == 0


def test_non_multipart_request_is_415(api_client: TestClient) -> None:
    error(api_client.post(BASE, json={"a": 1}), 415, "unsupported_media_type")


def test_missing_file_is_422_on_file_path(api_client: TestClient) -> None:
    resp = api_client.post(BASE, files={"name": (None, "x")})
    assert error(resp, 422, "validation_error")["details"][0]["path"] == "file"


@pytest.mark.parametrize(
    ("field", "value", "message_part"),
    [
        ("delimiter", "tab", "input should be"),
        ("encoding", "utf-16", "input should be"),
        ("has_header", "maybe", "boolean"),
        ("quote_char", "''", "at most 1"),
        ("quote_char", "", "at least 1"),
        ("name", "", "at least 1"),
        ("name", "n" * 201, "at most 200"),
        ("unknown_field", "1", "extra"),
    ],
)
def test_invalid_form_fields_report_field_name_paths(
    api_client: TestClient, api_session: Session, field: str, value: str, message_part: str
) -> None:
    body = error(upload(api_client, **{field: value}), 422, "validation_error")
    assert [d["path"] for d in body["details"]] == [field]
    assert message_part in body["details"][0]["message"].lower()
    assert row_count(api_session) == 0


def test_all_invalid_fields_are_reported_together(api_client: TestClient) -> None:
    body = error(upload(api_client, delimiter="x", encoding="y"), 422, "validation_error")
    assert sorted(d["path"] for d in body["details"]) == ["delimiter", "encoding"]


def test_duplicate_form_field_is_422(api_client: TestClient) -> None:
    resp = api_client.post(BASE, files=[("file", ("a.csv", CSV, "text/csv")), ("name", (None, "a")),
                                         ("name", (None, "b"))])  # fmt: skip
    body = error(resp, 422, "validation_error")
    assert body["details"][0]["path"] == "name"


@pytest.mark.parametrize(
    ("content", "options", "message_part"),
    [
        (b"", {}, ""),
        (b"a,b\n", {}, ""),
        (b"a,a\n1,2\n", {}, "duplicate header names"),
        (b"a,,c\n1,2,3\n", {}, "column 2 is empty"),
        (b'a,b\n"unterminated,1\n2,3\n', {}, ""),
        (b"a,b\n\xff\xfe,1\n", {}, ""),
    ],
)
def test_csv_format_errors_are_422_and_create_nothing(
    api_client: TestClient,
    api_session: Session,
    data_dir: Path,
    content: bytes,
    options: dict[str, str],
    message_part: str,
) -> None:
    body = error(upload(api_client, content, **options), 422, "validation_error")
    assert message_part in body["message"]
    assert body["details"][0]["path"] == "file"
    assert body["details"][0]["message"] == body["message"]
    assert leftovers(data_dir) == []
    assert not (data_dir / "sources").exists() or not list((data_dir / "sources").iterdir())
    assert row_count(api_session) == 0


def test_more_than_500_columns_is_422(api_client: TestClient) -> None:
    header = ",".join(f"c{i}" for i in range(501)).encode()
    error(upload(api_client, header + b"\n" + b"1," * 500 + b"1\n"), 422, "validation_error")


def test_database_failure_removes_stored_file(
    api_client: TestClient, api_session: Session, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(self: Session) -> None:
        raise sa.exc.OperationalError("commit", {}, Exception("db down"))

    monkeypatch.setattr(Session, "commit", boom)
    error(upload(api_client), 500, "internal_error")
    monkeypatch.undo()
    assert leftovers(data_dir) == []
    assert not list((data_dir / "sources").iterdir())
    assert row_count(api_session) == 0


# --- GET /sources -----------------------------------------------------------------------------


def test_list_is_paginated_newest_first(api_client: TestClient) -> None:
    ids = [upload(api_client, name=f"s{i}").json()["id"] for i in range(5)]
    page = api_client.get(BASE, params={"limit": 2, "offset": 1}).json()
    assert (page["total"], page["limit"], page["offset"]) == (5, 2, 1)
    assert [i["id"] for i in page["items"]] == [ids[3], ids[2]]
    default = api_client.get(BASE).json()
    assert (default["limit"], default["offset"], len(default["items"])) == (50, 0, 5)
    assert default["items"][0]["id"] == ids[4]


def test_list_empty(api_client: TestClient) -> None:
    assert api_client.get(BASE).json() == {"total": 0, "limit": 50, "offset": 0, "items": []}


@pytest.mark.parametrize(
    ("params", "path"),
    [({"limit": 0}, "/limit"), ({"limit": 201}, "/limit"), ({"offset": -1}, "/offset"),
     ({"limit": "x"}, "/limit")],
)  # fmt: skip
def test_list_rejects_bad_pagination(
    api_client: TestClient, params: dict[str, Any], path: str
) -> None:
    body = error(api_client.get(BASE, params=params), 422, "validation_error")
    assert body["details"][0]["path"] == path


# --- GET / DELETE /sources/{id} ----------------------------------------------------------------


def test_get_source(api_client: TestClient) -> None:
    created = upload(api_client).json()
    assert api_client.get(f"{BASE}/{created['id']}").json() == created


def test_get_unknown_source_is_404(api_client: TestClient) -> None:
    body = error(api_client.get(f"{BASE}/{uuid.uuid4()}"), 404, "not_found")
    assert body["message"]


def test_invalid_uuid_is_422(api_client: TestClient) -> None:
    body = error(api_client.get(f"{BASE}/not-a-uuid"), 422, "validation_error")
    assert body["details"][0]["path"] == "/source_id"


def test_delete_removes_row_and_file(
    api_client: TestClient, api_session: Session, data_dir: Path
) -> None:
    sid = upload(api_client).json()["id"]
    stored = data_dir / "sources" / f"{sid}.csv"
    assert stored.exists()
    resp = api_client.delete(f"{BASE}/{sid}")
    assert resp.status_code == 204
    assert resp.content == b""
    assert not stored.exists()
    assert row_count(api_session) == 0
    error(api_client.get(f"{BASE}/{sid}"), 404, "not_found")
    error(api_client.delete(f"{BASE}/{sid}"), 404, "not_found")


def test_delete_referenced_source_is_409_and_keeps_file(
    api_client: TestClient, api_session: Session, data_dir: Path
) -> None:
    sid = upload(api_client).json()["id"]
    api_session.add(Pipeline(name="p", source_id=uuid.UUID(sid), config={}))
    api_session.commit()
    body = error(api_client.delete(f"{BASE}/{sid}"), 409, "conflict")
    assert "pipeline" in body["message"]
    assert (data_dir / "sources" / f"{sid}.csv").exists()
    assert api_client.get(f"{BASE}/{sid}").status_code == 200


# --- GET /sources/{id}/preview -----------------------------------------------------------------


def test_preview_default_and_limit(api_client: TestClient) -> None:
    sid = upload(api_client).json()["id"]
    full = api_client.get(f"{BASE}/{sid}/preview")
    assert full.status_code == 200
    body = full.json()
    assert set(body) == {"source_id", "columns", "rows", "sampled_rows"}
    assert body["source_id"] == sid
    assert body["rows"] == [
        {"id": "1", "name": "Ada", "score": "9.5"},
        {"id": "2", "name": "Grace", "score": None},
        {"id": "3", "name": "Linus", "score": "7"},
    ]
    assert body["sampled_rows"] == 3
    assert [c["name"] for c in body["columns"]] == ["id", "name", "score"]

    two = api_client.get(f"{BASE}/{sid}/preview", params={"limit": 2}).json()
    assert len(two["rows"]) == 2


@pytest.mark.parametrize("limit", ["0", "501", "abc"])
def test_preview_rejects_bad_limit(api_client: TestClient, limit: str) -> None:
    sid = upload(api_client).json()["id"]
    body = error(api_client.get(f"{BASE}/{sid}/preview", params={"limit": limit}), 422,
                 "validation_error")  # fmt: skip
    assert body["details"][0]["path"] == "/limit"


def test_preview_unknown_source_is_404(api_client: TestClient) -> None:
    error(api_client.get(f"{BASE}/{uuid.uuid4()}/preview"), 404, "not_found")


def test_preview_with_missing_stored_file_is_internal_error(
    api_client: TestClient, data_dir: Path
) -> None:
    sid = upload(api_client).json()["id"]
    (data_dir / "sources" / f"{sid}.csv").unlink()
    error(api_client.get(f"{BASE}/{sid}/preview"), 500, "internal_error")


def test_preview_of_file_that_became_invalid_is_422(api_client: TestClient, data_dir: Path) -> None:
    sid = upload(api_client).json()["id"]
    (data_dir / "sources" / f"{sid}.csv").write_bytes(b"")
    error(api_client.get(f"{BASE}/{sid}/preview"), 422, "validation_error")


# --- contract surface --------------------------------------------------------------------------


def test_served_openapi_has_source_operations(api_client: TestClient) -> None:
    spec = api_client.get("/openapi.json").json()
    ops = {
        op["operationId"]
        for path, item in spec["paths"].items()
        if path.startswith("/api/v1/sources")
        for op in item.values()
    }
    assert ops == {"createSource", "listSources", "getSource", "deleteSource", "previewSource"}
    post = spec["paths"]["/api/v1/sources"]["post"]
    assert "multipart/form-data" in post["requestBody"]["content"]
