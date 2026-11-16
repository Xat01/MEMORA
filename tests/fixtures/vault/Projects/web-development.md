---
title: "Web Development Notes"
tags: [web, frontend, backend, api]
created: 2024-02-01
updated: 2024-02-10
---

# Web Development Notes

Collection of web development concepts and patterns.

## Frontend

### React Patterns

Common React patterns and hooks.

```jsx
function useLocalStorage(key, initialValue) {
  const [value, setValue] = useState(() => {
    const stored = localStorage.getItem(key);
    return stored ? JSON.parse(stored) : initialValue;
  });

  useEffect(() => {
    localStorage.setItem(key, JSON.stringify(value));
  }, [key, value]);

  return [value, setValue];
}
```

### State Management

Options for managing application state.

- Context API
- Redux Toolkit
- Zustand
- Jotai

## Backend

### API Design

RESTful API best practices.

- Use nouns for resources
- Proper HTTP status codes
- Versioning in URL
- Pagination for collections

### Database Patterns

Common database patterns.

- Repository pattern
- Unit of Work
- Migrations

## Deployment

### CI/CD

Continuous integration and deployment pipelines.

```yaml
name: Deploy
on:
  push:
    branches: [main]
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: npm ci && npm test
      - run: npm run deploy
```

### Containerization

Docker best practices for web apps.