"""Original files, kept by the SHA-256 of their bytes so any figure can be traced back to its file."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol

import gridfs
from gridfs import GridFSBucket
from pymongo.database import Database

from ledgersync.errors import NotFound


@dataclass(frozen=True)
class Blob:
    """One kept file: its bytes, the name it was uploaded under and its content type."""

    data: bytes
    name: str
    content_type: str


class BlobStore(Protocol):
    """Where original files are kept. The blob ID is the SHA-256 hex of the bytes."""

    def put(self, data: bytes, *, name: str, content_type: str) -> str:
        """Keeps the file and returns its blob ID; bytes already kept are not stored again."""

    def get(self, blob_id: str) -> Blob:
        """The kept file, or NotFound."""

    def exists(self, blob_id: str) -> bool:
        """Whether a file with this blob ID is kept."""


class MemoryBlobStore:
    """Files kept in memory, for tests and for runs without MongoDB (they last until a restart)."""

    def __init__(self):
        self._blobs: dict[str, Blob] = {}

    def put(self, data: bytes, *, name: str, content_type: str) -> str:
        blob_id = hashlib.sha256(data).hexdigest()
        self._blobs.setdefault(blob_id, Blob(data, name, content_type))
        return blob_id

    def get(self, blob_id: str) -> Blob:
        try:
            return self._blobs[blob_id]
        except KeyError:
            raise NotFound("That file isn't kept.") from None

    def exists(self, blob_id: str) -> bool:
        return blob_id in self._blobs


class GridFSBlobStore:
    """Files kept in the MongoDB database's `blobs` GridFS bucket, with the blob ID as the file's _id."""

    def __init__(self, db: Database):
        self._bucket = GridFSBucket(db, bucket_name="blobs")
        self._files = db["blobs.files"]

    def put(self, data: bytes, *, name: str, content_type: str) -> str:
        blob_id = hashlib.sha256(data).hexdigest()
        if not self.exists(blob_id):
            try:
                self._bucket.upload_from_stream_with_id(
                    blob_id, name, data, metadata={"name": name, "content_type": content_type})
            except gridfs.errors.FileExists:   # a parallel upload of the same bytes won the race
                pass
        return blob_id

    def get(self, blob_id: str) -> Blob:
        try:
            stream = self._bucket.open_download_stream(blob_id)
        except gridfs.errors.NoFile:
            raise NotFound("That file isn't kept.") from None
        meta = stream.metadata or {}
        return Blob(stream.read(), meta.get("name", stream.filename), meta.get("content_type", "application/octet-stream"))

    def exists(self, blob_id: str) -> bool:
        return self._files.count_documents({"_id": blob_id}, limit=1) > 0
