# 记账助手 AI 财务管理 Agent / App

> 技术设计文档（Technical Design Document）

版本：v1.1  
状态：Draft  
作者：Lerry  
更新时间：2026-08-21

---

## 目录

- [1. 系统概述](#1-系统概述)
- [2. 系统整体架构设计](#2-系统整体架构设计)
- [3. 技术选型](#3-技术选型)
- [4. AI Agent架构设计](#4-ai-agent架构设计)
- [5. Agent Workflow设计](#5-agent-workflow设计)
- [6. FastAPI工具服务设计](#6-fastapi工具服务设计)
- [7. 数据库与Memory设计](#7-数据库与memory设计)
- [8. LLM调用设计](#8-llm调用设计)
- [9. Prompt设计](#9-prompt设计)
- [10. API接口设计](#10-api接口设计)
- [11. 前端设计](#11-前端设计)
- [12. 项目目录结构](#12-项目目录结构)
- [13. 开发流程](#13-开发流程)

---

## 1. 系统概述

### 1.1 项目简介

记账助手是一款基于大语言模型的个人财务管理 AI Agent。

用户可以通过自然语言描述消费行为，由 AI Agent 完成：

- 消费信息提取
- 消费分类
- 时间解析
- 消费记录保存
- 历史账单查询
- 消费统计
- 消费分析
- 预算规划

系统通过 MySQL 保存用户历史财务数据，为 Agent 提供长期记忆能力。

未来通过 UniApp 将 AI Agent 封装为移动端应用，为用户提供完整的个人财务管理体验。

---

### 1.2 系统设计目标

系统核心目标是构建一个：

> 能够理解用户自然语言、调用外部工具、访问长期记忆，并基于历史财务数据进行分析的 AI 财务 Agent。

系统不采用单纯的：

```text
用户 → LLM → 回复
````

而采用：

```text
用户
 ↓
AI Agent
 ↓
LLM
 ↓
Tool Calling
 ↓
FastAPI
 ↓
MySQL
```

其中：

* LLM 负责理解、推理和决策
* Dify 负责 Agent Workflow 编排
* FastAPI 负责工具服务和业务接口
* MySQL 负责数据持久化和长期记忆

---

## 2. 系统整体架构设计

### 2.1 当前阶段架构

当前阶段优先开发 AI Agent 核心能力，暂不开发移动端。

```text
                    用户
                     |
                     ↓
              Dify Agent / Workflow
                     |
                     ↓
                    LLM
                     |
          -------------------------
          |                       |
          ↓                       ↓
      信息解析                 Tool Calling
                                  |
                                  ↓
                               FastAPI
                                  |
                                  ↓
                                MySQL
```

---

### 2.2 最终应用架构

移动端开发完成后：

```text
                    UniApp
                       |
                       ↓
                  FastAPI Backend
                       |
                       ↓
                 Dify Agent
                       |
              -----------------
              |               |
              ↓               ↓
             LLM          Tool Service
                              |
                              ↓
                            MySQL
```

---

### 2.3 系统分层

系统划分为三个核心层。

#### AI Agent 层

负责：

* 自然语言理解
* 意图识别
* 消费信息提取
* 工具选择
* 数据分析
* 自然语言回复

技术：

```text
Dify + LLM
```

---

#### Tool Service 层

负责：

* 提供 Agent 可以调用的工具
* 数据校验
* 业务逻辑
* 数据库访问

技术：

```text
FastAPI + SQLAlchemy
```

---

#### Memory 层

负责：

* 保存消费记录
* 保存用户财务数据
* 查询历史数据
* 为 Agent 提供长期记忆

技术：

```text
MySQL
```

---

## 3. 技术选型

### 3.1 AI Agent

| 技术                 | 用途                  |
| ------------------ | ------------------- |
| Dify               | Agent / Workflow 编排 |
| LLM                | 自然语言理解与推理           |
| Prompt Engineering | 控制模型行为              |
| Structured Output  | 消费信息结构化             |
| Tool Calling       | 调用外部工具              |

---

### 3.2 Backend

| 技术         | 用途                    |
| ---------- | --------------------- |
| Python     | 后端开发语言                |
| FastAPI    | Web 框架 / Tool Service |
| Pydantic   | 请求参数和数据校验             |
| SQLAlchemy | ORM                   |
| PyMySQL    | MySQL 数据库驱动           |

---

### 3.3 Database

第一版本直接使用：

```text
MySQL
```

MySQL 主要负责：

* 消费记录持久化
* 用户数据持久化
* 财务数据查询
* Agent 长期记忆

---

### 3.4 Frontend

后续开发：

| 技术     | 用途      |
| ------ | ------- |
| UniApp | 跨平台移动端  |
| Vue3   | 页面开发    |
| Pinia  | 状态管理    |
| Axios  | HTTP 请求 |
| uView  | UI 组件   |

---

## 4. AI Agent 架构设计

### 4.1 Agent 职责

Agent 负责：

1. 理解用户自然语言
2. 判断用户意图
3. 提取消费信息
4. 判断是否需要补充信息
5. 决定是否调用工具
6. 选择需要调用的工具
7. 根据工具返回的数据进行分析
8. 生成自然语言回复

---

### 4.2 LLM 职责边界

LLM 负责：

```text
理解
推理
分类
意图识别
信息提取
结果总结
```

LLM 不直接负责：

```text
数据库连接
SQL执行
数据持久化
数据真实性保证
```

这些职责交给 FastAPI 和 MySQL。

---

### 4.3 Agent 与 Tool 的关系

```text
                  AI Agent
                     |
        -----------------------------
        |             |             |
        ↓             ↓             ↓
 save_expense   query_expenses   get_expense_summary
        |             |             |
        -----------------------------
                     |
                     ↓
                  FastAPI
                     |
                     ↓
                   MySQL
```

---

## 5. Agent Workflow 设计

### 5.1 记账 Workflow

```text
用户输入
   ↓
Start
   ↓
LLM
   ↓
提取消费信息
   ↓
判断是否存在多笔消费
   ↓
Iteration
   ↓
HTTP Request
   ↓
FastAPI
   ↓
MySQL
   ↓
返回保存结果
   ↓
LLM生成反馈
   ↓
End
```

---

### 5.2 多笔消费处理

用户：

```text
今天早餐8元，午饭25元，打车20元
```

LLM 输出：

```json
{
  "expenses": [
    {
      "category": "餐饮",
      "amount": 8,
      "description": "早餐",
      "time": "今天"
    },
    {
      "category": "餐饮",
      "amount": 25,
      "description": "午饭",
      "time": "今天"
    },
    {
      "category": "交通",
      "amount": 20,
      "description": "打车",
      "time": "今天"
    }
  ]
}
```

Iteration 对每条消费记录分别调用：

```text
save_expense()
```

最终 MySQL 保存 3 条消费记录。

---

### 5.3 查询 Workflow

用户：

```text
我这个月花了多少钱？
```

处理流程：

```text
用户输入
   ↓
Agent
   ↓
判断意图
   ↓
query_expenses
   ↓
FastAPI
   ↓
MySQL
   ↓
返回查询结果
   ↓
LLM总结
   ↓
自然语言回答
```

---

### 5.4 分析 Workflow

用户：

```text
分析一下我这个月的消费
```

处理流程：

```text
用户输入
   ↓
Agent
   ↓
判断意图
   ↓
get_expense_summary
   ↓
FastAPI
   ↓
MySQL聚合查询
   ↓
返回统计数据
   ↓
LLM分析
   ↓
生成消费建议
```

---

## 6. FastAPI 工具服务设计

FastAPI 作为 Agent 的工具服务层。

---

### 6.1 保存消费工具

工具名称：

```text
save_expense
```

功能：

将 Agent 解析出的消费记录保存到 MySQL。

输入：

```json
{
  "user_id": "user001",
  "category": "餐饮",
  "amount": 15,
  "description": "午饭",
  "expense_time": "2026-08-21"
}
```

---

### 6.2 查询消费工具

工具名称：

```text
query_expenses
```

功能：

根据用户、时间范围、类别等条件查询历史消费。

支持：

* 指定日期
* 时间范围
* 月度查询
* 分类查询

---

### 6.3 消费统计工具

工具名称：

```text
get_expense_summary
```

功能：

获取：

* 总消费金额
* 消费笔数
* 分类金额
* 分类占比
* 日均消费

---

### 6.4 工具调用原则

```text
LLM / Agent
    ↓
决定调用哪个工具

FastAPI
    ↓
执行具体业务逻辑

MySQL
    ↓
保存 / 查询真实数据
```

Agent 不直接操作数据库。

---

## 7. 数据库与 Memory 设计

### 7.1 Memory 设计原则

MySQL 作为 Agent 的长期事实记忆。

```text
LLM
负责：
理解 / 推理 / 决策

MySQL
负责：
历史数据 / 事实 / 长期记忆
```

数据库中的数据属于用户真实财务数据，不应该由 LLM 虚构。

---

### 7.2 expenses 表

```sql
CREATE TABLE expenses (
    id INT PRIMARY KEY AUTO_INCREMENT,
    user_id VARCHAR(64) NOT NULL,
    category VARCHAR(50) NOT NULL,
    amount DECIMAL(10,2) NOT NULL,
    description VARCHAR(255),
    expense_time DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

### 7.3 字段说明

| 字段           | 类型            | 说明      |
| ------------ | ------------- | ------- |
| id           | INT           | 消费记录 ID |
| user_id      | VARCHAR(64)   | 用户 ID   |
| category     | VARCHAR(50)   | 消费类别    |
| amount       | DECIMAL(10,2) | 消费金额    |
| description  | VARCHAR(255)  | 消费描述    |
| expense_time | DATE          | 消费日期    |
| created_at   | TIMESTAMP     | 数据创建时间  |

---

### 7.4 数据设计原则

#### 金额

使用：

```text
DECIMAL(10,2)
```

不使用：

```text
FLOAT
```

避免金额计算产生浮点精度问题。

---

#### 时间

消费时间使用：

```text
expense_time
```

创建时间使用：

```text
created_at
```

二者区分：

```text
expense_time
= 用户实际消费时间

created_at
= 系统保存记录的时间
```

---

### 7.5 用户数据隔离

所有消费数据必须关联：

```text
user_id
```

查询数据时必须根据：

```text
user_id
```

进行过滤。

避免不同用户之间的数据混淆。

---

### 7.6 后续数据库扩展

未来可以增加：

```text
users
expenses
income
budgets
financial_goals
user_preferences
```

用于构建更加完整的个人财务画像。

---

## 8. LLM 调用设计

### 8.1 消费解析

```text
用户输入
   ↓
Dify
   ↓
LLM
   ↓
Structured JSON
```

例如：

```text
今天午饭16.8元
```

输出：

```json
{
  "expenses": [
    {
      "category": "餐饮",
      "amount": 16.8,
      "description": "午饭",
      "time": "今天"
    }
  ]
}
```

---

### 8.2 查询

```text
用户问题
   ↓
Agent
   ↓
判断查询意图
   ↓
调用 query_expenses
   ↓
FastAPI
   ↓
MySQL
   ↓
查询结果
   ↓
LLM
   ↓
自然语言回答
```

---

### 8.3 分析

```text
用户问题
   ↓
Agent
   ↓
调用 get_expense_summary
   ↓
MySQL聚合查询
   ↓
统计结果
   ↓
LLM分析
   ↓
生成消费建议
```

---

### 8.4 LLM 与数据库的数据边界

LLM 可以：

```text
理解用户输入
判断查询条件
分析数据库返回的数据
```

LLM 不应该：

```text
自己编造数据库数据
自己计算数据库事实
假设不存在的消费记录
```

涉及历史消费事实时，应优先使用数据库返回的数据。

---

## 9. Prompt 设计

### 9.1 消费解析 Prompt

System Prompt：

```text
你是一个智能记账助手。

你的任务是从用户自然语言中提取消费记录。

需要提取：

- category
- amount
- description
- time

规则：

1. 识别到金额即可记录。
2. 多笔消费必须拆分为多条记录。
3. 不允许猜测金额。
4. 如果完全没有金额，需要提醒用户补充。
5. 根据消费描述判断消费分类。
6. 用户没有明确提供时间时，不要虚构具体日期。
7. 输出必须符合指定JSON结构。
```

---

### 9.2 消费分类

默认分类：

```text
餐饮
饮品
交通
购物
娱乐
学习
住房
医疗
其他
```

---

### 9.3 查询意图

Agent 根据用户输入判断：

```text
record
query
analysis
```

例如：

```text
我这个月花了多少钱？
```

判断：

```text
intent = query
```

然后调用：

```text
query_expenses
```

---

### 9.4 分析意图

例如：

```text
我最近是不是花太多了？
```

判断：

```text
intent = analysis
```

然后：

```text
get_expense_summary
```

获取真实数据后，再由 LLM 进行分析。

---

## 10. API 接口设计

当前阶段 API 主要作为 Agent Tool。

---

### 10.1 保存消费

```http
POST /expense
```

请求：

```json
{
  "user_id": "user001",
  "category": "餐饮",
  "amount": 15,
  "description": "午饭",
  "expense_time": "2026-08-21"
}
```

返回：

```json
{
  "success": true,
  "message": "记账成功",
  "expense_id": 1
}
```

---

### 10.2 查询消费

```http
GET /expense
```

请求参数：

```text
user_id
start_date
end_date
category
```

示例：

```text
GET /expense?user_id=user001&start_date=2026-08-01&end_date=2026-08-21
```

返回：

```json
{
  "expenses": [
    {
      "id": 1,
      "category": "餐饮",
      "amount": 15,
      "description": "午饭",
      "expense_time": "2026-08-21"
    }
  ]
}
```

---

### 10.3 消费统计

```http
GET /expense/summary
```

请求参数：

```text
user_id
start_date
end_date
```

返回：

```json
{
  "total_amount": 487.5,
  "expense_count": 10,
  "category_summary": {
    "餐饮": 250,
    "交通": 80,
    "购物": 100,
    "娱乐": 57.5
  }
}
```

---

### 10.4 删除消费

```http
DELETE /expense/{expense_id}
```

用于后续账单管理功能。

---

### 10.5 修改消费

```http
PUT /expense/{expense_id}
```

用于后续账单管理功能。

---

## 11. 前端设计

前端作为后续阶段开发。

---

### 11.1 Chat 页面

核心页面。

功能：

* AI聊天
* 自然语言记账
* 账单查询
* 消费分析
* 财务建议

---

### 11.2 Bill 页面

功能：

* 查看历史账单
* 日期筛选
* 分类筛选
* 修改账单
* 删除账单

---

### 11.3 Analysis 页面

功能：

* 月度消费
* 分类占比
* 消费趋势
* AI消费分析

---

### 11.4 User 页面

功能：

* 收入设置
* 预算设置
* 财务目标
* 用户偏好

---

## 12. 项目目录结构

```text
AI-Budget-Assistant/

├── backend/
│   │
│   ├── app/
│   │   ├── main.py
│   │   │
│   │   ├── crud.py
│   │   │
│   │   ├── models.py
│   │   │
│   │   ├── schemas.py
│   │   │
│   │   ├── services/
│   │   │   ├── expense_service.py
│   │   │   └── analysis_service.py
│   │   │
│   │   └── database.py
│   │   
│   │
│   ├── requirements.txt
│   └── .env
│
├── dify/
│   │
│   ├── workflows/
│   │   ├── record_expense.md
│   │   ├── query_expense.md
│   │   └── analyze_expense.md
│   │
│   └── prompts/
│       └── expense_parser.md
│
├── frontend/
│   └── uniapp/
│
├── docs/
│   ├── PRD.md
│   └── TDD.md
│
├── README.md
│
└── .gitignore
```

---

## 13. 开发流程

### Phase 1：AI Agent 基础能力

目标：

> 让 Agent 能够理解自然语言消费描述。

完成：

* Dify Workflow
* LLM配置
* Prompt设计
* 消费信息提取
* 自动分类
* 多笔消费解析
* 时间识别
* Structured Output

---

### Phase 2：数据库与长期 Memory

目标：

> 让 Agent 真正拥有长期记忆。

完成：

* MySQL数据库
* expenses表
* FastAPI项目
* SQLAlchemy
* MySQL连接
* save_expense接口
* Dify HTTP Request
* 多笔消费循环保存

---

### Phase 3：查询能力

目标：

> 让 Agent 能访问自己的历史记忆。

完成：

* query_expenses接口
* 日期查询
* 月度查询
* 时间范围查询
* 分类查询
* 自然语言查询

---

### Phase 4：财务分析

目标：

> 从“AI记账工具”升级为“AI财务助手”。

完成：

* 消费总额统计
* 分类统计
* 分类占比
* 日均消费
* 消费趋势
* 消费变化分析
* AI消费建议

---

### Phase 5：预算与规划

目标：

> 让 Agent 能够帮助用户进行主动财务管理。

完成：

* 收入管理
* 预算设置
* 分类预算
* 预算执行情况
* 超预算提醒
* 存钱目标
* 财务规划

---

### Phase 6：移动端应用

目标：

> 将 AI Agent 封装为完整移动端应用。

完成：

* UniApp项目
* Vue3
* AI聊天页面
* 账单页面
* 分析页面
* 用户中心
* 后端接口接入

---

### Phase 7：高级 AI 能力

后续探索：

* OCR账单识别
* 多Agent架构
* RAG
* 个性化财务画像
* 主动式财务提醒

---

## 14. 系统核心设计原则

### 14.1 Agent负责决策

Agent负责：

```text
理解用户
 ↓
判断意图
 ↓
选择工具
 ↓
分析结果
```

---

### 14.2 Tool负责执行

FastAPI负责：

```text
接收参数
 ↓
校验数据
 ↓
执行业务逻辑
 ↓
访问数据库
 ↓
返回结果
```

---

### 14.3 Database负责事实与记忆

MySQL负责：

```text
真实消费记录
历史数据
统计数据
长期记忆
```

---

### 14.4 LLM不应该成为数据库

LLM不能作为：

```text
消费记录存储
金额事实来源
历史数据来源
```

数据库才是财务事实的唯一可信来源。

---

## 15. 项目核心架构总结

最终系统形成：

```text
                         用户
                           |
                           ↓
                      UniApp / Web
                           |
                           ↓
                     AI Agent
                           |
                    Dify + LLM
                           |
                 ┌─────────┴─────────┐
                 ↓                   ↓
              推理决策             Tool Calling
                                     |
                                     ↓
                                  FastAPI
                                     |
                                     ↓
                                  MySQL
                                     |
                                     ↓
                              长期财务记忆
                                     |
                                     ↓
                              返回真实数据
                                     |
                                     ↓
                                  LLM分析
                                     |
                                     ↓
                              自然语言回复
```

核心职责划分：

| 模块         | 核心职责                |
| ---------- | ------------------- |
| Dify       | Agent Workflow 编排   |
| LLM        | 理解、推理、决策、分析         |
| FastAPI    | Tool Service / 业务接口 |
| SQLAlchemy | ORM / 数据访问          |
| MySQL      | 数据持久化 / 长期 Memory   |
| UniApp     | 移动端用户界面             |

---

## END

```
