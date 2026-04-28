"""Approval ledger for HERMY command approvals — STUB.

Currently, approval_id in validate_command() proves only that a non-empty
string was supplied. A durable ledger is needed to prevent replay attacks and
to bind an approval to a specific user, action, and timestamp.

# ROADMAP — intended ledger design:
#
#   1. ApprovalLedger.record(approval_id, action, actor, expires_at):
#      Writes a signed approval entry to a persistent store (file or DB).
#      approval_id must be a UUID or HMAC-signed token.
#
#   2. ApprovalLedger.is_valid(approval_id, action) -> bool:
#      Returns True only if:
#        - approval_id exists in the ledger
#        - The recorded action matches the requested action
#        - The entry has not expired
#        - The entry has not been consumed (single-use approvals)
#
#   3. ApprovalLedger.consume(approval_id):
#      Marks the entry as used so it cannot be replayed.
#
#   4. get_default_ledger():
#      Returns None (no-op) when HERMY_APPROVAL_LEDGER_FILE is not set.
#      Returns a FileApprovalLedger when the env var points to a JSON file.
#
#   5. policy.validate_command should call ledger.is_valid(approval_id, action)
#      when a ledger is configured, and fall back to string-existence check
#      when no ledger is configured (current behaviour, clearly documented).
#
#   Security note: destructive commands must remain blocked even with a valid
#   approval_id. The ledger gates shell control operators only.
"""

from __future__ import annotations


class ApprovalLedger:
    """Durable approval ledger for HERMY command approvals.

    This is a stub. All methods raise NotImplementedError.
    See the ROADMAP comment at the top of this module.
    """

    def record(
        self,
        approval_id: str,
        action: str,
        actor: str | None = None,
    ) -> None:
        """Record a new approval entry."""
        raise NotImplementedError(
            "ApprovalLedger.record is not yet implemented. "
            "See controller/approval_ledger.py ROADMAP."
        )

    def is_valid(self, approval_id: str, action: str | None = None) -> bool:
        """Return True if the approval_id is valid for the given action."""
        raise NotImplementedError(
            "ApprovalLedger.is_valid is not yet implemented. "
            "See controller/approval_ledger.py ROADMAP."
        )

    def consume(self, approval_id: str) -> None:
        """Mark an approval as consumed so it cannot be replayed."""
        raise NotImplementedError(
            "ApprovalLedger.consume is not yet implemented. "
            "See controller/approval_ledger.py ROADMAP."
        )


def get_default_ledger() -> ApprovalLedger | None:
    """Return the configured approval ledger, or None (no-op mode).

    Returns None when HERMY_APPROVAL_LEDGER_FILE is not set, preserving
    current behaviour where approval_id is string-existence only.
    Full ledger support is pending — see ROADMAP in this module.
    """
    return None
