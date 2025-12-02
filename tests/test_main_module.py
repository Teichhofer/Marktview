import importlib
import runpy
import sys
from types import SimpleNamespace


def test_main_module_executes(monkeypatch):
    called = {}
    monkeypatch.setattr("marktview.cli.main", lambda: called.setdefault("called", True))
    monkeypatch.setattr("sys.argv", ["python"])
    runpy.run_module("marktview.__main__", run_name="__main__")
    assert called["called"] is True


def test_main_module_importable():
    module = importlib.import_module("marktview.__main__")
    assert hasattr(module, "main")
