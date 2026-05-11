import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

app = FastAPI(title="日报生成器 API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 数据存储 ──────────────────────────────────────────────────
DATA_FILE = Path("data/rag_docs.json")
DATA_FILE.parent.mkdir(exist_ok=True)


def load_docs() -> list[dict]:
    if DATA_FILE.exists():
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    return []


def save_docs(docs: list[dict]):
    DATA_FILE.write_text(
        json.dumps(docs, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── 服务商配置 ────────────────────────────────────────────────
PROVIDERS: dict[str, dict] = {
    "claude": {
        "url": "https://api.anthropic.com/v1/messages",
        "format": "anthropic",
        "env_key": "ANTHROPIC_API_KEY",
        "models": ["claude-sonnet-4-20250514", "claude-opus-4-20250514", "claude-haiku-4-5-20251001"],
    },
    "deepseek": {
        "url": "https://api.deepseek.com/v1/chat/completions",
        "format": "openai",
        "env_key": "DEEPSEEK_API_KEY",
        "models": ["deepseek-chat", "deepseek-reasoner"],
    },
    "qwen": {
        "url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "format": "openai",
        "env_key": "QWEN_API_KEY",
        "models": ["qwen-plus", "qwen-turbo", "qwen-max", "qwen-long"],
    },
    "glm": {
        "url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "format": "openai",
        "env_key": "GLM_API_KEY",
        "models": ["glm-4-flash", "glm-4-air", "glm-4", "glm-4-plus"],
    },
}


# ── Pydantic 模型 ──────────────────────────────────────────────
class GenerateRequest(BaseModel):
    provider: str
    model: str
    prompt: str
    custom_url: Optional[str] = None
    api_key: Optional[str] = None  # 前端传入优先；否则读 .env


class RagDoc(BaseModel):
    proj: str
    name: str
    desc: str = ""
    date: str = ""


class RagDocPatch(BaseModel):
    desc: str


class ParseRequest(BaseModel):
    text: str


class UpsertRequest(BaseModel):
    docs: list[RagDoc]


# ── /api/providers ────────────────────────────────────────────
@app.get("/api/providers")
async def get_providers():
    """返回服务商列表及每个服务商在服务端是否已配置 Key。"""
    result = {}
    for pid, cfg in PROVIDERS.items():
        result[pid] = {
            "models": cfg["models"],
            "configured": bool(os.getenv(cfg["env_key"], "")),
        }
    return result


# ── /api/generate（流式 SSE）────────────────────────────────────
@app.post("/api/generate")
async def generate(req: GenerateRequest):
    cfg = PROVIDERS.get(req.provider)
    if cfg is None and req.provider != "custom":
        raise HTTPException(400, f"未知服务商: {req.provider}")

    # Key 优先级：请求体 > .env
    api_key = (req.api_key or "").strip()
    if not api_key and cfg:
        api_key = os.getenv(cfg["env_key"], "")
    if not api_key:
        env_name = cfg["env_key"] if cfg else "CUSTOM_API_KEY"
        raise HTTPException(400, f"API Key 未设置，请在 .env 中配置 {env_name} 或在请求中传入 api_key")

    url = req.custom_url if req.provider == "custom" else (cfg["url"] if cfg else "")
    fmt = cfg["format"] if cfg else "openai"

    async def stream_anthropic():
        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }
        body = {
            "model": req.model,
            "max_tokens": 2000,
            "stream": True,
            "messages": [{"role": "user", "content": req.prompt}],
        }
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                async with client.stream("POST", url, headers=headers, json=body) as resp:
                    if resp.status_code != 200:
                        err = await resp.aread()
                        yield f"data: {json.dumps({'error': err.decode()})}\n\n"
                        return
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            j = json.loads(data)
                            if j.get("type") == "content_block_delta":
                                text = j.get("delta", {}).get("text", "")
                                if text:
                                    yield f"data: {json.dumps({'text': text})}\n\n"
                        except Exception:
                            pass
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        yield "data: [DONE]\n\n"

    async def stream_openai():
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        body = {
            "model": req.model,
            "max_tokens": 2000,
            "stream": True,
            "messages": [{"role": "user", "content": req.prompt}],
        }
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                async with client.stream("POST", url, headers=headers, json=body) as resp:
                    if resp.status_code != 200:
                        err = await resp.aread()
                        yield f"data: {json.dumps({'error': err.decode()})}\n\n"
                        return
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            j = json.loads(data)
                            text = (j.get("choices") or [{}])[0].get("delta", {}).get("content", "")
                            if text:
                                yield f"data: {json.dumps({'text': text})}\n\n"
                        except Exception:
                            pass
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        yield "data: [DONE]\n\n"

    stream_fn = stream_anthropic if fmt == "anthropic" else stream_openai
    return StreamingResponse(
        stream_fn(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── /api/rag/parse ────────────────────────────────────────────
@app.post("/api/rag/parse")
async def parse_report(req: ParseRequest):
    """解析历史日报文本，提取任务列表（不入库）。"""
    docs = []
    sections = re.split(r"(?=【[^】]+】)", req.text)
    for sec in sections:
        hm = re.match(r"^【([^】]+)】", sec)
        if not hm:
            continue
        proj = hm.group(1).strip()
        body = sec[hm.end():]
        task_blocks = re.split(r"(?=\d+[、．.]\s*\S)", body)
        for blk in task_blocks:
            tm = re.match(r"^\d+[、．.]\s*(.+?)(?:（[^）]*）)?\s*\n", blk)
            if not tm:
                continue
            name = tm.group(1).strip()
            desc_lines = [
                l.strip()
                for l in blk[tm.end():].split("\n")
                if l.strip() and re.match(r"^\d+[\.．]", l.strip())
            ]
            desc = "\n".join(desc_lines)
            if name:
                docs.append({"proj": proj, "name": name, "desc": desc})
    return {"docs": docs, "count": len(docs)}


# ── /api/rag/docs CRUD ────────────────────────────────────────
@app.get("/api/rag/docs")
async def get_all_docs():
    return load_docs()


@app.post("/api/rag/docs")
async def upsert_docs(req: UpsertRequest):
    docs = load_docs()
    added = updated = 0
    for d in req.docs:
        exist = next((x for x in docs if x["proj"] == d.proj and x["name"] == d.name), None)
        if exist:
            if d.desc and not exist.get("desc"):
                exist["desc"] = d.desc
                updated += 1
        else:
            docs.append({
                "id": str(uuid.uuid4())[:8],
                "proj": d.proj,
                "name": d.name,
                "desc": d.desc,
                "date": d.date or datetime.now().strftime("%Y-%m-%d"),
            })
            added += 1
    save_docs(docs)
    return {"added": added, "updated": updated, "total": len(docs)}


@app.patch("/api/rag/docs/{doc_id}")
async def patch_doc(doc_id: str, body: RagDocPatch):
    docs = load_docs()
    for d in docs:
        if d["id"] == doc_id:
            d["desc"] = body.desc
            save_docs(docs)
            return d
    raise HTTPException(404, "文档不存在")


@app.delete("/api/rag/docs/{doc_id}")
async def delete_doc(doc_id: str):
    docs = load_docs()
    new_docs = [d for d in docs if d["id"] != doc_id]
    if len(new_docs) == len(docs):
        raise HTTPException(404, "文档不存在")
    save_docs(new_docs)
    return {"ok": True, "remaining": len(new_docs)}


@app.delete("/api/rag/docs")
async def clear_docs():
    save_docs([])
    return {"ok": True}


# ── 健康检查 ──────────────────────────────────────────────────
@app.get("/api/health")
async def health():
    return {"status": "ok", "docs": len(load_docs())}


# ── 静态文件（前端）────────────────────────────────────────────
app.mount("/", StaticFiles(directory="static", html=True), name="static")
