from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException


@dataclass
class AppError(Exception):
    code: str
    message: str
    details: Any = None
    status_code: int = 400

    def to_payload(self) -> dict[str, Any]:
        return {
            "success": False,
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
            },
        }


def http_error(error: AppError) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail=error.to_payload())

