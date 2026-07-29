# PR #24 Data Consistency and Credential Recovery Design

## Scope

This change resolves exactly two unresolved P1 review findings in PR #24:

1. Reject stale monthly timesheet replacements that would erase another user's newer changes.
2. Prevent committed password resets from becoming unrecoverable when credential-file publication fails.

The other six P1 findings are tracked separately in issues #25 through #30 and are not part of this implementation.

## Monthly timesheet consistency

The existing save path already serializes writes for one employee by locking the stable Employee row with `for_update=True`. The missing contract is an optimistic revision check: a client that loaded an older monthly snapshot can still replace the newly committed snapshot after it acquires the lock.

The list API will return an opaque `revision` derived from the complete current generated Timesheet snapshot for the selected employee and period. The token will include stable document identity and modification state so additions, deletions, and edits all produce a new revision. The frontend will retain the loaded revision and submit it as `expected_revision` with the replacement payload.

After acquiring the Employee row lock, the save API will recompute the current revision and compare it with `expected_revision`. A mismatch will fail before deleting any Timesheet document and instruct the user to reload. A matching revision will preserve the current replace-all behavior, including intentional row deletion. Calls that omit `expected_revision` will be rejected for editable single-employee saves so stale clients cannot bypass the guard.

Tests will cover token stability, token changes after a snapshot change, stale-save rejection before replacement, successful saves with the current token, intentional deletion with the current token, and the frontend request contract.

## Credential delivery recovery

The current implementation commits password changes before atomically publishing the credential CSV. If publication then fails, rollback cannot restore committed passwords and the exception handler deletes the only recovery artifact.

The revised operation will:

1. Validate the private output target and reject directory targets before changing passwords.
2. Write, flush, fsync, and chmod the private pending CSV.
3. Apply password changes inside the uncommitted database transaction.
4. Atomically publish and chmod the credential CSV.
5. Commit the database transaction only after publication succeeds.

On any exception, the database transaction will roll back. The private pending or published credential artifact will not be deleted by the exception handler, preserving operator recovery evidence. No file operation that can strand credentials will run after a successful database commit.

Tests will inject publication failure and commit failure, assert that commit never precedes publication, assert rollback occurs, and assert the recovery artifact remains available.

## Delivery

Implementation will be limited to the monthly timesheet backend, its frontend caller, the credential-delivery utility, and their focused tests. The resulting commits will be pushed to `feat/ocr-monthly-timesheet-integration`, the existing PR #24 head branch.

