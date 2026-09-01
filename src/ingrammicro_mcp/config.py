from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Transport
    mcp_transport: Literal["stdio", "http"] = "stdio"
    mcp_http_port: int = 8080
    mcp_http_host: str = "0.0.0.0"

    # Auth mode:
    # "gateway" — production/SOP-compliant: credentials from HTTP headers per request (no global state)
    # "env"     — local dev only: shared credentials from env vars (not SOP-compliant)
    auth_mode: Literal["env", "gateway"] = "gateway"

    # Ingram Micro credentials (only required in env mode)
    ingrammicro_client_id: str | None = None
    ingrammicro_client_secret: str | None = None
    ingrammicro_customer_number: str | None = None
    ingrammicro_country_code: str | None = None

    # HTTP header names used to pass credentials in gateway mode.
    # The client must include all four headers on every /mcp request.
    ingrammicro_client_id_header: str = "X-IngramMicro-Client-Id"
    ingrammicro_client_secret_header: str = "X-IngramMicro-Client-Secret"
    ingrammicro_customer_number_header: str = "X-IngramMicro-Customer-Number"
    ingrammicro_country_code_header: str = "X-IngramMicro-Country-Code"

    # Identifies this integration to Ingram Micro as the calling system
    # (IM-SenderID header) — not tenant-specific credential material, so
    # it's a fixed setting rather than something each gateway request supplies.
    ingrammicro_sender_id: str = "MSPbots"

    # Ingram Micro's own sandbox/production distinction is a base-URL swap,
    # not a separate credential — override for sandbox testing.
    ingrammicro_base_url: str = "https://api.ingrammicro.com"

    @property
    def has_credentials(self) -> bool:
        """Returns True if the server can serve API calls.

        Gateway mode always returns True — each request carries its own credentials.
        Env mode requires all four Ingram Micro settings to be set.
        """
        if self.auth_mode == "gateway":
            return True
        return all(
            [
                self.ingrammicro_client_id,
                self.ingrammicro_client_secret,
                self.ingrammicro_customer_number,
                self.ingrammicro_country_code,
            ]
        )


def get_settings() -> Settings:
    return Settings()
