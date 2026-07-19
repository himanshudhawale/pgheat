# Releasing

pgheat publishes standard Python source and wheel distributions.

## One-time PyPI setup

The `pgheat` project name is available on PyPI as of 2026-07-18. Before the
first upload, configure a pending Trusted Publisher in the PyPI account that
will own the project:

| Setting | Value |
| --- | --- |
| PyPI project name | `pgheat` |
| GitHub owner | `himanshudhawale` |
| GitHub repository | `pgheat` |
| Workflow | `publish.yml` |
| Environment | `pypi` |

Trusted Publishing uses GitHub's short-lived OpenID Connect identity. Do not
create or store a long-lived PyPI API token in the repository.

## Release process

1. Update `project.version` in `pyproject.toml`.
2. Confirm the version does not already exist on PyPI.
3. Build the source and wheel distributions.
4. Create a GitHub release tagged `v<version>`.
5. Run the **Publish Python package** workflow for that tag.
6. Confirm installation from PyPI in a clean environment.

The publishing workflow targets the protected GitHub environment named
`pypi`. Configure required reviewers on that environment if release approval
is desired.

## Local package build

```shell
python -m pip install build twine
python -m build
python -m twine check dist/*
```

Build artifacts are written to `dist/`, which is excluded from Git.
