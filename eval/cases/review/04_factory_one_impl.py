"""Sample review case: over-engineering (OE-1 + OE-6).

A Factory with one concrete implementer and an interface that no
second class implements. Classic over-engineering for the sake of
"future-proofing" with no second impl in sight.

EXPECTED: `/dev-kit:review` MUST flag at least one `architecture` major
finding (factory with one implementer; abstract base class with one
concrete).
"""
from abc import ABC, abstractmethod


class StorageBackend(ABC):
    @abstractmethod
    def put(self, key: str, value: bytes) -> None: ...

    @abstractmethod
    def get(self, key: str) -> bytes: ...


class S3Backend(StorageBackend):
    def __init__(self, bucket: str):
        self._bucket = bucket

    def put(self, key: str, value: bytes) -> None:
        # real S3 put logic
        ...

    def get(self, key: str) -> bytes:
        # real S3 get logic
        ...


def make_storage() -> StorageBackend:
    return S3Backend(bucket="prod")
