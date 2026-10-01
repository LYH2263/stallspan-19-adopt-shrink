# StallSpan 市集摊档开间

沿街段一维 First-Fit 开间分配，挡柱不可被摊位跨越，输出分配图与放不下清单。

技术栈：Python 3.12 / FastAPI / SQLAlchemy / PostgreSQL / Vue 3 / TypeScript / Vite

## 启动

```bash
docker compose up --build
```

| 服务 | 地址 |
| --- | --- |
| 前端 | http://localhost:4700 |
| API | http://localhost:9700 |
| API 文档 | http://localhost:9700/docs |
| Postgres | localhost:5448 |

健康检查：`GET http://localhost:9700/api/health`

## 使用说明

1. 在「集日」「街段」确认开市日、可分配时段窗与可用宽度。
2. 在「摊主」「挡柱」维护需求宽度（登记优先只读）与障碍位置。
3. 打开「分配带」查看一维开间现算（不写运行行）。
4. 在「放不下」对某摊点「让路」：不改摊宽，仅把目标柱间内邻摊的本轮临时优先压低后重算；
   让路只写草稿、不产生运行行，主图/放不下/临时优先三处始终同一套结论。
5. 在「分配带」点「确认落库」正式落一条运行行：仅在集日可分配时段窗内、且无同类写闸时生效，
   结论未变时确认幂等不增行；「重置让路」清空临时优先回到基线。

### 分配接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/allocate/state` | 现算结论（含本轮临时优先），纯读 |
| POST | `/api/allocate/yield/{vendor_id}` | 对某放不下摊位让路，零写运行行；失败 409 |
| POST | `/api/allocate/reset` | 清空临时优先回基线 |
| POST | `/api/allocate/confirm` | 过时段窗+写闸后幂等落一条运行行 |
| GET | `/api/allocate/latest` | 最近一条正式运行，无则 `null`（纯读） |

## 开发与测试

```bash
docker compose exec api pytest -q
```
