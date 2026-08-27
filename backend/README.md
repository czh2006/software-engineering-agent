# Backend — FastAPI 服务

AI Software Engineering Agent 的后端服务。

## 技术栈

- FastAPI · Python 3.12+ · Poetry · Pydantic v2 · Uvicorn
- PostgreSQL(asyncpg)· Redis

## 目录结构

```
backend/
├── app/
│   ├── api/         # API 路由（routes/ 下按模块组织）
│   ├── core/        # 核心配置（config.py）
│   ├── models/      # 数据模型（SQLAlchemy ORM）
│   ├── schemas/     # Pydantic 请求/响应模型
│   └── services/    # 业务逻辑服务层
├── pyproject.toml   # 依赖与项目配置（Poetry）
└── Dockerfile
```

## 本地开发

```bash
poetry install          # 安装依赖（虚拟环境在 backend/.venv）
poetry run uvicorn app.main:app --reload   # 或 make backend
```

- API 文档：http://localhost:8000/docs
- 健康检查：http://localhost:8000/api/v1/health
