# AI Budget Assistant

一个基于大语言模型（LLM）的聊天式智能记账助手。

用户可以通过自然语言描述消费行为，
AI 自动完成消费信息提取、账单记录、消费查询以及个人财务目标管理。

例如：

用户：

> 昨天晚上打车30元，午饭50元

AI：

> 已记录：
>
> 餐饮 - 50元
>
> 交通 - 30元


---

# 项目介绍

传统记账工具通常需要用户主动填写账单，
记录成本较高，导致用户难以长期坚持。

本项目通过 LLM 理解用户自然语言输入，
结合 Workflow 编排和后端服务，
实现类似聊天助手的智能记账体验。


---

# 核心功能

## AI自然语言记账

支持：

> 昨天晚上打车30元，吃饭50元


自动解析：

- 消费类别
- 消费金额
- 消费描述
- 消费时间


支持：

- 单笔消费记录
- 一次输入多笔消费


---

## 消费查询与分析

支持：

- 查询历史消费记录
- 按时间范围查询
- 消费统计
- 分类消费分析


---

## 用户长期画像 Memory

支持保存用户长期财务信息：

- 存款目标
- 财务目标


例如：

用户：

> 我要存钱买电脑


系统记录用户长期目标，
后续对话可以继续使用。


---

# 系统架构

                 User
                   |
                   |
              FastAPI
                   |
              JWT Auth
                   |
              Dify Workflow
                   |
        ---------------------
        |          |         |
      LLM       Memory    Tools
        |          |         |
   结构化解析   Profile   Agent API
                              |
                          MySQL



---

# Workflow设计


当前版本采用 Dify Workflow 编排：



用户输入

↓

意图识别

↓

LLM结构化解析

↓

调用 Backend Agent API

↓

MySQL数据存储

↓

生成回复



Memory流程：



用户信息提取

↓

查询已有用户画像

↓

LLM合并更新

↓

保存用户画像



---

# Tech Stack


## Backend

- FastAPI
- SQLAlchemy
- MySQL
- JWT Authentication


## AI

- Dify Workflow
- Qwen LLM
- Prompt Engineering
- Structured Output


## Deployment

- Docker


---

# API设计


## Agent API


### 消费记录


POST /agent/expense


用于 AI 写入用户消费记录。


### 消费查询


GET /agent/expense/query


用于 AI 查询用户历史消费。


### 用户画像


GET /agent/profile

POST /agent/profile


用于管理用户长期财务目标。


---

# 项目状态

当前版本：

## Workflow MVP v1.0


已完成：

- [x] 用户认证系统
- [x] FastAPI 后端
- [x] Dify Workflow 接入
- [x] 用户身份传递
- [x] LLM消费信息结构化解析
- [x] 多笔消费记录
- [x] 消费时间解析
- [x] 消费数据存储
- [x] 消费查询接口
- [x] 用户长期画像 Memory


---

# Roadmap


## Agent 化升级

- [ ] Workflow 转 Agent
- [ ] Tool Calling
- [ ] Agent自主选择工具


## Memory优化

- [ ] 多财务目标支持
- [ ] 更智能的用户画像更新策略


## 应用层

- [ ] UniApp移动端
- [ ] 数据可视化
- [ ] Docker完整部署
