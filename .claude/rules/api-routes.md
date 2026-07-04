---
paths:
  - "**/api/**"
  - "**/routes/**"
  - "**/route.ts"
  - "**/route.tsx"
---

# API route authoring rules

These rules apply when writing HTTP route handlers (Next.js App Router, Express, Hono, Fastify, etc.).

## Input validation (mandatory)

- Every route MUST validate every input with **zod** schema.
  - Query params → `z.object({...}).parse(req.query)`
  - Path params → `z.object({...}).parse(req.params)`
  - Body → `z.object({...}).parse(await req.json())`
- Do NOT use `any`, `unknown`, or raw `req.body` in the handler body.
- Schemas MUST be exported and named `<routeName>Schema`.
- Nested objects use `.extend({...})` or composition; do not inline.

## Response envelope (mandatory)

Every successful response MUST use this exact shape:

```ts
return Response.json({
  data: <T>,        // payload
  error: null,      // always null on success
  meta: {           // always present, even if empty
    requestId: <string>,
    timestamp: <ISO 8601 string>,
  },
});
```

Every error response MUST use:

```ts
return Response.json({
  data: null,
  error: { code: <UPPER_SNAKE>, message: <human-readable>, details?: <object> },
  meta: { requestId, timestamp },
}, { status: <HTTP code> });
```

`data` and `error` are **mutually exclusive** — exactly one is non-null.

## HTTP status codes (mandatory)

Use the **first matching** code:

| Situation | Status |
|---|---|
| `GET` success, `POST` creating | 200 / 201 |
| `POST` update, `DELETE` success | 200 / 204 |
| Validation failed (zod) | **400** |
| Missing/invalid auth | **401** |
| Auth valid but insufficient permission | **403** |
| Resource not found | **404** |
| Unique constraint / business rule violation | **409** |
| Input type OK but semantically wrong (e.g. wrong state) | **422** |
| Rate limit | **429** |
| Server error, unhandled | **500** (never expose internals) |
| External dependency failed | **502** / **503** / **504** |

## Forbidden patterns

- ❌ Throwing raw `Error` to the client (use the error envelope).
- ❌ Returning `data` without `meta` (even if empty).
- ❌ HTTP 200 for failures (common slip).
- ❌ Logging secrets in `error.details`.

## Reference example

```ts
const CreateUserSchema = z.object({
  email: z.string().email(),
  name: z.string().min(1).max(100),
});

export async function POST(req: Request) {
  try {
    const body = CreateUserSchema.parse(await req.json());
    const user = await db.user.create({ data: body });
    return Response.json({
      data: user,
      error: null,
      meta: { requestId: crypto.randomUUID(), timestamp: new Date().toISOString() },
    }, { status: 201 });
  } catch (e) {
    if (e instanceof z.ZodError) {
      return Response.json({
        data: null,
        error: { code: 'VALIDATION_FAILED', message: 'Invalid input', details: e.flatten() },
        meta: { requestId: crypto.randomUUID(), timestamp: new Date().toISOString() },
      }, { status: 400 });
    }
    throw e; // bubble to 500 handler
  }
}
```
