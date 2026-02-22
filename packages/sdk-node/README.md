# @argus-ai/node

Argus Node.js SDK — instrumentation for AI-native observability, monitoring, and security.

## Installation

```bash
npm install @argus-ai/node
```

## Quick Start

### Initialize the SDK

```typescript
import { init } from '@argus-ai/node';

init({
  serverUrl: 'https://argus.example.com',
  apiKey: 'your-api-key',
  serviceName: 'my-service',
});
```

### Express Middleware

```typescript
import express from 'express';
import { argusMiddleware } from '@argus-ai/node';

const app = express();
app.use(argusMiddleware());
```

### Trace Functions

```typescript
import { trace } from '@argus-ai/node';

class UserService {
  @trace('fetchUser')
  async fetchUser(id: string) {
    // Automatically creates a span with timing and error capture
  }
}
```

### Capture Exceptions

```typescript
import { captureException } from '@argus-ai/node';

try {
  riskyOperation();
} catch (err) {
  captureException(err as Error);
}
```

### Breadcrumbs

```typescript
import { addBreadcrumb } from '@argus-ai/node';

addBreadcrumb('http', 'GET /api/users', { statusCode: 200 });
```

### Custom Events

```typescript
import { event } from '@argus-ai/node';

event('payment_processed', { amount: 99.99, currency: 'USD' });
```

### Logging

```typescript
import { ArgusLogger } from '@argus-ai/node';

const logger = new ArgusLogger('api');
logger.log('Request handled', { path: '/users' });
logger.error('Something failed', { code: 500 });
```

## Features

- **Distributed Tracing** — W3C Traceparent propagation across services
- **Express Middleware** — Automatic request/response instrumentation
- **Function Tracing** — `@trace` decorator for class methods
- **Exception Capture** — Stack traces with breadcrumb context
- **Breadcrumbs** — Trail of events leading up to errors
- **Custom Events** — Send arbitrary telemetry data
- **Structured Logging** — `ArgusLogger` with log levels and auto-forwarding
- **HTTP Instrumentation** — Auto-instrument outgoing `fetch` calls
- **Serverless Support** — Auto-detects AWS Lambda, Vercel, GCP Functions, Cloudflare Workers
- **Non-blocking** — Events are batched and flushed asynchronously
- **AsyncLocalStorage** — Trace context propagates through async calls automatically

## License

MIT — see [LICENSE](LICENSE) for details.
