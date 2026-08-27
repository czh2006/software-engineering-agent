# ============================================================
# AI Software Engineering Agent — 开发命令
# ============================================================

.PHONY: help install dev backend frontend docker docker-up docker-down docker-build docker-logs clean

help:
	@echo "可用命令："
	@echo "  make install      安装 backend 与 frontend 依赖"
	@echo "  make dev          一键启动完整栈（docker compose up --build）"
	@echo "  make backend      本地启动后端（uvicorn --reload，http://localhost:8000/docs）"
	@echo "  make frontend     本地启动前端（next dev，http://localhost:3000）"
	@echo "  make docker       构建并启动全部 Docker 服务（前台）"
	@echo "  make docker-up    后台启动全部 Docker 服务"
	@echo "  make docker-down  停止全部 Docker 服务"
	@echo "  make docker-build 构建 Docker 镜像"
	@echo "  make docker-logs  查看 Docker 日志"
	@echo "  make clean        停止并删除容器与数据卷"

install:
	cd backend && poetry install
	cd frontend && npm install

dev:
	docker compose up --build

backend:
	cd backend && poetry run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

frontend:
	cd frontend && npm run dev

docker:
	docker compose up --build

docker-up:
	docker compose up -d

docker-down:
	docker compose down

docker-build:
	docker compose build

docker-logs:
	docker compose logs -f

clean:
	docker compose down -v
