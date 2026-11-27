from __future__ import annotations

import hashlib
import importlib

from taskledger import api
from taskledger.command_inventory import COMMAND_METADATA


def _digest(values: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(values)).encode()).hexdigest()


def test_v0_7_8_command_names_are_frozen_before_cleanup() -> None:
    command_names = list(COMMAND_METADATA)

    assert len(command_names) == 207
    assert len({command.split()[0] for command in command_names}) == 47
    assert _digest(command_names) == (
        "67d352f66004a0cef3e88686afa192595e12acedc88a03d6b521692e860bfc45"
    )


def test_v0_7_8_public_api_exports_are_frozen_before_cleanup() -> None:
    exports = [
        f"{module_name}.{export_name}"
        for module_name in api.__all__
        for export_name in getattr(
            importlib.import_module(f"taskledger.api.{module_name}"), "__all__", []
        )
    ]

    assert len(api.__all__) == 15
    assert len(exports) == 156
    assert _digest(exports) == (
        "4d57fba54baf53e8cf4a90c7e41504f7bbcc3b87167e1f4b25e2131e20e26e1c"
    )
