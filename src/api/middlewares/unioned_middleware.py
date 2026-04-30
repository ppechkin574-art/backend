# import logging
# import time
# import uuid
# from fastapi import Request
# from starlette.middleware.base import BaseHTTPMiddleware
# from utils.monitoring import ERROR_COUNT, REQUEST_COUNT, REQUEST_DURATION

# logger = logging.getLogger(__name__)


# class UnionedMiddleware(BaseHTTPMiddleware):
#     async def dispatch(self, request: Request, call_next):
#         if request.url.path in ["/metrics", "/health", "/ready"]:
#             return await call_next(request)
#         user_id = "anonymous"
#         auth_header = request.headers.get("authorization")

#         if auth_header and auth_header.startswith("Bearer "):
#             try:
#                 auth_service = request.app.state.container.auth_service()
#                 user_dto = auth_service.get_user_from_token(
#                     auth_header.replace("Bearer ", "")
#                 )
#                 user_id = str(user_dto.id)
#                 # user_email = str(user_dto.email) if user_dto.email else ""
#             except Exception as e:
#                 logger.info("[CombinedMiddleware] Failed to get user from token: %s", e)

#         request.state.user_id = user_id

#         request_id = str(uuid.uuid4())
#         client_ip = request.client.host if request.client else "unknown"

#         if request.headers.get("x-forwarded-for"):
#             client_ip = request.headers["x-forwarded-for"].split(",")[0]
#         elif request.headers.get("x-real-ip"):
#             client_ip = request.headers["x-real-ip"]

#         base_context = {
#             "request_id": request_id,
#             "user_id": user_id,
#             # "email": user_email,
#             "client_ip": client_ip,
#             "method": request.method,
#             "endpoint": request.url.path,
#             "user_agent": request.headers.get("user-agent", ""),
#             "query_params": dict(request.query_params),
#         }

#         context_filter = RequestContextFilter(base_context)

#         root_logger = logging.getLogger()
#         for handler in root_logger.handlers:
#             handler.addFilter(context_filter)

#         start_time = time.time()

#         try:
#             response = await call_next(request)

#             process_time = time.time() - start_time
#             REQUEST_COUNT.labels(
#                 method=request.method,
#                 endpoint=request.url.path,
#                 status_code=response.status_code,
#             ).inc()

#             REQUEST_DURATION.labels(
#                 method=request.method, endpoint=request.url.path
#             ).observe(process_time)

#             logging.info(
#                 "Request completed",
#                 extra={
#                     "props": {
#                         **base_context,
#                         "status_code": response.status_code,
#                         "response_time_seconds": round(process_time, 3),
#                         "response_size": int(response.headers.get("content-length", 0)),
#                     }
#                 },
#             )

#             return response

#         except Exception as e:
#             process_time = time.time() - start_time

#             ERROR_COUNT.labels(
#                 method=request.method,
#                 endpoint=request.url.path,
#                 error_type=type(e).__name__,
#             ).inc()

#             logging.exception(
#                 "Request failed: %s",
#                 e,
#                 extra={
#                     "props": {
#                         **base_context,
#                         "status_code": 500,
#                         "response_time_seconds": round(process_time, 3),
#                         "error_type": type(e).__name__,
#                     }
#                 },
#             )
#             raise
#         finally:
#             for handler in root_logger.handlers:
#                 handler.removeFilter(context_filter)


# class RequestContextFilter(logging.Filter):
#     """Фильтр для добавления контекста ко всем логам"""

#     def __init__(self, context):
#         super().__init__()
#         self.context = context

#     def filter(self, record):
#         if not hasattr(record, "props"):
#             record.props = {}
#         record.props.update(self.context)
#         return True
