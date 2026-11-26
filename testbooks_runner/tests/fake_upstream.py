"""A stand-in for the model service. Each request it gets is appended to `calls`."""
from __future__ import annotations

import asyncio
import gzip
import json

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from testbooks_runner.tests.minimal import minimal_instance

USAGE = {"prompt_tokens": 100, "completion_tokens": 50}


def make_upstream(calls: list) -> Starlette:
    async def note(request: Request) -> bytes:
        body = await request.body()
        calls.append({"method": request.method, "path": request.url.path,
                      "query": request.url.query, "headers": dict(request.headers), "body": body})
        return body

    async def chat(request: Request):
        raw = await note(request)
        body = json.loads(raw or b"{}")
        if not body.get("stream"):
            return JSONResponse({"id": "gen-1", "choices": [{"message": {"content": "hi"}}], "usage": USAGE})
        gap = 0.4 if body.get("slow") else 0.15

        async def events():
            for i in range(3):
                chunk = {"id": "gen-1", "choices": [{"delta": {"content": str(i)}}]}
                if i == 2:
                    chunk["usage"] = USAGE
                yield f"data: {json.dumps(chunk)}\n\n".encode()
                await asyncio.sleep(gap)
            yield b"data: [DONE]\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

    async def key(request: Request):
        await note(request)
        return JSONResponse({"data": {"label": "fake"}})

    async def models(request: Request):
        await note(request)
        return JSONResponse({"data": [{"id": "qwen/qwen3.8-27b", "active": True}]})

    async def generation(request: Request):
        await note(request)
        return JSONResponse({"data": {"total_cost": 0.0012, "tokens_prompt": 100, "tokens_completion": 50}})

    async def fail(request: Request):
        await note(request)
        return JSONResponse({"error": {"message": "slow down"}}, status_code=429)

    async def gzipped(request: Request):
        await note(request)
        return Response(gzip.compress(b'{"data": {"zipped": true}}'), media_type="application/json",
                        headers={"content-encoding": "gzip"})

    async def gzipped_stream(request: Request):
        await note(request)
        body = gzip.compress(b'data: {"id": "gen-7", "choices": []}\n\ndata: [DONE]\n\n')

        async def chunks():  # compressed although the relay asked for identity, as a proxy might
            for i in range(0, len(body), 16):
                yield body[i:i + 16]

        return StreamingResponse(chunks(), media_type="text/event-stream", headers={"content-encoding": "gzip"})

    async def drop(request: Request):
        await note(request)

        async def events():
            yield b'data: {"id": "gen-9"}\n\n'
            yield b'data: {"id": "gen-9", "n": 2}\n\n'
            raise RuntimeError("upstream dropped")

        return StreamingResponse(events(), media_type="text/event-stream")

    async def stall(request: Request):
        await note(request)

        async def events():
            yield b'data: {"id": "gen-8"}\n\n'
            yield b'data: {"id": "gen-8", "n": 2}\n\n'
            await asyncio.sleep(25)

        return StreamingResponse(events(), media_type="text/event-stream")

    return Starlette(routes=[
        Route("/api/v1/drop", drop, methods=["POST"]),
        Route("/api/v1/stall", stall, methods=["POST"]),
        Route("/api/v1/chat/completions", chat, methods=["POST"]),
        Route("/api/v1/key", key),
        Route("/api/v1/models/user", models),
        Route("/api/v1/generation", generation),
        Route("/api/v1/fail", fail, methods=["POST"]),
        Route("/api/v1/gzipped", gzipped),
        Route("/api/v1/gzipped-stream", gzipped_stream, methods=["POST"]),
    ])


def make_minimal_upstream(calls: list) -> Starlette:
    """Like make_upstream, but a chat answers with the smallest JSON its response_format schema allows."""
    app = make_upstream(calls)
    count = [0]

    async def chat(request: Request):
        raw = await request.body()
        calls.append({"method": request.method, "path": request.url.path, "query": request.url.query,
                      "headers": dict(request.headers), "body": raw})
        body = json.loads(raw or b"{}")
        schema = ((body.get("response_format") or {}).get("json_schema") or {}).get("schema") or {}
        count[0] += 1
        return JSONResponse({"id": f"gen-{count[0]}",
                             "choices": [{"message": {"role": "assistant",
                                                      "content": json.dumps(minimal_instance(schema))},
                                          "finish_reason": "stop"}],
                             "usage": {**USAGE, "cost": 0}})

    app.router.routes.insert(0, Route("/api/v1/chat/completions", chat, methods=["POST"]))

    async def generation(request: Request):
        calls.append({"method": request.method, "path": request.url.path, "query": request.url.query,
                      "headers": dict(request.headers), "body": b""})
        return JSONResponse({"data": {"total_cost": 0, "tokens_prompt": 100, "tokens_completion": 50}})

    app.router.routes.insert(0, Route("/api/v1/generation", generation))
    return app
