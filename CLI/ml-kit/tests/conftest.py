# -*- coding: utf-8 -*-
"""ml-kit test setup: keep the error log (R6) out of the real tool folder.

Every failing CLI call in the tests would otherwise append to <tool folder>/data/logs/errors.txt.
ML_KIT_DATA_DIR is set for the whole session; subprocesses spawned by the tests inherit it.
"""
import os

import pytest


@pytest.fixture(scope="session", autouse=True)
def _mlkit_data_dir(tmp_path_factory):
    old = os.environ.get("ML_KIT_DATA_DIR")
    os.environ["ML_KIT_DATA_DIR"] = str(tmp_path_factory.mktemp("mlkit_data"))
    yield os.environ["ML_KIT_DATA_DIR"]
    if old is None:
        os.environ.pop("ML_KIT_DATA_DIR", None)
    else:
        os.environ["ML_KIT_DATA_DIR"] = old
