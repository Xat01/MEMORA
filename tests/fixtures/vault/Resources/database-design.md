---
title: "Database Design Principles"
tags: [database, design, sql, normalization]
created: 2024-02-05
updated: 2024-02-20
---

# Database Design Principles

Fundamental principles for relational database design.

## Normalization

Process of organizing data to reduce redundancy.

### 1NF - First Normal Form

- Atomic values only
- No repeating groups
- Each column single value

### 2NF - Second Normal Form

- In 1NF
- No partial dependencies
- All non-key attributes depend on whole key

### 3NF - Third Normal Form

- In 2NF
- No transitive dependencies
- Non-key attributes depend only on key

### BCNF - Boyce-Codd Normal Form

- Stricter 3NF
- Every determinant is a candidate key

## Indexing Strategy

### When to Index

- Foreign keys (always)
- WHERE clause columns
- JOIN columns
- ORDER BY columns

### Index Types

- B-Tree (default, range queries)
- Hash (equality only)
- GIN (arrays, full-text)
- GiST (geometric, full-text)

## Query Optimization

### EXPLAIN ANALYZE

Understand query execution plans.

```sql
EXPLAIN ANALYZE
SELECT * FROM orders
WHERE customer_id = 123
AND created_at > '2024-01-01';
```

### Common Optimizations

- Avoid SELECT *
- Use LIMIT for pagination
- Prefer EXISTS over IN for subqueries
- Denormalize for read-heavy workloads

## Migrations

### Best Practices

- One migration per logical change
- Never modify applied migrations
- Test migrations locally first
- Use transactions where possible
- Include rollback instructions

### Naming Convention

```
YYYYMMDD_HHMMSS_description.sql
```

Example: `20240115_143000_add_user_indexes.sql`