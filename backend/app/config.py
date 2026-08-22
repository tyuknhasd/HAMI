import os
import secrets


class Settings:
    # --- General ---
    PROJECT_NAME: str = "HAMI"
    PORT: int = int(os.getenv("PORT", 8000))

    # --- Security ---
    SECRET_KEY: str = os.getenv("SECRET_KEY") or secrets.token_hex(32)
    ADMIN_USERNAME: str = os.getenv("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "123456")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    # --- Database ---
    # Railway injects DATABASE_URL automatically when you attach a Postgres plugin.
    # Falls back to a local sqlite file for quick local testing.
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./hami.db")

    # --- Public domain (used to build client links) ---
    PUBLIC_DOMAIN: str = (
        os.getenv("PUBLIC_DOMAIN")
        or os.getenv("RAILWAY_PUBLIC_DOMAIN")
        or "localhost"
    )
    PUBLIC_PORT: int = int(os.getenv("PUBLIC_PORT", 443))
    WORKER_SNI: str = os.getenv("WORKER_SNI", "")
    SUB_DOMAIN: str = os.getenv("SUB_DOMAIN", "")

    # --- Xray ---
    XRAY_BIN: str = os.getenv("XRAY_BIN", "/usr/local/bin/xray")
    XRAY_CONFIG_PATH: str = os.getenv("XRAY_CONFIG_PATH", "/etc/xray/config.json")
    XRAY_API_PORT: int = int(os.getenv("XRAY_API_PORT", 10085))
    REALITY_PRIVATE_KEY: str = os.getenv("REALITY_PRIVATE_KEY", "")
    REALITY_PUBLIC_KEY: str = os.getenv("REALITY_PUBLIC_KEY", "")
    REALITY_SHORT_ID: str = os.getenv("REALITY_SHORT_ID", "")
    REALITY_DEST: str = os.getenv("REALITY_DEST", "www.microsoft.com:443")
    REALITY_SERVER_NAMES: str = os.getenv("REALITY_SERVER_NAMES", "www.microsoft.com")

    # --- MTProto (mtg sidecar) ---
    MTG_SECRET: str = os.getenv("MTG_SECRET", "")
    MTG_PORT: int = int(os.getenv("MTG_PORT", 3128))
    MTG_ADTAG: str = os.getenv("MTG_ADTAG", "")  # sponsor channel tag from @MTProxybot
    MTG_CONFIG_PATH: str = os.getenv("MTG_CONFIG_PATH", "/etc/mtg/secrets.toml")

    # --- Telegram bot (optional) ---
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_ADMIN_IDS: str = os.getenv("TELEGRAM_ADMIN_IDS", "")


settings = Settings()
