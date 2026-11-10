# ADR-0004: One canonical Test Document (pydantic) and immutable revisions

- **Status:** Proposed (2026-11-10)
- **Related:** plan.md §3, §8, §11 · KT-102–KT-108, KT-301, KT-401, KT-706

## Context

Tests need to be imported and exported as JSON that an LLM can write reliably. Published tests must never change under existing results. Grading should be deterministic and safe to re-run. Without a single format we'd end up maintaining four representations: editor models, export JSON, published snapshots and grading input.

## Decision

- Define the **Test Document v1** once, as **pydantic v2** models with a discriminated union on the question `type`. They're plain Python with no Django imports, in `apps/exchange/document.py`.
- The same models provide:
  - import validation, with semantic checks and a readable report
  - export
  - the JSON Schema (`manage.py export_schema` → `schema/test.v1.schema.json`, generated and never hand-edited)
  - validation of LLM output
- The **editor** works on relational models (Project, Assessment, Question, Option), because that's the most natural fit for Django forms. Serializers convert in both directions, and round-trip tests guard them.
- **Publishing** freezes the test into an immutable `Revision` that stores the validated Test Document and its sha256 hash. Sessions and attempts point to revisions. Editing a published test creates a draft, and republishing creates the next revision.
- **Grading** is pure functions over `(TestDocument, answers)`.

## Consequences

- **Easier:** one schema to document and test. Old results always render exactly as they were taken. Regrading after an answer-key fix is a controlled operation (new revision, regrade the chosen attempts). LLM and import paths reuse all validation.
- **Harder:** serializers must keep the relational editor and the document in sync, which round-trip tests cover. Schema changes need a version policy (plan §11.6).
- **Commitment:** exports are always canonical. Imports are lenient: unknown fields produce warnings and missing ids are generated.

## Alternatives considered

- **Storing tests only as JSON documents, with no Question/Option tables:** a simpler model, but form-based editing and per-field validation get awkward in Django.
- **Snapshotting questions into each attempt:** duplicates data per taker and complicates regrading.
- **Hand-written JSON Schema with the jsonschema library:** two sources of truth (schema and code) that drift apart.
