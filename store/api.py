from contextlib import asynccontextmanager
import hmac
import ipaddress
import logging
import os
from pathlib import Path
import tempfile

import anyio
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from .repository import PublishError, Repository


class OpenFileResponse(FileResponse):
    """Pin the file across publication and close it even on client disconnect."""
    def __init__(self, file, **kwargs):
        self.file = file
        super().__init__(f"/proc/self/fd/{file.fileno()}", stat_result=os.fstat(file.fileno()), **kwargs)

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.file.close()


def repository_from_env():
    return Repository(os.environ.get("STORE_DATA", "/data"),
                      os.environ.get("STORE_REPO_URL", "http://127.0.0.1:8766/fdroid/repo"),
                      fdroid=os.environ.get("FDROID", "fdroid"), aapt=os.environ.get("AAPT", "aapt"),
                      apksigner=os.environ.get("APKSIGNER", "apksigner"))


def create_api(repository=None, key=None, allowed=None, max_bytes=None, initialize=True):
    repository = repository or repository_from_env()
    if key is None:
        key = Path(os.environ.get("STORE_API_KEY_FILE", "/run/secrets/store_api_key")).read_text().strip()
    if len(key) < 32:
        raise ValueError("API key must contain at least 32 characters")
    networks = [ipaddress.ip_network(n.strip()) for n in (allowed or os.environ.get(
        "STORE_ALLOWED_NETWORKS", "127.0.0.0/8,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,fc00::/7")).split(",")]
    max_bytes = max_bytes or int(os.environ.get("STORE_MAX_APK_BYTES", str(512 * 1024 * 1024)))

    @asynccontextmanager
    async def lifespan(app):
        if initialize:
            await run_in_threadpool(repository.initialize)
        yield

    app = FastAPI(title="Store upload API", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    @app.exception_handler(PublishError)
    async def publication_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=exc.status,
                            headers={"Retry-After": "5"} if exc.status == 503 else None)

    @app.middleware("http")
    async def authenticate(request: Request, call_next):
        try:
            peer = ipaddress.ip_address(request.client.host)
            if isinstance(peer, ipaddress.IPv6Address) and peer.ipv4_mapped:
                peer = peer.ipv4_mapped
        except ValueError:
            return JSONResponse({"detail": "Internal network only"}, status_code=403)
        if not any(peer in network for network in networks):
            return JSONResponse({"detail": "Internal network only"}, status_code=403)
        if request.url.path != "/healthz" and not hmac.compare_digest(request.headers.get("x-api-key", "").encode(), key.encode()):
            return JSONResponse({"detail": "Invalid API key"}, status_code=401)
        return await call_next(request)

    @app.get("/healthz")
    def health():
        repository.state()
        return {"status": "ok"}

    @app.get("/api/v1/apps")
    def apps():
        return repository.state()

    @app.get("/api/v1/apps/{package}")
    def app_info(package: str):
        item = repository.state()["apps"].get(package)
        if item is None:
            raise HTTPException(404, "App not found")
        return item

    @app.post("/api/v1/releases")
    async def upload(request: Request, notes: str = ""):
        if len(notes.encode()) > 8192:
            raise HTTPException(422, "Release notes exceed 8192 bytes")
        if request.headers.get("content-type", "").split(";")[0] not in ("application/vnd.android.package-archive", "application/octet-stream"):
            raise HTTPException(415, "Send raw APK bytes with Content-Type: application/vnd.android.package-archive")
        try:
            content_length = int(request.headers["content-length"]) if "content-length" in request.headers else None
        except ValueError:
            raise HTTPException(400, "Invalid Content-Length")
        if content_length is not None and (content_length < 0 or content_length > max_bytes):
            raise HTTPException(413, "APK exceeds upload limit")
        with repository.lock(blocking=False):
            descriptor, path = tempfile.mkstemp(suffix=".apk", dir=repository.root / "incoming")
            path = Path(path)
            try:
                count = 0
                with os.fdopen(descriptor, "wb") as file:
                    # Bound both the upload's disk usage and lock-holding duration.
                    with anyio.fail_after(300):
                        async for chunk in request.stream():
                            count += len(chunk)
                            if count > max_bytes:
                                raise HTTPException(413, "APK exceeds upload limit")
                            await run_in_threadpool(file.write, chunk)
                    file.flush()
                    os.fsync(file.fileno())
                if not count or (content_length is not None and count != content_length):
                    raise HTTPException(400, "Empty or incomplete APK upload")
                result = await run_in_threadpool(repository.publish, path, notes)
                return JSONResponse(result, status_code=201 if result["status"] == "published" else 200)
            except TimeoutError:
                raise HTTPException(408, "Upload timed out")
            finally:
                path.unlink(missing_ok=True)

    return app


def create_downloads(repository=None):
    repository = repository or repository_from_env()
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/healthz")
    def health():
        repository.state()
        return {"status": "ok"}

    @app.api_route("/fdroid/repo/{name:path}", methods=["GET", "HEAD"])
    def download(name: str):
        try:
            file = repository.open_download(name)
        except (FileNotFoundError, IsADirectoryError):
            raise HTTPException(404, "File not found")
        suffix = Path(name).suffix
        media = {".apk": "application/vnd.android.package-archive", ".jar": "application/java-archive", ".json": "application/json", ".png": "image/png"}.get(suffix, "application/octet-stream")
        return OpenFileResponse(file, media_type=media,
                                headers={"Cache-Control": "public, max-age=31536000, immutable" if suffix == ".apk" else "no-cache"})

    return app
