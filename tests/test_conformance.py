"""Conformance tests for hermes-infisical-source.

Subclase el kit oficial de Hermes (tests/secret_sources/conformance.py) —
verde en estos checks es el barómetro de contrato-compliant para un secret source.
Ejecutar desde el repo del harness:
    PYTHONPATH=<este-repo> pytest tests/test_conformance.py
"""
import importlib.util
import pathlib

import pytest

from tests.secret_sources.conformance import SecretSourceConformance

_PLUGIN = pathlib.Path(__file__).resolve().parent.parent / "__init__.py"


def _load_source():
    spec = importlib.util.spec_from_file_location("hermes_infisical", _PLUGIN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.InfisicalSource()


class TestInfisicalConformance(SecretSourceConformance):
    @pytest.fixture
    def source(self):
        return _load_source()
