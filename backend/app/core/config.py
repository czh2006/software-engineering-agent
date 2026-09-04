"""应用配置。

使用 pydantic-settings 从环境变量 / .env 文件加载配置，
所有配置项均有类型标注与默认值。
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局应用设置（Pydantic v2）。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 应用
    app_name: str = "AI Software Engineering Agent"
    environment: str = "development"
    debug: bool = False

    # 服务
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000

    # 跨域
    cors_origins: list[str] = ["http://localhost:3000"]

    # 数据库 / 缓存
    database_url: str = (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/"
        "software_engineering_agent"
    )
    # 宿主 6379 被 VMware vmnat 占用，Docker Redis 映射到 16379
    redis_url: str = "redis://localhost:16379/0"

    # OpenAI 兼容端点（从 OPENAI_BASE_URL / OPENAI_API_KEY / OPENAI_MODEL 或 .env 读取）
    openai_base_url: str = "https://api.deepseek.com"
    openai_api_key: str | None = None
    openai_model: str = "deepseek-v4-flash"


@lru_cache
def get_settings() -> Settings:
    """返回全局单例配置（带缓存）。"""
    return Settings()
