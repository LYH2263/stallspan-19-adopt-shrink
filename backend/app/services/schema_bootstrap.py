"""启动期幂等结构补齐。

Base.metadata.create_all 只会建缺失的表，不会给已存在的 market_days 补列，也不会改旧种子数据。
这里用 inspector 预检后做方言无关的 ALTER TABLE，并把默认可分配时段窗回填给历史行。
全新库（create_all 已带列）与测试库（直接 create_all）下都安全可重复执行。
"""
from __future__ import annotations
from datetime import datetime

from sqlalchemy import DateTime, inspect, text
from sqlalchemy.engine import Engine

# 历史数据与种子默认窗：覆盖演示当天（2026-10-01）。
DEFAULT_OPEN = datetime(2026, 9, 20, 0, 0, 0)
DEFAULT_CLOSE = datetime(2026, 12, 31, 23, 59, 59)


def ensure_schema(engine: Engine) -> None:
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    if "market_days" in table_names:
        existing = {col["name"] for col in inspector.get_columns("market_days")}
        add_cols = []
        if "alloc_open_at" not in existing:
            add_cols.append("alloc_open_at")
        if "alloc_close_at" not in existing:
            add_cols.append("alloc_close_at")
        with engine.begin() as conn:
            datetime_type = DateTime().compile(dialect=engine.dialect)
            for col in add_cols:
                # 方言编译：Postgres -> TIMESTAMP，SQLite -> DATETIME。
                conn.execute(text(f"ALTER TABLE market_days ADD COLUMN {col} {datetime_type}"))
            if add_cols:
                conn.execute(
                    text(
                        "UPDATE market_days SET alloc_open_at = :open_at, "
                        "alloc_close_at = :close_at WHERE alloc_open_at IS NULL"
                    ),
                    {"open_at": DEFAULT_OPEN, "close_at": DEFAULT_CLOSE},
                )
