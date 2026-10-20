# 城市 GDP 数据分析

采集纽约、伦敦、东京、新加坡、北京、上海、深圳、香港 8 个城市在 2000–2025 年 9 个节点上的经济总量数据，按统一口径折算美元，计算 **区域GDP、经济首位度、人均GDP、地均GDP** 四项指标。

## 文档

| 文档 | 内容 |
|---|---|
| [INIT.md](INIT.md) | 初始需求与候选数据源 |
| [SPEC.md](SPEC.md) | 需求规格：口径、公式、来源要求、交付物、验收标准 |
| [DESIGN.md](DESIGN.md) | 实现设计：采集通道、原始数据留存、数据库、目录结构 |
| [PLAN.md](PLAN.md) | 分步实施计划（S1–S7） |

**当前状态**：S1–S7 全部完成，交付物已生成在 `output/`。

## 快速开始

```bash
uv sync                 # 安装依赖（Python 3.12）
uv run citygdp doctor   # 配置与数据库自检
uv run pytest -q        # 约束与配置测试
```

数据采集命令：

```bash
uv run citygdp fetch --source all     # 下载原始数据到 data/raw
uv run citygdp ingest --source all    # 解析入 fact 表
uv run citygdp build                  # 计算派生指标
uv run citygdp validate               # 规则校验
uv run citygdp export                 # 生成 output/*
```

## 目录

```
config/       城市、参数、校验锚点（口径的唯一定义处）
data/raw/     不可变原始数据（按 source_id 分版本）
data/manual/  手工下载投递区
data/db/      SQLite 中间库（可重建）
src/citygdp/  代码：adapters / build / validate / export
tests/        schema 约束与配置测试
output/       交付物与逐步验收记录
```

## 口径要点

- 一律**现价**，按**世界银行年度平均汇率**折算美元；国家 GDP 同用世界银行。
- 缺失值**留空**，不插值、不外推。
- 东京为日本年度（4 月–翌年 3 月），按起始年对齐。
- 深圳 2024 年起含深汕特别合作区，不作历史回溯。
- 每个数值可追溯到来源登记表中的一条记录与 `data/raw` 下的原始文件。
