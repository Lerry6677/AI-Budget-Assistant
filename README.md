# AI Budget Assistant

一个基于大语言模型的聊天式智能记账助手。

传统记账工具需要用户主动填写账单，
导致记录成本高、坚持困难。

本项目希望通过自然语言交互，
让用户像聊天一样完成记账、预算管理和消费分析。

例如：

> 用户：今天早餐花了8块，公交4块
>
> AI：已记录：
> - 早餐 - 8元
> - 交通 - 4元
>
> 今日消费 12 元。

---

## 核心功能

### MVP

- 自然语言记账
- 自动分类消费
- 月度预算管理
- 消费分析
- AI 财务建议

---

## 技术方案

| 层 | 技术 |
| --- | --- |
| Backend | Python / FastAPI |
| ORM | SQLAlchemy + PyMySQL |
| Database | MySQL |
| AI（当前） | Dify Workflow / Agent |
| AI（新）  | **LangChain + LangGraph（内嵌到 FastAPI）** |

---

## 项目结构

```
backend/
├── api/                # FastAPI 路由
│   ├── chat.py         # /chat：根据 AGENT_ENABLED 切换 Agent / Dify
│   ├── agent.py        # 给 Agent 回调的纯数据接口
│   ├── expense.py      # 普通用户账单 CRUD
│   ├── user.py
│   └── dependencies.py
├── agent/              # ★ LangChain / LangGraph 编排层
│   ├── llm.py          # LLM 工厂（OpenAI / DashScope / DeepSeek）
│   ├── prompts.py      # System Prompt 与消息模板
│   ├── tools.py        # @tool 工具集（save / query / analyze / profile）
│   ├── state.py        # Agent Graph 状态定义
│   ├── checkpointer.py # 会话记忆（默认内存，可切 SQLite / MySQL）
│   └── graph.py        # 装配：create_react_agent
├── services/           # 业务逻辑层
│   ├── expense_service.py
│   ├── auth_service.py
│   └── dify_service.py # 旧实现，AGENT_ENABLED=false 时回退
├── models/             # SQLAlchemy ORM
├── schemas/            # Pydantic
├── database/           # 连接 / Session / Base
├── utils/
├── config.py           # 统一读取环境变量
└── main.py             # FastAPI 入口
```

---

## 架构演进

### 旧：Dify 外包大脑

```
用户 → FastAPI /chat → Dify Workflow → LLM
                                ↓
                         HTTP Tool（FastAPI /agent/*）
                                ↓
                              MySQL
```

### 新：LangGraph 内嵌大脑（当前目标）

```
用户 → FastAPI /chat → LangGraph Agent → LLM
                              ├── tools（save/query/analyze/profile）→ 业务 service
                              └── checkpointer（按 user_id 隔离会话）
                                                ↓
                                             MySQL
```

通过 `AGENT_ENABLED` 切换：

- `AGENT_ENABLED=true`  → 走 LangGraph Agent
- `AGENT_ENABLED=false` → 继续走 Dify（兼容，便于回退）

---

## 快速开始

1. 复制环境变量模板

   ```bash
   cp .env.example .env
   ```

2. 编辑 `.env`，至少填好：

   - `DATABASE_URL`
   - `JWT_SECRET_KEY`
   - `LLM_API_KEY`（当 `AGENT_ENABLED=true`）

3. 安装依赖

   ```bash
   cd backend
   python -m venv venv
   venv\Scripts\activate     # Windows
   pip install -r requirements.txt
   ```

4. 启动

   ```bash
   uvicorn main:app --reload
   ```

5. 打开 [http://localhost:8000/docs](http://localhost:8000/docs) 查看 API。

---

## 当前状态

🚧 LangChain 化重构中

- ✅ 项目骨架与配置切换
- ✅ `agent/` 目录骨架（`llm.py` / `prompts.py` / `tools.py` / `state.py` / `checkpointer.py` / `graph.py`）
- ✅ `/chat` 双路径入口
- ⏳ 工具实现 & 端到端联调（每个文件都已留 TODO）

---

## 开发路线

参考 `docs/PRD.md` 和 `docs/Development_Task_List.md`。
