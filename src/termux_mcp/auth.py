"""Middleware token (header x-api-key) + pembatas percobaan gagal."""
import collections
import hmac
import time
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import PlainTextResponse


class Auth(BaseHTTPMiddleware):
    def __init__(self, app, token: str, max_fail: int = 10, window: int = 60):
        super().__init__(app)
        self.token = token.encode()
        self.max_fail = max_fail
        self.window = window
        self.fails = collections.defaultdict(list)

    async def dispatch(self, req, call_next):
        ip = req.client.host if req.client else "?"
        now = time.time()
        recent = [t for t in self.fails[ip] if now - t < self.window]
        if recent:
            self.fails[ip] = recent
        else:
            self.fails.pop(ip, None)
        if len(recent) >= self.max_fail:
            return PlainTextResponse("terlalu banyak percobaan", status_code=429)
        given = req.headers.get("x-api-key", "").encode()
        if not hmac.compare_digest(given, self.token):
            self.fails[ip].append(now)
            return PlainTextResponse("no", status_code=401)
        return await call_next(req)
