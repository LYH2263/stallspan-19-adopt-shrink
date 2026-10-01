from datetime import date, datetime
from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

class MarketDay(Base):
    __tablename__ = "market_days"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    day: Mapped[date] = mapped_column(Date)
    # 可分配时段窗（naive UTC，与现有 DateTime 列一致）。NULL 表示未配置，confirm 一律拒绝。
    alloc_open_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    alloc_close_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

class Segment(Base):
    __tablename__ = "segments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    market_day_id: Mapped[int] = mapped_column(ForeignKey("market_days.id"))
    name: Mapped[str] = mapped_column(String(64))
    width_m: Mapped[float] = mapped_column(Float)

class Vendor(Base):
    __tablename__ = "vendors"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    market_day_id: Mapped[int] = mapped_column(ForeignKey("market_days.id"))
    name: Mapped[str] = mapped_column(String(64))
    stall_width_m: Mapped[float] = mapped_column(Float)
    # 登记优先：只读，永不因让路被改写。让路的临时优先只存 AllocationDraft.overrides_json。
    priority: Mapped[int] = mapped_column(Integer, default=1)

class Pillar(Base):
    __tablename__ = "pillars"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    segment_id: Mapped[int] = mapped_column(ForeignKey("segments.id"))
    position_m: Mapped[float] = mapped_column(Float)
    thickness_m: Mapped[float] = mapped_column(Float, default=0.4)
    label: Mapped[str] = mapped_column(String(32), default="挡柱")

class AllocationRun(Base):
    __tablename__ = "allocation_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    segment_id: Mapped[int] = mapped_column(ForeignKey("segments.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    result_json: Mapped[str] = mapped_column(Text, default="{}")

class AllocationDraft(Base):
    """每条街段至多一行：本轮临时优先覆盖 + 最近一次让路/重置成功后的结论快照。

    overrides_json: {"<vendor_id>": 临时优先(float)}；未列到的摊主沿用登记 priority。
    result_json   : 仅作审计/展示快照，confirm 不读它，一律用库内数据实时重算。
    让路只写本表，绝不写 allocation_runs；运行行仅 confirm 成功后落一条。
    """
    __tablename__ = "allocation_drafts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    segment_id: Mapped[int] = mapped_column(ForeignKey("segments.id"), unique=True)
    overrides_json: Mapped[str] = mapped_column(Text, default="{}")
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
