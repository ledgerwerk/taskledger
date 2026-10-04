# Release checklist

Build Taskledger from the intended release tag or commit in a clean
environment. The artifact version must agree across package metadata, the
imported module, and the CLI before publishing.

```bash
VERSION=0.7.0
python -m build
python -m twine check dist/*
python -m pip install --force-reinstall "dist/taskledger-${VERSION}-"*.whl

test "$(taskledger --version)" = "taskledger ${VERSION}"
test "$(python -c 'import taskledger; print(taskledger.__version__)')" = "${VERSION}"
test "$(python -c 'from importlib.metadata import version; print(version("taskledger"))')" = "${VERSION}"
```

Use a Ledgercore version satisfying the declared dependency range (`>=0.6.1,<0.7.0`). Confirm that the wheel contains `taskledger/py.typed`
and required runtime package files. Run the full test, lint, type, Sphinx,
Documentledger, and SpecMason gates before changing release metadata or
publishing artifacts.
