from fastapi import HTTPException


def not_found(resource: str = "Resource") -> None:
    """404 Not Found 발생"""
    raise HTTPException(status_code=404, detail=f"{resource} not found")


def forbidden(msg: str = "Forbidden") -> None:
    """403 Forbidden 발생"""
    raise HTTPException(status_code=403, detail=msg)


def bad_request(msg: str) -> None:
    """400 Bad Request 발생"""
    raise HTTPException(status_code=400, detail=msg)


def conflict(msg: str) -> None:
    """409 Conflict 발생 (중복 리소스 등)"""
    raise HTTPException(status_code=409, detail=msg)


def unprocessable(msg: str) -> None:
    """422 Unprocessable Entity 발생 (비즈니스 로직 검증 실패)"""
    raise HTTPException(status_code=422, detail=msg)


def service_unavailable(msg: str = "Service temporarily unavailable") -> None:
    """503 Service Unavailable 발생 (외부 서비스 장애 등)"""
    raise HTTPException(status_code=503, detail=msg)
