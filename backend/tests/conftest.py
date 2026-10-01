import os

# 必须在导入 app.*（app.database 会按 settings 建 engine）之前换成 sqlite，
# 避免在无 psycopg2 的测试环境解析 Postgres 方言；生产容器仍由 DATABASE_URL 指向 Postgres。
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.models import AllocationDraft, AllocationRun, MarketDay, Pillar, Segment, Vendor
from app.services import allocation_service as svc

# 单连接内存库：StaticPool 让 TestClient 线程池与测试线程共享同一个 :memory: SQLite。
engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)


def _override_get_db():
    s = TestingSessionLocal()
    try:
        yield s
    finally:
        s.close()


app.dependency_overrides[get_db] = _override_get_db

# 测试默认给一个极宽窗，默认 now 永远在窗内；窗外分支用显式 now 注入触发。
GREEN_VENDORS = [
    ("阿强烧烤", 4.0, 1), ("林记糖水", 3.0, 1), ("老周水果", 5.0, 2),
    ("小美饰品", 2.5, 2), ("大碗面", 6.0, 1), ("手作皮具", 3.5, 3),
    ("巨型舞台车", 12.0, 9), ("流浪咖啡车", 9.0, 8),
]


def _reset_world():
    s = TestingSessionLocal()
    try:
        for model in (AllocationRun, AllocationDraft, Vendor, Pillar, Segment, MarketDay):
            for row in s.query(model).all():
                s.delete(row)
        s.commit()
        day = MarketDay(id=1, name="周末夜市", day=datetime(2026, 9, 20).date(),
                        alloc_open_at=datetime(2020, 1, 1),
                        alloc_close_at=datetime(2100, 1, 1))
        s.add(day)
        s.add(Segment(id=1, market_day_id=1, name="东街段", width_m=30.0))
        s.add(Pillar(id=1, segment_id=1, position_m=10.0, thickness_m=0.5, label="灯柱A"))
        s.add(Pillar(id=2, segment_id=1, position_m=20.0, thickness_m=0.5, label="灯柱B"))
        for i, (name, wdt, pri) in enumerate(GREEN_VENDORS, start=1):
            s.add(Vendor(id=i, market_day_id=1, name=name, stall_width_m=wdt, priority=pri))
        s.commit()
    finally:
        s.close()


@pytest.fixture(autouse=True)
def green_world():
    _reset_world()
    # 清空进程内写闸注册表，避免跨用例残留。
    with svc._locks_guard:
        svc._locks.clear()
    yield


@pytest.fixture
def db():
    s = TestingSessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def client():
    # 不进入 with（不触发 lifespan），避免连真实库；表与夹具已在内存库就绪。
    return TestClient(app)
