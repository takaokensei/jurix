# Jurix Release Checklist v2

## Candidate preparation

- [ ] working tree clean;
- [ ] commit is reproducible;
- [ ] release identifier recorded;
- [ ] migration plan reviewed;
- [ ] RAG model identifiers pinned;
- [ ] corpus version recorded.

## Code gates

- [ ] Ruff passed;
- [ ] Python tests passed;
- [ ] JS/browser tests passed;
- [ ] Django checks passed;
- [ ] architecture budget reviewed;
- [ ] security audit passed.

## Database gates

- [ ] migration state clean;
- [ ] PostgreSQL is used;
- [ ] pgvector extension enabled;
- [ ] vector coverage above release threshold;
- [ ] corpus integrity passed.

## Data/storage

- [ ] attachment audit passed;
- [ ] backup created;
- [ ] backup hash recorded;
- [ ] restore verification current;
- [ ] object storage credentials valid.

## RAG

- [ ] reviewed benchmark selected;
- [ ] benchmark hash recorded;
- [ ] retrieval metrics compared;
- [ ] citation metrics compared;
- [ ] grounding regression reviewed;
- [ ] unanswerable cases reviewed.

## Staging

- [ ] web health;
- [ ] queue health;
- [ ] Ollama reachability;
- [ ] HTTP smoke;
- [ ] one search request;
- [ ] one RAG request;
- [ ] one upload lifecycle;
- [ ] one session lifecycle.

## Rollback

- [ ] rollback artifact exists;
- [ ] DB compatibility confirmed;
- [ ] operator knows rollback sequence.
