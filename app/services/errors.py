class NotFound(Exception):
    pass


class AgentUnavailable(Exception):
    """The configured LLM provider could not complete the request.

    Only reachable with LLM_PROVIDER=anthropic -- the stub never raises this,
    which is exactly why it took real network calls to need it.
    """
