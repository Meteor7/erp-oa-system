# PR #24 Data Consistency and Credential Recovery Design

## Scope

This change resolves exactly two unresolved P1 review findings in PR #24:

1. Reject stale monthly timesheet replacements that would erase another user's newer changes.
2. Preserve recoverable credentials when final credential-file publication fails after password resets commit.

The other six P1 findings are tracked separately in issues #25 through #30 and are not part of this implementation.

## Monthly timesheet consistency

The existing save path already serializes writes for one employee by locking the stable Employee row with `for_update=True`. The missing contract is an optimistic revision check: a client that loaded an older monthly snapshot can still replace the newly committed snapshot after it acquires the lock.

For a selected employee and period, the list API will return an opaque `revision` derived from a sorted snapshot of every active generated Timesheet document, including document name, monthly entry ID, and modification timestamp. An empty month will also have a deterministic non-empty revision. The all-employees read-only view will not expose a save revision.

The frontend will retain the revision loaded with the editable rows and submit it as `expected_revision`. The save API will accept the argument with a default of `None` for transport compatibility, but will explicitly reject a missing value with a refresh instruction so an old or stale frontend cannot bypass the guard.

After acquiring the Employee row lock, the save API will recompute the revision. A mismatch will fail before any deletion. A match will preserve the current replace-all behavior, including intentional row deletion. The existing duplicate-ID and employee-period ownership checks remain in place; the revision check does not replace them. The separate delete endpoint already uses the same Employee lock and its returned list response will contain the new revision, causing any older full-form save to be rejected.

Tests will cover deterministic empty and populated revisions, token changes after additions or edits, stale-save rejection before replacement, successful save with the current token, intentional deletion with the current token, explicit rejection of a missing token, and the frontend request contract. The production frontend build must be refreshed because the request payload changes.

## Credential delivery recovery

The current implementation commits password changes before publishing the credential CSV and then deletes the pending CSV when publication fails. Rollback cannot restore committed passwords, so all reset accounts can become unrecoverable.

Publishing the final CSV before the database commit is also unsafe: a commit failure would leave a final-looking credential file whose passwords are not active, and it could overwrite an older valid delivery. The implementation will therefore use the existing private pending file as a durable recovery journal.

The revised operation will:

1. Validate that the output remains under the site private directory and reject a directory target before changing passwords.
2. Create the deterministic `.pending` CSV with exclusive creation, then flush, fsync, and chmod it to `0600`. If a prior pending recovery exists, abort before changing passwords rather than overwrite it.
3. Apply password changes inside the uncommitted database transaction.
4. Commit the database transaction.
5. Atomically replace the final output with the already durable and private pending CSV. Because the pending file is already `0600`, no post-publication chmod is required.

The implementation will track whether commit succeeded. Failures before commit roll back the database and leave the pending artifact for diagnosis. Failures after commit do not pretend rollback can undo the reset and must leave the pending artifact untouched as the authoritative recovery delivery. A successful atomic replace removes the pending pathname and makes the same bytes available at the final output path.

Frappe v15's `update_password` writes through the current database transaction and does not commit internally, so the explicit commit boundary remains authoritative.

Tests will inject password-update failure, database-commit failure, and final-publication failure. They will assert ordering, rollback only before commit, no overwrite of an existing pending recovery, retention of credentials on every failure path, and successful publication with private permissions.

## Delivery

Implementation will be limited to the monthly timesheet backend, its frontend caller and production build output, the credential-delivery utility, and focused tests. The resulting commits will be pushed to `feat/ocr-monthly-timesheet-integration`, the existing PR #24 head branch.
