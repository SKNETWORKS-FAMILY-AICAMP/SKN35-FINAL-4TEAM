"""Expected read failures may carry the engine's tool_error marker."""


def expected_read_error(span, reply):
    # The caller must also match the replayed result and arguments exactly.
    return (span.get("error") == "tool_error" and isinstance(reply, dict)
            and reply.get("ok") is False
            and reply.get("error") in {"temporary_unavailable", "permission_denied"})
