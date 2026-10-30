# Decision 0002: Local persistence model

## Status

Approved by the owner on 2026-10-26. Schema implementation may proceed within this decision's scope.

## Context

The MVP holds project/session content only in process memory, but the approved initial-release contract requires durable projects and resumable workflow state in local PostgreSQL. The release remains single-user and localhost-only; project data is retained until explicit deletion.

## Decision

1. Use one local workspace as the ownership scope. Do not introduce user accounts or multi-user authorization in the initial release; every project repository query still filters by workspace and project.
2. Store project mutations as immutable, monotonically numbered revisions with an optimistic-concurrency pointer on the project.
3. Store user text once in project-scoped source records and reference it from revisions, answers, facts, decisions, and requirements. Do not place idea text or answer bodies in operational events or audit metadata.
4. Store generated documents as immutable content/hash revisions. Bind validation reports and export metadata to exact document revisions and hashes. Do not persist ZIP bytes by default.
5. Delete projects by hard deletion with database-level cascades. Do not retain a `deleted_at` project row; keep only content-minimal audit metadata that cannot recreate project content.
6. Use SQLAlchemy 2.x asynchronous persistence and explicit Alembic migrations. Application startup does not create schema or silently fall back to in-memory storage.
7. Add LangGraph checkpoint data in its own schema in Phase 5. The project-delete workflow must prove checkpoint cleanup before reporting deletion complete.

## Consequences

- The ERD, table responsibilities, transaction boundaries, indexes, and migration order are documented in `docs/DATA_MODEL_AND_MIGRATIONS.md`.
- The current process-memory MVP has no durable project data to migrate; persistent implementation changes the old no-disk-storage behavior and must be disclosed to users.
- Hard deletion is consistent with the Phase 0 contract but cannot promise forensic erasure from PostgreSQL host storage.
- PostgreSQL volume files rely on the user's local device/disk protection; Context OS does not provide at-rest encryption or a backup/restore guarantee.
- Public/multi-user deployment remains blocked pending separate authentication, authorization, privacy, and security decisions.

## Revisit when

The owner changes the single-user boundary, deletion/retention policy, storage platform, or deployment target. Any change requires coordinated updates to the product, API, privacy, migration, and acceptance contracts.
