# YOBI Oracle AI Database 26ai

The application schema is owned by `YOBI_APP`; the runtime never uses `ADMIN`.
Migrations are sequential SQL files with SHA-256 checksums recorded in
`SCHEMA_MIGRATION`. `menu`, `review_snippet`, and `menu_knowledge` use fixed
`VECTOR(1536, FLOAT32)` columns. Safety constraints are always relational filters;
vector distance only ranks already-safe candidates.

Commands:

```bash
make db-bootstrap  # interactive, secrets are read without echo
make db-migrate
make db-seed
python scripts/seed_demo.py --verify-only
```

`--fresh` removes only deterministic catalog rows from the `YOBI_APP` schema. It is
intentionally not the default and is not used by deployment automation.
