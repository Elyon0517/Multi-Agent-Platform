"""Bounded, project-confined image reads. Never accept a client-supplied host root."""

from __future__ import annotations

import errno
import os
import stat
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree

from fastapi import APIRouter, HTTPException, Query, Response

from agentlab.adapters.workspace import GitWorkspace
from agentlab.bootstrap import Services
from agentlab.core.ports import RunBusy

MAX_IMAGE_BYTES = 10 * 1024 * 1024
IMAGE_MIME = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
    ".webp": "image/webp", ".bmp": "image/bmp", ".ico": "image/x-icon", ".avif": "image/avif",
    ".svg": "image/svg+xml",
}


def _is_image(data: bytes, suffix: str) -> bool:
    if suffix == ".svg":
        if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
            return False
        try:
            root = ElementTree.fromstring(data.decode("utf-8-sig"))
            return root.tag in {"svg", "{http://www.w3.org/2000/svg}svg"}
        except (ValueError, ElementTree.ParseError):
            return False
    signatures = {
        ".png": b"\x89PNG\r\n\x1a\n", ".jpg": b"\xff\xd8\xff", ".jpeg": b"\xff\xd8\xff",
        ".gif": b"GIF8", ".bmp": b"BM", ".ico": b"\x00\x00\x01\x00",
    }
    if suffix == ".webp":
        return data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    if suffix == ".avif":
        return data[4:8] == b"ftyp" and (b"avif" in data[8:64] or b"avis" in data[8:64])
    return data.startswith(signatures[suffix])


def read_project_image(root: Path, rel: str) -> tuple[bytes, str]:
    parts = PurePosixPath(rel).parts
    if (not parts or rel.startswith("/") or "\\" in rel or "\x00" in rel
            or any(p in {".", ".."} for p in rel.split("/")) or GitWorkspace._sensitive(rel)):
        raise HTTPException(422, "invalid image path")
    suffix = PurePosixPath(rel).suffix.lower()
    if suffix not in IMAGE_MIME:
        raise HTTPException(415, "unsupported image type")
    # Walk directory descriptors with O_NOFOLLOW: containment survives a concurrent symlink replacement.
    directory: int | None = None
    handle: int | None = None
    try:
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        handle = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        info = os.fstat(handle)
        if not stat.S_ISREG(info.st_mode):
            raise HTTPException(422, "image must be a regular file")
        if info.st_size > MAX_IMAGE_BYTES:
            raise HTTPException(413, "image larger than 10 MB")
        with os.fdopen(handle, "rb") as file:
            handle = None
            data = file.read(MAX_IMAGE_BYTES + 1)
        if len(data) > MAX_IMAGE_BYTES:
            raise HTTPException(413, "image larger than 10 MB")
    except OSError as exc:
        code = 404 if exc.errno == errno.ENOENT else 422
        raise HTTPException(code, "image missing or path is not readable") from exc
    finally:
        if handle is not None:
            os.close(handle)
        if directory is not None:
            os.close(directory)
    if not _is_image(data, suffix):
        raise HTTPException(415, "file content does not match its image type")
    return data, IMAGE_MIME[suffix]


def build_image_router(svc: Services) -> APIRouter:
    router = APIRouter()

    @router.get("/projects/{project_id}/images", response_class=Response)
    def image(project_id: str, path: str = Query(min_length=1, max_length=4096)) -> Response:
        try:
            with svc.store.lock_run("project:" + project_id):
                try:
                    project = svc.projects.get(project_id)
                except KeyError as exc:
                    raise HTTPException(404, "project not found") from exc
                data, mime = read_project_image(Path(project.workspace), path)
        except RunBusy as exc:
            raise HTTPException(409, "project is busy") from exc
        return Response(data, media_type=mime, headers={
            "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store",
            "Content-Disposition": "attachment",
            "Content-Security-Policy": "sandbox; default-src 'none'",
        })

    return router
