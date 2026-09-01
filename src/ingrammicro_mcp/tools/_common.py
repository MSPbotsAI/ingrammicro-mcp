from .._json import error_envelope

NO_TOKEN = error_envelope(
    "not_configured",
    "No Ingram Micro credentials. Send the X-IngramMicro-Client-Id, "
    "X-IngramMicro-Client-Secret, X-IngramMicro-Customer-Number, and "
    "X-IngramMicro-Country-Code headers.",
    False,
)
