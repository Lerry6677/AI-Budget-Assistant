# ============================================================================
# AI Budget Assistant —— Backend 镜像（阶段 2-3）
# ----------------------------------------------------------------------------
# 构建上下文 = 仓库根目录，代码落在 /app/backend/，因此 uvicorn 入口必须写
# 包路径 backend.main:app（/app 下并没有 main.py）。
#
# 版本口径：统一到 Python 3.13。阶段 2-2 的 requirements.txt 是在
# Python 3.13.9 (Windows) 上验证通过的（282 passed / 1 failed / 12 skipped），
# 这里用 3.13-slim 消除环境漂移。已实测 3.12 也能装上同一批钉住的直接依赖，
# 但既然验证基线在 3.13，就以 3.13 为准。
# ============================================================================
FROM python:3.13-slim

WORKDIR /app

# PYTHONPATH=/app 是必需的：uvicorn 是 console script，Python 不会把 CWD
# 放进 sys.path，不显式指定就找不到 `backend.main`；pytest 里的
# `import backend.xxx` 同样依赖它。
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

# 先只拷 requirements，让依赖层可以独立缓存（改代码不会触发重装依赖）
COPY backend/requirements.txt ./backend/requirements.txt

RUN pip install --no-cache-dir -r backend/requirements.txt

# 再拷其余源码。实际进镜像的内容由根目录 .dockerignore 决定：
# .env / venv / node_modules / *.sqlite / *.sql / .git 全部被排除。
COPY . .

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
