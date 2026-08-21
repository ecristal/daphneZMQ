"""Locate generated Python protobuf modules without assuming a build folder."""

import importlib
import os
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_protobuf_modules(require_trigger_source=False):
    candidates = []
    configured = os.environ.get("DAPHNE_PROTO_PYTHON_DIR")
    if configured:
        candidates.append(Path(configured))
    configured_build = os.environ.get("DAPHNE_BUILD_DIR")
    if configured_build:
        candidates.append(Path(configured_build) / "srcs" / "protobuf")
    for build_name in ("build-petalinux", "build-client", "build-test", "build"):
        candidates.append(REPO_ROOT / build_name / "srcs" / "protobuf")
    candidates.append(REPO_ROOT / "srcs" / "protobuf")

    visited = set()
    errors = []
    for candidate in candidates:
        candidate = candidate.expanduser().resolve()
        if candidate in visited:
            continue
        visited.add(candidate)
        if not all(
            (candidate / filename).is_file()
            for filename in (
                "daphneV3_high_level_confs_pb2.py",
                "daphneV3_low_level_confs_pb2.py",
            )
        ):
            continue

        high_name = "daphneV3_high_level_confs_pb2"
        low_name = "daphneV3_low_level_confs_pb2"
        sys.modules.pop(high_name, None)
        sys.modules.pop(low_name, None)
        sys.path.insert(0, str(candidate))
        try:
            high = importlib.import_module(high_name)
            low = importlib.import_module(low_name)
        except Exception as exc:
            errors.append(f"{candidate}: {exc}")
            continue
        finally:
            sys.path.pop(0)

        if require_trigger_source and not all(
            hasattr(high, name)
            for name in (
                "SPY_TRIGGER_SOURCE_LEGACY_ALL",
                "WriteSpyBufferTriggerSourceRequest",
                "ReadSpyBufferTriggerSourceRequest",
                "MT2_WRITE_SPYBUFFER_TRIGGER_SOURCE_REQ",
                "MT2_READ_SPYBUFFER_TRIGGER_SOURCE_REQ",
            )
        ):
            errors.append(f"{candidate}: trigger-source schema is out of date")
            continue
        return high, low

    detail = "; ".join(errors)
    if detail:
        detail = " Checked: " + detail
    raise RuntimeError(
        "Compatible Python protobuf bindings were not found. Rebuild the "
        "project or set DAPHNE_PROTO_PYTHON_DIR." + detail
    )
