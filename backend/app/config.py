from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")
    database_url: str = "postgresql+psycopg2://stallspan:stallspan@localhost:5448/stallspan"
    seed_on_empty: bool = True
    # 可分配时段窗：相对集日 [day - days_before, day + days_after]（含端点）
    allocation_days_before: int = 30
    allocation_days_after: int = 30


settings = Settings()
