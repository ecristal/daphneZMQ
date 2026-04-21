from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable


def _candidate_build_dirs(repo_root: Path) -> Iterable[Path]:
    env_build = os.environ.get("DAPHNE_BUILD_DIR")
    if env_build:
        yield Path(env_build)

    for name in (
        "build-client",
        "build-test",
        "build-petalinux",
        "build",
        "build-local",
        "build-local2",
        "build-local3",
    ):
        yield repo_root / name


def _add_build_pb2_to_package_path() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    for build_dir in _candidate_build_dirs(repo_root):
        pb2_dir = build_dir / "srcs" / "protobuf"
        if (pb2_dir / "daphneV3_high_level_confs_pb2.py").is_file():
            if str(pb2_dir) not in __path__:
                __path__.append(str(pb2_dir))
            return


_add_build_pb2_to_package_path()

