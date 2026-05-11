# 日报生成器

基于 RAG 的 AI 日报生成工具，支持 Claude、DeepSeek、通义千问、智谱 GLM。

## 项目结构

```
daily-report/
├── main.py              # FastAPI 后端（API 代理 + RAG 存储）
├── requirements.txt
├── .env.example         # 环境变量模板
├── Dockerfile
├── docker-compose.yml
├── nginx.conf           # 生产环境反向代理配置
├── data/                # RAG 任务库（自动创建，建议挂载 volume）
└── static/
    └── index.html       # 前端页面
```

## 快速部署

### 方式一：Docker（推荐）

```bash
# 1. 克隆项目
git clone <your-repo>
cd daily-report

# 2. 配置 API Key
cp .env.example .env
vim .env   # 填入对应的 API Key

# 3. 启动（仅应用，适合内网/开发）
docker compose up -d

# 4. 访问
open http://your-server-ip:8000
```

### 方式二：Docker + Nginx（生产 HTTPS）

```bash
# 1. 配置 .env（同上）

# 2. 修改 nginx.conf 中的域名
sed -i 's/your-domain.com/yourdomain.com/g' nginx.conf

# 3. 放入 SSL 证书（certbot 或自签）
mkdir certs
cp /etc/letsencrypt/live/yourdomain.com/fullchain.pem certs/
cp /etc/letsencrypt/live/yourdomain.com/privkey.pem certs/

# 4. 启动（含 Nginx）
docker compose --profile prod up -d
```

### 方式三：直接运行（本地开发）

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置环境变量
cp .env.example .env
vim .env

# 3. 启动
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# 4. 访问
open http://localhost:8000
```

## API Key 配置

API Key 有两种配置方式，前者优先级更高：

| 方式 | 场景 | 安全性 |
|------|------|--------|
| 服务端 `.env` | 团队共用，Key 统一管理 | ★★★ |
| 前端页面输入 | 个人使用，或临时切换 | ★★ |

### .env 配置项

```env
ANTHROPIC_API_KEY=sk-ant-xxxxxxxx     # Claude
DEEPSEEK_API_KEY=sk-xxxxxxxx          # DeepSeek
QWEN_API_KEY=sk-xxxxxxxx              # 通义千问
GLM_API_KEY=xxxxxxxx.xxxxxxxx         # 智谱 GLM
```

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/providers` | 获取服务商列表及配置状态 |
| POST | `/api/generate` | 生成日报（SSE 流式） |
| POST | `/api/rag/parse` | 解析历史日报，提取任务 |
| GET | `/api/rag/docs` | 获取所有 RAG 文档 |
| POST | `/api/rag/docs` | 批量新增/更新文档 |
| PATCH | `/api/rag/docs/{id}` | 更新单条文档描述 |
| DELETE | `/api/rag/docs/{id}` | 删除单条文档 |
| DELETE | `/api/rag/docs` | 清空任务库 |
| GET | `/api/health` | 健康检查 |

交互式文档：`http://your-server:8000/docs`

## 数据持久化

RAG 任务库存储在 `data/rag_docs.json`，Docker 部署时已通过 volume 挂载到宿主机 `./data/`，重启容器数据不丢失。

## 更新部署

```bash
git pull
docker compose up -d --build
```
