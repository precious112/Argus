# argus-python

Argus Python SDK — instrumentation for AI-native observability, monitoring, and security.

## Installation

```bash
pip install argus-ai-sdk
```

With framework extras:

```bash
pip install argus-ai-sdk[fastapi]
pip install argus-ai-sdk[flask]
```

## Quick Start

### Initialize the SDK

```python
import argus

argus.init(
    server_url="https://argus.example.com",
    api_key="your-api-key",
    service_name="my-service",
)
```

### Framework Middleware

**FastAPI:**

```python
from fastapi import FastAPI
from argus.middleware.fastapi import ArgusMiddleware

app = FastAPI()
app.add_middleware(ArgusMiddleware)
```

**Flask:**

```python
from flask import Flask
from argus.middleware.flask import ArgusFlask

app = Flask(__name__)
ArgusFlask(app)
```

### Trace Functions

```python
from argus.decorators import trace

@trace("fetch_user")
async def fetch_user(user_id: str):
    # Automatically creates a span with timing and error capture
    ...
```

### Capture Exceptions

```python
try:
    risky_operation()
except Exception:
    argus.capture_exception()
```

### Breadcrumbs

```python
argus.add_breadcrumb(
    category="http",
    message="GET /api/users",
    data={"status_code": 200}
)
```

### Custom Events

```python
argus.event("payment_processed", {"amount": 99.99, "currency": "USD"})
```

## Features

- **Distributed Tracing** — W3C Traceparent propagation across services
- **Framework Middleware** — FastAPI and Flask integrations
- **Function Tracing** — `@trace` decorator for sync and async functions
- **Exception Capture** — Automatic stack traces with breadcrumb context
- **Breadcrumbs** — Trail of events leading up to errors
- **Custom Events** — Send arbitrary telemetry data
- **HTTP Instrumentation** — Auto-instrument outgoing httpx requests
- **Serverless Support** — Auto-detects AWS Lambda, Vercel, GCP Functions, and more
- **Non-blocking** — Events are batched and flushed asynchronously

## License

MIT — see [LICENSE](LICENSE) for details.
