# Contributing

pgheat is currently specifying its behavior before implementation. Design
contributions should preserve these constraints:

- Findings must be explainable from recorded evidence.
- Counter resets and missing samples must be represented explicitly.
- Read, write, recency, and cache signals must not be collapsed prematurely.
- The default operating mode must be read-only.
- PostgreSQL version assumptions must be documented and tested.

## Proposing a change

Open an issue describing:

1. The operator problem.
2. The PostgreSQL evidence available to solve it.
3. Failure modes and possible false conclusions.
4. How the behavior can be tested reproducibly.

Architecture changes should include an ADR under `docs/decisions/`.

## Development

Build and test commands will be added when the implementation language and
project structure are introduced. Do not add placeholder dependencies or CI
workflows before they execute real checks.
