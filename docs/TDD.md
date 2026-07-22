
# 记账助手 AI 财务管理 App

> 技术设计文档（Technical Design Document）

版本：v1.0
状态：Draft
更新时间：2026-07-22

---

## 目录

* [1. 系统概述](#1-系统概述)
* [2. 整体架构设计](#2-整体架构设计)
* [3. 技术选型](#3-技术选型)
* [4. 前端设计](#4-前端设计)
* [5. 后端设计](#5-后端设计)
* [6. 数据库设计](#6-数据库设计)
* [7. LLM调用设计](#7-llm调用设计)
* [8. Prompt设计](#8-prompt设计)
* [9. API接口设计](#9-api接口设计)
* [10. 项目目录结构](#10-项目目录结构)
* [11. 开发流程](#11-开发流程)

---

## 1. 系统概述

### 1.1 项目简介

记账助手是一款基于大语言模型的移动端 AI 财务管理应用。

用户通过自然语言输入消费信息，系统调用 LLM 完成：

* 消费信息抽取
* 消费分类
* 数据结构化
* 财务分析

最终帮助用户完成个人消费管理。

---

## 2. 系统整体架构设计

整体采用：

> 移动端 + 后端服务 + LLM服务 + 数据库

架构：

```
                 用户

                  |

              UniApp App

                  |

              HTTP API

                  |

              FastAPI

        ---------------------

        |                   |

     LLM服务             数据库

        |

  Prompt + 用户输入

```

---

## 3. 技术选型

### 3.1 前端

技术：

| 技术     | 用途    |
| ------ | ----- |
| UniApp | 移动端开发 |
| Vue3   | 页面开发  |
| Pinia  | 状态管理  |
| Axios  | 接口请求  |
| uView  | UI组件库 |

选择原因：

* Vue基础可以复用
* 一套代码支持多端
* AI生成代码质量较高

---

### 3.2 后端

技术：

| 技术         | 用途    |
| ---------- | ----- |
| Python     | 开发语言  |
| FastAPI    | Web框架 |
| Pydantic   | 数据校验  |
| SQLAlchemy | ORM   |

选择原因：

* AI生态成熟
* 调用LLM方便
* 接口开发简单

---

### 3.3 数据库

第一版：

SQLite

原因：

* 部署简单
* 适合个人项目

后续：

PostgreSQL / MySQL

---

## 4. 前端设计

### 4.1 页面结构

```
pages/

├── chat/
│   └── index.vue

├── bill/
│   └── index.vue

├── analysis/
│   └── index.vue

└── user/
    └── index.vue

```

---

### 4.2 页面功能

#### Chat页面

核心页面。

功能：

* 输入消费
* 展示AI回复
* 确认账单

流程：

```
输入

↓

发送请求

↓

显示AI结果

↓

确认保存

```

---

#### Bill页面

功能：

* 查看账单
* 删除
* 修改

---

#### Analysis页面

功能：

* 月消费统计
* 分类统计
* 趋势展示

---

#### User页面

功能：

* 设置收入
* 设置预算

---

## 5. 后端设计

### 5.1 服务模块

结构：

```
backend/

├── main.py

├── api/
│   ├── chat.py
│   ├── expense.py
│   └── user.py


├── services/

│   ├── llm_service.py
│   ├── expense_service.py
│   └── analysis_service.py


├── models/

│   ├── user.py
│   ├── expense.py
│   └── budget.py


└── database/

    └── db.py

```

---

### 5.2 核心业务流程

用户记账：

```
用户输入

↓

POST /chat

↓

调用LLM

↓

解析JSON

↓

返回消费记录

↓

用户确认

↓

保存数据库

```

---

## 6. 数据库设计

### 6.1 用户表 user

| 字段           | 类型       |
| ------------ | -------- |
| id           | int      |
| username     | string   |
| password     | string   |
| income       | float    |
| created_time | datetime |

---

### 6.2 消费记录表 expense

| 字段       | 类型     |
| -------- | ------ |
| id       | int    |
| user_id  | int    |
| name     | string |
| amount   | float  |
| category | string |
| date     | date   |
| remark   | string |

---

示例：

| name | amount | category |
| ---- | ------ | -------- |
| 早餐   | 4      | 餐饮       |
| 公交   | 4.5    | 交通       |

---

### 6.3 预算表 budget

| 字段       | 类型     |
| -------- | ------ |
| id       | int    |
| user_id  | int    |
| month    | string |
| category | string |
| amount   | float  |

---

## 7. LLM调用设计

### 7.1 调用流程

```
用户输入

↓

Prompt模板

↓

LLM API

↓

JSON结果

↓

业务处理

↓

数据库

```

---

### 7.2 LLM职责

LLM负责：

✅ 理解自然语言

✅ 提取消费信息

✅ 分类

LLM不负责：

❌ 保存数据

❌ 计算统计

❌ 修改数据库

---

## 8. Prompt设计

### 8.1 消费解析Prompt

System：

```
你是一个智能记账助手。

你的任务：
从用户输入中提取消费记录。

要求：
返回JSON格式。

字段：

name:
消费名称

amount:
金额

category:
消费分类

date:
消费日期


规则：

1. 不允许猜测金额
2. 信息不足需要询问用户
3. 分类必须来自指定列表

```

---

User:

```
今天晚上吃火锅68
```

---

AI:

```json
{
"name":"火锅",
"amount":68,
"category":"餐饮"
}
```

---

## 9. API接口设计

### 9.1 AI聊天接口

POST

```
/api/chat
```

请求：

```json
{
"text":"今天午饭16.8"
}
```

返回：

```json
{
"records":[
{
"name":"午饭",
"amount":16.8,
"category":"餐饮"
}
]
}
```

---

### 9.2 保存账单

POST

```
/api/expense
```

请求：

```json
{
"name":"早餐",
"amount":4,
"category":"餐饮"
}
```

---

### 9.3 获取账单

GET

```
/api/expense/list
```

返回：

```json
[
{
"name":"早餐",
"amount":4
}
]
```

---

### 9.4 消费分析

GET

```
/api/analysis/month
```

返回：

```json
{
"total":2500,
"category":{
"餐饮":800,
"交通":200
}
}
```

---

## 10. 项目目录结构

最终：

```
finance-ai-assistant/

├── frontend/

│
├── backend/

│
├── docs/

│   ├── PRD.md
│   └── TDD.md
│
├── prompts/

│   └── expense_parser.md
│
├── README.md

└── .gitignore

```

---

## 11. 开发流程

### Phase 1：完成AI记账闭环

目标：

用户输入一句话

↓

AI解析

↓

保存数据库

---

### Phase 2：完善数据展示

增加：

* 账单列表
* 图表
* 查询

---

### Phase 3：AI增强

增加：

* 预算
* 消费建议
* Agent

---


