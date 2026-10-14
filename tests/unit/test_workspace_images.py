from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentlab.api.app import create_app
from agentlab.api.images import MAX_IMAGE_BYTES
from tests.unit.test_project_experience import services

PNG = b"\x89PNG\r\n\x1a\n" + b"image-data"


def test_images_are_project_scoped_and_return_bytes_with_safe_headers(tmp_path: Path) -> None:
    svc = services(tmp_path)
    a, b = tmp_path / "one", tmp_path / "two"
    a.mkdir()
    b.mkdir()
    (a / "screen.png").write_bytes(PNG)
    (b / "screen.png").write_bytes(PNG + b"second")
    projects = [svc.projects.create(str(p.name), "test", str(p)) for p in (a, b)]
    with TestClient(create_app(svc)) as client:
        for project, expected in zip(projects, (PNG, PNG + b"second"), strict=True):
            response = client.get(f"/projects/{project.id}/images", params={"path": "screen.png"})
            assert response.status_code == 200
            assert response.content == expected
            assert response.headers["content-type"] == "image/png"
            assert response.headers["x-content-type-options"] == "nosniff"
            assert response.headers["content-disposition"] == "attachment"
        assert client.get("/projects/missing/images", params={"path": "screen.png"}).status_code == 404
        assert client.get(f"/projects/{projects[0].id}/images", params={"path": "missing.png"}).status_code == 404


@pytest.mark.parametrize("path", ["../screen.png", "/tmp/screen.png", "..\\screen.png", ".env/screen.png", ".git/screen.png", "keys/private.key", "screen.txt"])
def test_image_reads_reject_escapes_sensitive_paths_and_non_images(tmp_path: Path, path: str) -> None:
    svc = services(tmp_path)
    project = svc.projects.create("project", "test", str(tmp_path))
    with TestClient(create_app(svc)) as client:
        response = client.get(f"/projects/{project.id}/images", params={"path": path})
        assert response.status_code in {422, 415}


def test_symlink_files_directories_and_fifos_cannot_be_read(tmp_path: Path) -> None:
    svc = services(tmp_path)
    root, outside = tmp_path / "project", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "secret.png").write_bytes(PNG)
    (root / "link.png").symlink_to(outside / "secret.png")
    (root / "linked").symlink_to(outside, target_is_directory=True)
    (root / "inside.png").write_bytes(PNG)
    (root / "internal.png").symlink_to(root / "inside.png")
    os.mkfifo(root / "pipe.png")
    project = svc.projects.create("project", "test", str(root))
    with TestClient(create_app(svc)) as client:
        for path in ["link.png", "linked/secret.png", "internal.png", "pipe.png"]:
            assert client.get(f"/projects/{project.id}/images", params={"path": path}).status_code == 422


def test_images_enforce_size_signature_and_svg_security(tmp_path: Path) -> None:
    svc = services(tmp_path)
    project = svc.projects.create("project", "test", str(tmp_path))
    (tmp_path / "fake.png").write_text("private text renamed as a picture")
    with (tmp_path / "huge.png").open("wb") as file:
        file.truncate(MAX_IMAGE_BYTES + 1)
    (tmp_path / "diagram.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"><rect width="5" height="5"/></svg>')
    (tmp_path / "entity.svg").write_text('<!DOCTYPE svg [<!ENTITY x "bad">]><svg>&x;</svg>')
    with TestClient(create_app(svc)) as client:
        url = f"/projects/{project.id}/images"
        assert client.get(url, params={"path": "fake.png"}).status_code == 415
        assert client.get(url, params={"path": "huge.png"}).status_code == 413
        assert client.get(url, params={"path": "entity.svg"}).status_code == 415
        response = client.get(url, params={"path": "diagram.svg"})
        assert response.status_code == 200
        assert response.headers["content-security-policy"] == "sandbox; default-src 'none'"
