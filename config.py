import os
from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing environment variable: {name} (check your .env file)")
    return value


class Settings:
    storage_conn = _require("AZURE_STORAGE_CONNECTION_STRING")
    storage_container = _require("AZURE_STORAGE_CONTAINER")

    search_endpoint = _require("AZURE_SEARCH_ENDPOINT")
    search_key = _require("AZURE_SEARCH_KEY")
    search_index = _require("AZURE_SEARCH_INDEX")

    openai_endpoint = _require("AZURE_OPENAI_ENDPOINT")
    openai_key = _require("AZURE_OPENAI_KEY")
    openai_api_version = _require("AZURE_OPENAI_API_VERSION")
    chat_deployment = _require("AZURE_OPENAI_CHAT_DEPLOYMENT")
    embedding_deployment = _require("AZURE_OPENAI_EMBEDDING_DEPLOYMENT")


settings = Settings()