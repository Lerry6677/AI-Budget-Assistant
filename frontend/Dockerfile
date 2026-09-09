# ============================================================================
# 前端多阶段镜像（阶段 3-3）
# ----------------------------------------------------------------------------
# Stage 1  node:20-alpine  : npm ci + vite build（VITE_API_BASE_URL build-time 烤入）
# Stage 2  nginx:1.27-alpine: 仅托管 dist 静态文件 + /api 反代，运行时零 Node
# 由 docker-compose.server.yml 构建，args 注入 VITE_API_BASE_URL=/api
# ============================================================================

# ---------- Stage 1: build ----------
FROM node:20-alpine AS build
WORKDIR /app

# 依赖层独立缓存：package*.json 不变则 npm ci 命中缓存
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# build-time 变量（vite 在编译期把 import.meta.env.VITE_API_BASE_URL 替换为字面量）
ARG VITE_API_BASE_URL=/api
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

# ---------- Stage 2: nginx ----------
FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
