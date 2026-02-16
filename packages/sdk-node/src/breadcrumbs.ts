/**
 * Breadcrumb trail for error context.
 */

const MAX_BREADCRUMBS = 50;

interface Breadcrumb {
  timestamp: string;
  category: string;
  message: string;
  data: Record<string, unknown>;
}

const _breadcrumbs: Breadcrumb[] = [];

export function addBreadcrumb(
  category: string,
  message: string,
  data: Record<string, unknown> = {},
): void {
  _breadcrumbs.push({
    timestamp: new Date().toISOString(),
    category,
    message,
    data,
  });

  // Trim to max size
  while (_breadcrumbs.length > MAX_BREADCRUMBS) {
    _breadcrumbs.shift();
  }
}

export function getBreadcrumbs(): Breadcrumb[] {
  return [..._breadcrumbs];
}

export function clearBreadcrumbs(): void {
  _breadcrumbs.length = 0;
}
