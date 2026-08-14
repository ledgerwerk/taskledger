# Release checklist

Build Taskledger from the intended release tag or commit in a clean
environment. The artifact version must agree across package metadata, the
imported module, and the CLI before publishing.

```bash
python -m build
python -m twine check dist/*
python -m pip install --force-reinstall dist/taskledger-0.6.1-*.whl
taskledger --version
python -c 'import taskledger; print(taskledger.__version__)'
python -c 'from importlib.metadata import version; print(version("taskledger"))'
```

The clean environment must contain Ledgercore 0.6.1, and all three version
checks must report `0.6.1`. Confirm that the wheel contains `taskledger/py.typed`
and required runtime package files. Run the full test, lint, type, Sphinx,
Documentledger, and SpecMason gates before changing release metadata or
publishing artifacts.
