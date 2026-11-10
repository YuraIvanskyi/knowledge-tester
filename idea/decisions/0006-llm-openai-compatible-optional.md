# ADR-0006: The LLM is optional and assistive, reached through an OpenAI-compatible API, with an in-process job worker

- **Status:** Proposed (2026-11-10)
- **Related:** plan.md §15 · KT-701–KT-709

## Context

A local LLM should help with tedious tasks: importing students from text, images or files, and drafting or structuring tests. Host hardware varies widely, and some hosts can't run a model at all. Student data is personal. Local model servers (Ollama, LM Studio, the llama.cpp server, vLLM) all expose an OpenAI-compatible HTTP API. LLM calls take seconds to minutes on low-end hardware.

## Decision

- **Optional.** Everything works without an LLM. Assistant UI appears only when an endpoint is configured and healthy.
- **Assistive.** Output is always a proposal shown in a preview. Nothing is saved, published or graded without the teacher confirming it.
- **One thin client** for `/v1/chat/completions` over **httpx**, with text and image parts. The default base URL is `http://127.0.0.1:11434/v1` (Ollama). A privacy warning appears when the endpoint is outside localhost or the LAN.
- **Structured output.** Every feature declares a pydantic output schema. The app requests JSON-schema-constrained output when the server supports it, always validates, retries up to 2 times with the validation errors fed back, and then shows the raw output with the errors.
- **Jobs.** Each job is an `LLMJob` row handled by a **single in-process worker thread**: one job at a time, with HTMX polling for status. Jobs left running at startup are marked failed.

## Consequences

- **Easier:** no Celery, Redis or extra process. The engine can be swapped by changing a URL, and remote LAN GPUs work without code changes.
- **Harder:** a server restart loses running jobs (they're marked failed and can be retried). Throughput is one job at a time, which is fine for a single teacher's assistant tasks.
- **Revisit when** background work grows beyond LLM jobs: move to Django's tasks framework with a database-backed worker.

## Alternatives considered

- **The Ollama-specific Python client:** ties the app to one engine.
- **Celery with Redis:** heavy, with extra services on a teacher's laptop.
- **Streaming responses straight into the page:** works for chat, but the features here need validated structured results, and synchronous long requests are fragile on weak networks.
- **A cloud LLM by default:** needs internet and sends student data off the host. Teachers can still point the base URL at an OpenAI-compatible cloud endpoint if they choose, behind a warning.
