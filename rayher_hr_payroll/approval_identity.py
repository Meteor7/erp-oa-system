"""Authorization identities are User IDs, never mutable display names."""


def approval_actor_ids(user):
    # The caller supplies the authenticated User.name (or an explicit User ID).
    # Employee IDs and names belong to separate namespaces and are not aliases.
    user_id = str(user or "").strip()
    return {user_id} if user_id and user_id != "Guest" else set()
