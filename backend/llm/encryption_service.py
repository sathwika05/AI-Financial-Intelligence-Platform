from cryptography.fernet import Fernet, InvalidToken

from backend.config import settings


class EncryptionService:
    def __init__(self) -> None:
        self._fernet = Fernet(
            settings.LLM_KEY_ENCRYPTION_SECRET.encode()
        )

    def encrypt(self, value: str) -> str:
        if not value:
            raise ValueError("API key cannot be empty")

        return self._fernet.encrypt(
            value.encode()
        ).decode()

    def decrypt(self, encrypted_value: str) -> str:
        if not encrypted_value:
            raise ValueError("Encrypted API key is missing")

        try:
            return self._fernet.decrypt(
                encrypted_value.encode()
            ).decode()
        except InvalidToken as exc:
            raise ValueError(
                "Unable to decrypt provider API key"
            ) from exc


encryption_service = EncryptionService()