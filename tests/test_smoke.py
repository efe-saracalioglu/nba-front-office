import importlib

import pytest


@pytest.mark.parametrize(
    "package", ["rules", "models", "mcp_server", "agents", "data", "evals", "app"]
)
def test_packages_import(package):
    importlib.import_module(package)
