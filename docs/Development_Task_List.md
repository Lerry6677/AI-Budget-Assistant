# 记账助手 AI 财务管理 App

> 开发任务拆分文档（Development Task List）

版本：v1.0  
状态：Draft  
更新时间：2026-07-22

---

# 1. 开发目标

基于 PRD 和技术设计文档，实现一个移动端 AI 记账助手。

第一阶段目标：

完成最小可用版本（MVP）

用户能够：

1. 打开 App
2. 输入消费信息
3. AI 自动解析消费内容
4. 用户确认记录
5. 保存到账单
6. 查看历史消费

---

# 2. 开发阶段规划

整体分为 6 个阶段：

```
Phase 1
项目初始化

↓

Phase 2
移动端页面开发

↓

Phase 3
后端服务开发

↓

Phase 4
LLM接入

↓

Phase 5
数据库和业务闭环

↓

Phase 6
优化和部署
```

---

# Phase 1 项目初始化

## Task 1.1 创建项目仓库

### 目标

创建 GitHub 项目。


项目名称：

```
finance-ai-assistant
```

---

目录：

```
finance-ai-assistant/

├── frontend/

├── backend/

├── docs/

├── prompts/

└── README.md
```

---

## Task 1.2 初始化前端项目

技术：

- UniApp
- Vue3


完成：

- 创建项目
- 配置运行环境
- 配置 UI 组件库


验收：

能够启动 App。


---

## Task 1.3 初始化后端项目

技术：

- Python
- FastAPI


完成：

创建：

```
backend/

├── main.py

├── requirements.txt

└── README.md
```


验收：

访问：

```
localhost:8000

```

返回：

```
Hello Finance AI
```

---

# Phase 2 移动端开发

目标：

完成 App 基础界面。

---

# Task 2.1 AI聊天页面


页面：

```
pages/chat/index.vue
```


功能：

- 消息列表
- 输入框
- 发送按钮


效果：

类似 ChatGPT。


---

验收：

用户输入：

```
今天早餐4元
```

页面显示：

```
用户：
今天早餐4元

AI：
正在分析...
```

---

# Task 2.2 消费确认卡片


功能：

AI返回结果后展示：

```
消费记录：

早餐

金额：
4元

分类：
餐饮


确认保存？
```

按钮：

- 确认
- 修改


---

# Task 2.3 账单页面


页面：

```
pages/bill/index.vue
```


功能：

展示：

```
7月22日

早餐 4元

公交 4.5元

```

---

# Task 2.4 分析页面


页面：

```
pages/analysis/index.vue
```


展示：

- 月消费金额
- 分类统计


---

# Phase 3 后端开发

目标：

建立 API 服务。

---

# Task 3.1 创建接口结构


目录：

```
backend/

├── api/

├── services/

├── models/

└── database/
```

---

# Task 3.2 用户接口


实现：

用户创建

接口：

```
POST /api/user
```

---

# Task 3.3 消费接口


实现：

新增消费：

```
POST /api/expense
```


查询消费：

```
GET /api/expense/list
```

---

# Task 3.4 分析接口


实现：

```
GET /api/analysis/month
```


返回：

```json
{
"total":1000,
"category":{
"餐饮":500
}
}
```

---

# Phase 4 LLM 接入

目标：

让 App 具备 AI 能力。

---

# Task 4.1 接入 LLM API


支持：

- OpenAI
- DeepSeek
- Claude


实现：

```
llm_service.py
```

---

# Task 4.2 编写消费解析 Prompt


文件：

```
prompts/

expense_parser.md
```


功能：

将：

```
今天吃饭20
```

转换：

```json
{
"name":"吃饭",
"amount":20,
"category":"餐饮"
}
```

---

# Task 4.3 实现结构化输出


要求：

LLM必须返回：

JSON


禁止：

自然语言输出。


---

# Task 4.4 AI聊天接口


接口：

```
POST /api/chat
```


流程：

```
用户输入

↓

FastAPI

↓

Prompt

↓

LLM

↓

JSON

↓

返回App
```

---

# Phase 5 数据库闭环

目标：

完成完整业务流程。


---

# Task 5.1 创建数据库


创建：

SQLite


表：

- user
- expense
- budget


---

# Task 5.2 保存账单


流程：

```
AI解析

↓

用户确认

↓

保存数据库
```

---

# Task 5.3 查询账单


支持：

用户：

```
我这个月花多少钱？
```

返回统计。

---

# Phase 6 优化和部署

---

# Task 6.1 UI优化


优化：

- 页面布局
- 动画
- 加载状态


---

# Task 6.2 异常处理


处理：

- API失败
- 网络异常
- LLM超时


---

# Task 6.3 部署


后端：

部署：

- Docker
- 云服务器


前端：

发布：

- Android APK


---

# 3. 每个阶段验收标准

|阶段|完成标准|
|-|-|
|Phase1|项目可以运行|
|Phase2|App页面完成|
|Phase3|后端接口完成|
|Phase4|AI可以解析消费|
|Phase5|数据完整保存|
|Phase6|可正常使用|

---

# 4. Codex / Trae 开发原则

## 原则1：不要一次生成整个项目

错误：

```
帮我开发一个AI记账App
```

容易导致：

- 代码混乱
- 无法维护


---

正确：

```
请完成Task 2.1：

开发聊天页面。

要求：
...
```

---

## 原则2：每完成一个Task提交一次

Git：

```
feat: create chat page

feat: add llm service

feat: add expense database
```

---

## 原则3：AI负责编码，人负责决策

AI负责：

- 写代码
- 修Bug
- 重构


你负责：

- 产品设计
- 功能取舍
- 测试验证
- Prompt优化

---

# 5. MVP完成定义

当以下功能完成：

✅ 手机App运行

✅ 用户输入消费

✅ LLM解析

✅ 用户确认

✅ 数据保存

✅ 查看账单


即完成第一版。

---

END
