import sys
from types import ModuleType
from unittest.mock import Mock

import pytest
import torch.distributed


@pytest.fixture(autouse=True)
def teardown_process_group():  # noqa: PT004
    """Ensures that the distributed process group gets closed before the next test runs."""
    yield
    if torch.distributed.is_available() and torch.distributed.is_initialized():
        torch.distributed.destroy_process_group()


@pytest.fixture()
def mosaic_mds_index_data():
    return {
        "shards": [
            {
                "column_encodings": ["int", "jpeg"],
                "column_names": ["class", "image"],
                "column_sizes": [8, None],
                "compression": "zstd",
                "format": "mds",
                "hashes": [],
                "raw_data": {"basename": "shard.00000.mds", "bytes": 125824, "hashes": {}},
                "samples": 100,
                "size_limit": 67108864,
                "version": 2,
                "zip_data": {"basename": "shard.00000.mds.zstd", "bytes": 63407, "hashes": {}},
            }
        ],
        "version": 2,
    }


@pytest.fixture()
def google_mock(monkeypatch):
    google = ModuleType("google")
    monkeypatch.setitem(sys.modules, "google", google)
    google_cloud = ModuleType("cloud")
    monkeypatch.setitem(sys.modules, "google.cloud", google_cloud)
    google_cloud_storage = ModuleType("storage")
    monkeypatch.setitem(sys.modules, "google.cloud.storage", google_cloud_storage)
    google.cloud = google_cloud
    google.cloud.storage = google_cloud_storage
    return google


@pytest.fixture()
def lightning_cloud_mock(monkeypatch):
    lightning_cloud = ModuleType("lightning_cloud")
    monkeypatch.setitem(sys.modules, "lightning_cloud", lightning_cloud)
    rest_client = ModuleType("rest_client")
    monkeypatch.setitem(sys.modules, "lightning_cloud.rest_client", rest_client)
    lightning_cloud.rest_client = rest_client
    rest_client.LightningClient = Mock()
    return lightning_cloud


@pytest.fixture()
def lightning_sdk_mock(monkeypatch):
    lightning_sdk = ModuleType("lightning_sdk")
    monkeypatch.setitem(sys.modules, "lightning_sdk", lightning_sdk)
    return lightning_sdk
