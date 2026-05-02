from rest_framework.response import Response
from rest_framework import status

def error_response(message, code, status_code, details=None):
    payload = {"error": message, "code": code}
    if details:
        payload["details"] = details
    return Response(payload, status=status_code)

def not_found_response(message="The requested resource was not found."):
    return error_response(
        message, 
        "NOT_FOUND", 
        status.HTTP_404_NOT_FOUND
    )

def internal_error_response():
    return error_response(
        "An unexpected error occurred. Please contact the administrator.", 
        "INTERNAL_SERVER_ERROR", 
        status.HTTP_500_INTERNAL_SERVER_ERROR
    )

def validation_error_response(details):
    return error_response(
        "Validation failed", 
        "VALIDATION_ERROR", 
        status.HTTP_400_BAD_REQUEST, 
        details
    )

def conflict_response(message, details=None):
    return error_response(
        message,
        "CONFLICT",
        status.HTTP_409_CONFLICT,
        details
    )
