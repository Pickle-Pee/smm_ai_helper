"""Safe application failures; programming defects are not caught wholesale."""
class CopilotAPIError(Exception):
    def __init__(self, status, code, *, owned_site=None):
        super().__init__(code)
        self.status, self.code, self.owned_site = status, code, owned_site


class ProviderUnavailable(CopilotAPIError):
    def __init__(self):
        super().__init__(503, "temporarily_unavailable")
