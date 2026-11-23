class ApiError(Exception):
    status = 400
    code = "bad_request"

    def __init__(self, message: str = "", *, code: str | None = None, details=None):
        super().__init__(message)
        self.message = message or self.__class__.__name__
        if code:
            self.code = code
        self.details = details


class ValidationFailed(ApiError):
    status = 422
    code = "validation_error"


class NotFound(ApiError):
    status = 404
    code = "not_found"


class Forbidden(ApiError):
    status = 403
    code = "forbidden"


class Conflict(ApiError):
    status = 409
    code = "conflict"
