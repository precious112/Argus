/**
 * Express middleware for Argus.
 */

import { getClient } from "../index";

type NextFunction = (err?: unknown) => void;

interface Request {
  method: string;
  path: string;
  url: string;
}

interface Response {
  statusCode: number;
  on(event: string, cb: () => void): void;
}

/**
 * Express middleware that logs requests and captures errors.
 */
export function argusMiddleware() {
  return (req: Request, res: Response, next: NextFunction): void => {
    const start = Date.now();
    const client = getClient();

    res.on("finish", () => {
      const duration = Date.now() - start;
      if (client) {
        client.sendEvent("log", {
          level: res.statusCode >= 500 ? "ERROR" : "INFO",
          message: `${req.method} ${req.path || req.url} ${res.statusCode} (${duration}ms)`,
          method: req.method,
          path: req.path || req.url,
          status_code: res.statusCode,
          duration_ms: duration,
        });
      }
    });

    next();
  };
}
