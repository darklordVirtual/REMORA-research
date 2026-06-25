# Author: Stian Skogbrott
# License: Apache-2.0
"""Azure Blob Storage adapter for REMORA.

Requirements:
    pip install azure-storage-blob azure-identity
"""
from __future__ import annotations

from remora.adapters.storage import StorageAdapter


class AzureBlobStorage(StorageAdapter):
    """Store artifacts in Azure Blob Storage.

    Parameters
    ----------
    account_url:
        Storage account URL (e.g. https://myaccount.blob.core.windows.net).
    container:
        Blob container name.
    credential:
        Azure credential (connection string, SAS token, or None for DefaultAzureCredential).
    """

    def __init__(self, account_url: str, container: str, credential: str | None = None):
        self._account_url = account_url
        self._container = container
        self._credential = credential

    def _client(self):
        from azure.storage.blob import ContainerClient

        if self._credential:
            return ContainerClient(self._account_url, self._container, credential=self._credential)
        from azure.identity import DefaultAzureCredential
        return ContainerClient(self._account_url, self._container, credential=DefaultAzureCredential())

    def put(self, key: str, data: bytes) -> None:
        self._client().upload_blob(key, data, overwrite=True)

    def get(self, key: str) -> bytes | None:
        try:
            return self._client().download_blob(key).readall()
        except Exception:
            return None

    def exists(self, key: str) -> bool:
        try:
            self._client().get_blob_properties(key)
            return True
        except Exception:
            return False

    def list_keys(self, prefix: str = "") -> list[str]:
        return sorted(b.name for b in self._client().list_blobs(name_starts_with=prefix))
