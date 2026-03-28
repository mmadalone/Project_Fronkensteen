![AI Embedding](https://raw.githubusercontent.com/mmadalone/Project_Fronkensteen/main/images/header/ai_embedding-header.jpeg)

# AI Embedding — Semantic Search & Memory Lifecycle

Configuration package for the semantic search subsystem (I-2) and memory lifecycle monitoring (I-42). Provides all tuning knobs for embedding generation, vector search, and automatic memory archival.

## What's Inside

- **Automations:** 1 (`ai_embedding_dimension_change`)
- **Input helpers:** 12 (moved to consolidated helper files) -- 3 booleans, 6 numbers, 3 texts

## Entity Reference

| Entity ID | Type | Purpose |
|---|---|---|
| `input_text.ai_task_instance` | input_text | `ha_text_ai` sensor entity for LLM calls |
| `input_text.ai_embedding_api_url` | input_text | Embedding API base URL (OpenRouter, OpenAI) |
| `input_text.ai_embedding_api_key` | input_text | API key (password mode) |
| `input_text.ai_embedding_model` | input_text | Embedding model name |
| `input_number.ai_embedding_dimensions` | input_number | Vector dimensions (changing triggers reindex) |
| `input_datetime.ai_embedding_batch_time` | input_datetime | Nightly batch schedule |
| `input_number.ai_embedding_batch_size` | input_number | Records per batch run |
| `input_number.ai_semantic_search_results` | input_number | Default result count |
| `input_number.ai_semantic_similarity_threshold` | input_number | Minimum cosine similarity |
| `input_number.ai_semantic_blend_weight` | input_number | FTS5/semantic blend (0=FTS5 only, 100=semantic only) |
| `input_boolean.ai_embedding_reindex_needed` | input_boolean | Flag for full reindex |
| `input_number.ai_memory_record_limit` | input_number | Lifecycle monitoring: record count threshold (I-42) |
| `input_number.ai_memory_db_max_mb` | input_number | Lifecycle monitoring: DB size threshold (I-42) |
| `input_boolean.ai_memory_auto_archive` | input_boolean | Auto-archive master toggle (I-42 Phase 2) |
| `input_number.ai_memory_archive_target_pct` | input_number | Archive down to this percentage (I-42 Phase 2) |
| `input_number.ai_memory_archive_recency_days` | input_number | Recency protection window (I-42 Phase 2) |
| `input_text.ai_memory_archive_protection_tags` | input_text | Protected tag list (I-42 Phase 2) |
| `automation.ai_embedding_dimension_change` | automation | Flips reindex flag when embedding dimensions change |

## Dependencies

- **Pyscript:** `pyscript/memory.py` (semantic search services, embedding generation, archival)

## Cross-References

- **All pyscript modules** that call `pyscript.memory_search` or `pyscript.memory_set` rely on embedding configuration from this package
- **Voice agents** use semantic search via LLM tool functions

## Notes

- Changing `ai_embedding_dimensions` automatically sets `ai_embedding_reindex_needed` to ON via the dimension change automation. The next batch run will rebuild the vector table.
- The dimension change automation is a package automation (infrastructure glue), not a blueprint -- it monitors a single helper and flips a flag.
- I-42 Phase 2 added auto-archive capabilities with configurable target percentage, recency protection, and tag-based protection.
- Deployed: 2026-03-05.
