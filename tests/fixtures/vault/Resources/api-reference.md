---
title: "API Reference Guide"
tags: [api, reference, rest, graphql]
created: 2024-01-20
updated: 2024-02-15
---

# API Reference Guide

Quick reference for common API patterns.

## REST Endpoints

Standard CRUD operations.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /resources | List all resources |
| GET | /resources/{id} | Get single resource |
| POST | /resources | Create new resource |
| PUT | /resources/{id} | Update resource |
| PATCH | /resources/{id} | Partial update |
| DELETE | /resources/{id} | Delete resource |

## Query Parameters

Common query parameters for list endpoints.

- `page` - Page number (default: 1)
- `per_page` - Items per page (default: 20, max: 100)
- `sort` - Sort field (prefix with `-` for descending)
- `filter` - Filter expression
- `search` - Full-text search

## Error Responses

Standard error format.

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid input",
    "details": [
      {"field": "email", "message": "Invalid email format"}
    ]
  }
}
```

## Authentication

### Bearer Token

```
Authorization: Bearer <token>
```

### API Key

```
X-API-Key: <key>
```

## Rate Limiting

Headers for rate limit information.

- `X-RateLimit-Limit` - Request limit
- `X-RateLimit-Remaining` - Remaining requests
- `X-RateLimit-Reset` - Reset timestamp (Unix)