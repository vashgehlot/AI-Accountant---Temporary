import hashlib

import pytest

from ledgersync.blobs import Blob, GridFSBlobStore, MemoryBlobStore
from ledgersync.errors import NotFound


@pytest.fixture(params=[pytest.param("memory"), pytest.param("gridfs", marks=pytest.mark.mongo)])
def blobs(request):
    """The same tests on the in-memory store and on GridFS (skipped when MongoDB isn't configured)."""
    if request.param == "memory":
        return MemoryBlobStore()
    return GridFSBlobStore(request.getfixturevalue("mongo_db"))


def test_put_returns_the_sha256_and_get_returns_the_same_file(blobs):
    blob_id = blobs.put(b"hello", name="a.txt", content_type="text/plain")
    assert blob_id == hashlib.sha256(b"hello").hexdigest()
    assert blobs.get(blob_id) == Blob(b"hello", "a.txt", "text/plain")
    assert blobs.exists(blob_id)


def test_the_same_bytes_twice_are_kept_once(blobs):
    first = blobs.put(b"x", name="a.csv", content_type="text/csv")
    assert blobs.put(b"x", name="b.csv", content_type="text/csv") == first
    assert blobs.get(first).name == "a.csv"


def test_an_unknown_blob_is_not_found(blobs):
    assert not blobs.exists("0" * 64)
    with pytest.raises(NotFound):
        blobs.get("0" * 64)
