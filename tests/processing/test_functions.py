import os
import sys
from unittest import mock

import cryptography
import numpy as np
import pytest
from litdata import StreamingDataset, merge_datasets, optimize, walk
from litdata.processing.functions import _get_input_dir, _resolve_dir
from litdata.streaming.cache import Cache
from litdata.utilities.encryption import FernetEncryption, RSAEncryption
from PIL import Image


@pytest.mark.skipif(sys.platform == "win32", reason="currently not supported for windows.")
def test_get_input_dir(tmpdir, monkeypatch):
    monkeypatch.setattr(os.path, "exists", mock.MagicMock(return_value=True))
    assert _get_input_dir(["/teamspace/studios/here/a", "/teamspace/studios/here/b"]) == "/teamspace/studios/here"

    exists_res = [False, True]

    def fn(*_, **__):
        return exists_res.pop(0)

    monkeypatch.setattr(os.path, "exists", fn)

    with pytest.raises(ValueError, match="The provided item  didn't contain any filepaths."):
        assert _get_input_dir(["", "/teamspace/studios/asd/b"])


def test_walk(tmpdir):
    for i in range(5):
        folder_path = os.path.join(tmpdir, str(i))
        os.makedirs(folder_path, exist_ok=True)
        for j in range(5):
            filepath = os.path.join(folder_path, f"{j}.txt")
            with open(filepath, "w") as f:
                f.write("hello world !")

    walks_os = sorted(os.walk(tmpdir))
    walks_function = sorted(walk(tmpdir))
    assert walks_os == walks_function


def test_get_input_dir_with_s3_path():
    input_dir = _get_input_dir(["s3://my_bucket/my_folder/a.txt"])
    assert input_dir == "s3://my_bucket/my_folder"
    input_dir = _resolve_dir(input_dir)
    assert not input_dir.path
    assert input_dir.url == "s3://my_bucket/my_folder"


def compress(index):
    return index, index**2


def different_compress(index):
    return index, index**2, index**3


def fn(i: int):
    if i in [1, 2, 4]:
        raise ValueError("An error occurred")
    return i, i**2


def another_fn(i: int):
    return i, i**2


def random_image(index):
    fake_img = Image.fromarray(np.random.randint(0, 255, (32, 32, 3), dtype=np.uint8))
    return {"image": fake_img, "class": index}


@pytest.mark.skipif(sys.platform == "win32" or sys.platform == "darwin", reason="too slow")
def test_optimize_append_overwrite(tmpdir):
    output_dir = str(tmpdir / "output_dir")

    optimize(
        fn=compress,
        inputs=list(range(5)),
        num_workers=1,
        output_dir=output_dir,
        chunk_bytes="64MB",
    )

    ds = StreamingDataset(output_dir)

    assert len(ds) == 5
    assert ds[:] == [(i, i**2) for i in range(5)]

    with pytest.raises(RuntimeError, match="HINT: If you want to append/overwrite to the existing dataset"):
        optimize(
            fn=compress,
            inputs=list(range(5, 10)),
            num_workers=1,
            output_dir=output_dir,
            chunk_bytes="64MB",
        )

    with pytest.raises(ValueError, match="The provided `mode` should be either `append` or `overwrite`"):
        optimize(
            fn=compress,
            inputs=list(range(5, 10)),
            num_workers=1,
            output_dir=output_dir,
            chunk_bytes="64MB",
            mode="some-random-mode",
        )

    optimize(
        fn=compress,
        inputs=list(range(5, 10)),
        num_workers=2,
        output_dir=output_dir,
        chunk_bytes="64MB",
        mode="overwrite",
    )

    ds = StreamingDataset(output_dir)

    assert len(ds) == 5
    assert ds[:] == [(i, i**2) for i in range(5, 10)]

    optimize(
        fn=compress,
        inputs=list(range(10, 15)),
        num_workers=os.cpu_count(),
        output_dir=output_dir,
        chunk_bytes="64MB",
        mode="append",
    )

    ds = StreamingDataset(output_dir)

    assert len(ds) == 10
    assert ds[:] == [(i, i**2) for i in range(5, 15)]

    optimize(
        fn=compress,
        inputs=list(range(15, 20)),
        num_workers=2,
        output_dir=output_dir,
        chunk_bytes="64MB",
        mode="append",
    )

    ds = StreamingDataset(output_dir)

    assert len(ds) == 15
    assert ds[:] == [(i, i**2) for i in range(5, 20)]

    with pytest.raises(Exception, match="The config isn't consistent between chunks"):
        optimize(
            fn=different_compress,
            inputs=list(range(100, 200)),
            num_workers=1,
            output_dir=output_dir,
            chunk_bytes="64MB",
            mode="append",
        )

    optimize(
        fn=different_compress,
        inputs=list(range(0, 5)),
        num_workers=1,
        output_dir=output_dir,
        chunk_bytes="64MB",
        mode="overwrite",
    )

    ds = StreamingDataset(output_dir)

    assert len(ds) == 5
    assert ds[:] == [(i, i**2, i**3) for i in range(0, 5)]


@pytest.mark.skipif(sys.platform == "win32" or sys.platform == "darwin", reason="too slow")
def test_optimize_checkpoint_in_none_and_append_mode(tmpdir):
    output_dir = str(tmpdir / "output_dir")

    with pytest.raises(RuntimeError, match="We found the following error"):
        optimize(
            fn=fn,
            inputs=list(range(4)),
            output_dir=output_dir,
            chunk_size=1,
            num_workers=2,
            use_checkpoint=True,
        )

    # check that the checkpoints are created
    assert os.path.exists(os.path.join(output_dir, ".checkpoints"))
    assert os.path.exists(os.path.join(output_dir, ".checkpoints", "config.json"))

    optimize(
        fn=another_fn,
        inputs=list(range(4)),
        output_dir=output_dir,
        chunk_size=1,
        num_workers=2,
        use_checkpoint=True,
    )

    ds = StreamingDataset(output_dir)

    assert len(ds) == 4
    assert ds[:] == [(i, i**2) for i in range(4)]
    # checkpoints should be deleted
    assert not os.path.exists(os.path.join(output_dir, ".checkpoints"))

    # --------- now test for append mode ---------

    with pytest.raises(RuntimeError, match="We found the following error"):
        optimize(
            fn=fn,
            inputs=list(range(4, 8)),
            output_dir=output_dir,
            chunk_size=1,
            num_workers=2,
            use_checkpoint=True,
            mode="append",
        )

    # check that the checkpoints are created
    assert os.path.exists(os.path.join(output_dir, ".checkpoints"))
    assert os.path.exists(os.path.join(output_dir, ".checkpoints", "config.json"))
    print("-" * 80)
    # print all the files in the checkpoints folder
    for f in os.listdir(os.path.join(output_dir, ".checkpoints")):
        print(f)
    print("-" * 80)

    optimize(
        fn=another_fn,
        inputs=list(range(4, 8)),
        output_dir=output_dir,
        chunk_size=1,
        num_workers=2,
        use_checkpoint=True,
        mode="append",
    )

    ds = StreamingDataset(output_dir)

    assert len(ds) == 8
    assert ds[:] == [(i, i**2) for i in range(8)]
    # checkpoints should be deleted
    assert not os.path.exists(os.path.join(output_dir, ".checkpoints"))


def test_merge_datasets(tmpdir):
    folder_1 = os.path.join(tmpdir, "folder_1")
    folder_2 = os.path.join(tmpdir, "folder_2")
    folder_3 = os.path.join(tmpdir, "folder_3")

    os.makedirs(folder_1, exist_ok=True)
    os.makedirs(folder_2, exist_ok=True)

    cache_1 = Cache(input_dir=folder_1, chunk_bytes="64MB")
    for i in range(10):
        cache_1[i] = i

    cache_1.done()
    cache_1.merge()

    cache_2 = Cache(input_dir=folder_2, chunk_bytes="64MB")
    for i in range(10, 20):
        cache_2[i] = i

    cache_2.done()
    cache_2.merge()

    merge_datasets(
        input_dirs=[folder_1, folder_2],
        output_dir=folder_3,
    )

    ds = StreamingDataset(input_dir=folder_3)

    assert len(ds) == 20
    assert ds[:] == list(range(20))


@pytest.mark.skipif(sys.platform == "win32", reason="Not tested on windows")
def test_optimize_with_fernet_encryption(tmpdir):
    output_dir = str(tmpdir / "output_dir")

    # ----------------- sample level -----------------
    fernet = FernetEncryption(password="password", level="sample")
    optimize(
        fn=compress,
        inputs=list(range(5)),
        num_workers=1,
        output_dir=output_dir,
        chunk_bytes="64MB",
        encryption=fernet,
    )

    ds = StreamingDataset(output_dir, encryption=fernet)
    assert len(ds) == 5
    assert ds[:] == [(i, i**2) for i in range(5)]

    # ----------------- chunk level -----------------
    fernet = FernetEncryption(password="password", level="chunk")
    optimize(
        fn=compress,
        inputs=list(range(5)),
        num_workers=1,
        output_dir=output_dir,
        chunk_bytes="64MB",
        encryption=fernet,
        mode="overwrite",
    )

    ds = StreamingDataset(output_dir, encryption=fernet)
    assert len(ds) == 5
    assert ds[:] == [(i, i**2) for i in range(5)]

    # ----------------- test with appending more -----------------
    optimize(
        fn=compress,
        inputs=list(range(5, 10)),
        num_workers=1,
        output_dir=output_dir,
        chunk_bytes="64MB",
        encryption=fernet,
        mode="append",
    )
    ds = StreamingDataset(output_dir, encryption=fernet)
    assert len(ds) == 10
    assert ds[:] == [(i, i**2) for i in range(10)]

    # ----------------- decrypt with different conf  -----------------
    ds = StreamingDataset(output_dir)
    with pytest.raises(ValueError, match="Data is encrypted but no encryption object was provided."):
        ds[0]

    fernet.level = "sample"
    ds = StreamingDataset(output_dir, encryption=fernet)
    with pytest.raises(ValueError, match="Encryption level mismatch."):
        ds[0]

    fernet = FernetEncryption(password="password", level="chunk")
    ds = StreamingDataset(output_dir, encryption=fernet)
    with pytest.raises(cryptography.fernet.InvalidToken, match=""):
        ds[0]

    # ----------------- test with other alg -----------------
    rsa = RSAEncryption(password="password", level="sample")
    ds = StreamingDataset(output_dir, encryption=rsa)
    with pytest.raises(ValueError, match="Encryption algorithm mismatch."):
        ds[0]

    # ----------------- test with random images -----------------

    fernet = FernetEncryption(password="password", level="chunk")
    optimize(
        fn=random_image,
        inputs=list(range(5)),
        num_workers=1,
        output_dir=output_dir,
        chunk_bytes="64MB",
        encryption=fernet,
        mode="overwrite",
    )

    ds = StreamingDataset(output_dir, encryption=fernet)

    assert len(ds) == 5
    assert ds[0]["class"] == 0


@pytest.mark.skipif(sys.platform == "win32", reason="Not tested on windows")
def test_optimize_with_rsa_encryption(tmpdir):
    output_dir = str(tmpdir / "output_dir")

    # ----------------- sample level -----------------
    rsa = RSAEncryption(password="password", level="sample")
    optimize(
        fn=compress,
        inputs=list(range(5)),
        num_workers=1,
        output_dir=output_dir,
        chunk_bytes="64MB",
        encryption=rsa,
    )

    ds = StreamingDataset(output_dir, encryption=rsa)
    assert len(ds) == 5
    assert ds[:] == [(i, i**2) for i in range(5)]

    # ----------------- chunk level -----------------
    rsa = RSAEncryption(password="password", level="chunk")
    optimize(
        fn=compress,
        inputs=list(range(5)),
        num_workers=1,
        output_dir=output_dir,
        chunk_bytes="64MB",
        encryption=rsa,
        mode="overwrite",
    )

    ds = StreamingDataset(output_dir, encryption=rsa)
    assert len(ds) == 5
    assert ds[:] == [(i, i**2) for i in range(5)]

    # ----------------- test with appending more -----------------
    optimize(
        fn=compress,
        inputs=list(range(5, 10)),
        num_workers=1,
        output_dir=output_dir,
        chunk_bytes="64MB",
        encryption=rsa,
        mode="append",
    )
    ds = StreamingDataset(output_dir, encryption=rsa)
    assert len(ds) == 10
    assert ds[:] == [(i, i**2) for i in range(10)]

    # ----------------- decrypt with different conf  -----------------
    ds = StreamingDataset(output_dir)
    with pytest.raises(ValueError, match="Data is encrypted but no encryption object was provided."):
        ds[0]

    # ----------------- test with random images  -----------------
    # RSA Encryption throws an error: ValueError: Encryption failed, when trying to encrypt large data
    # optimize(
    #     fn=random_image,
    #     inputs=list(range(5)),
    #     num_workers=1,
    #     output_dir=output_dir,
    #     chunk_bytes="64MB",
    #     encryption=rsa,
    #     mode="overwrite",
    # )
