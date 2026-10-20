# DESIGN.md — 城市 GDP 数据分析：实现设计文档

| 项目 | 内容 |
|---|---|
| 文档版本 | v1.0 |
| 状态 | 待确认 |
| 编制日期 | 2026-10-20 |
| 上游文档 | `SPEC.md`（需求基线） |
| 下游文档 | `PLAN.md`（实施步骤） |

---

## 1. 设计目标与原则

| 原则 | 含义 | 落地方式 |
|---|---|---|
| 单一事实来源 | 原始文件是唯一权威 | `data/raw` 只增不改，任何清洗结果可重建 |
| 离线可重建 | 无网络也能产出交付物 | `build/validate/export` 只读 `data/raw` 与 SQLite |
| 全链路可追溯 | 每个数字能回到一行原始记录 | `fact.source_id` 外键；登记表含 URL/表号/哈希 |
| 幂等 | 重复执行结果不变 | `fetch` 覆盖同版本；`fact` 按唯一键 upsert；`derived` 全量重算 |
| 配置驱动 | 城市、年份、单位、阈值不写死 | `config/*.yaml` |
| 半自动友好 | 官方站点不可自动化时不阻塞 | `data/manual` 投递区 + 同一套 parser |

**明确不做**：爬虫框架、调度系统、Web 服务、实时更新。这是一次性数据工程。

---

## 2. 总体架构

```
        远端数据源                       本地不可变区              中间层                产出
┌──────────────────────┐        ┌────────────────────┐   ┌──────────────┐   ┌──────────────┐
│ WB API               │        │ data/raw/<sid>/    │   │              │   │ output/      │
│ BEA ZIP              │ fetch  │   <原始文件>        │   │  SQLite      │   │  *.xlsx      │
│ Census CSV           │ ─────► │   manifest.json    │──►│  fact        │──►│  *.md        │
│ ONS xlsx             │        │   (url/etag/hash)  │   │  derived     │   │              │
│ SingStat JSON        │        └────────────────────┘   │  issue       │   └──────────────┘
│ HK C&SD CSV/JSON     │                 │               └──────────────┘
│ 东京都 API/Excel/PDF  │                 │ parse                ▲
│ 中国三市 页面/PDF     │                 └──────────────────────┘
└──────────────────────┘                        build / validate
```

四个可独立运行的阶段：

1. **fetch** — 下载 → `data/raw`，写 `manifest.json`（含 ETag、Last-Modified、SHA256、抓取时间）。
2. **ingest** — 解析 → 写入 `fact`（原始观测，规范化单位）+ `source`（登记表行）。
3. **build** — 由 `fact` 计算 `derived`（4 项指标），写入 `issue`（缺失、异常、备注）。
4. **validate / export** — 规则校验 + 输出 Excel 与说明。

---

## 3. 数据源采集方案

### 3.1 源清单总表

| source_id 前缀 | 城市/范围 | 指标 | 机构 | 端点 | 格式 | 自动化 |
|---|---|---|---|---|---|---|
| `WB-WDI` | 6 个经济体 | 国家 GDP、汇率 | World Bank | `api.worldbank.org/v2` | JSON | A 全自动 |
| `BEA-CAGDP1` | 纽约 | 县级 GDP | BEA | `apps.bea.gov/regional/zip/CAGDP1.zip` | ZIP/CSV | A 全自动 |
| `CENSUS-PEP` | 纽约 | 人口 | Census Bureau | `www2.census.gov/.../co-est*.csv` | CSV | A 全自动 |
| `ONS-RGDP` | 伦敦 | 区域 GDP | ONS | 数据集页 xlsx 直链 | XLSX | A 全自动 |
| `ONS-POP` | 伦敦 | 人口 | ONS | 年中人口估计 | XLSX | A 全自动 |
| `SINGSTAT-M014871` | 新加坡 | GDP | SingStat | TableBuilder API | JSON | A 全自动 |
| `SINGSTAT-M810001` | 新加坡 | 人口 | SingStat | TableBuilder API | JSON | A 全自动 |
| `HKCSD-310-31002` | 香港 | GDP | C&SD | 数据 API / CSV | JSON/CSV | A 全自动 |
| `HKCSD-POP` | 香港 | 人口 | C&SD | 110-01001 | JSON/CSV | A 全自动 |
| `TOKYO-KEIZAI` | 东京 | 都内総生産 | 東京都総務局 | 开放数据 API / 年报 Excel | JSON/XLSX/PDF | B 半自动 |
| `TOKYO-POP` | 东京 | 推计人口 | 東京都総務局 | 推计人口 Excel | XLSX | B 半自动 |
| `CN-BJ` / `CN-SH` / `CN-SZ` | 北京/上海/深圳 | GDP、人口 | 各市统计局 | 年鉴/统计公报 | HTML/PDF/XLSX | C 手工+解析 |

自动化分级：**A** 全自动、**B** 半自动（结构变化时人工介入）、**C** 人工下载后脚本解析。

### 3.2 逐源方案

#### 3.2.1 世界银行（WB）

- 端点：`https://api.worldbank.org/v2/country/{ISO3}/indicator/{IND}?format=json&per_page=100&date=1995:2025`
- 指标：`NY.GDP.MKTP.CD`（现价美元 GDP）、`PA.NUS.FCRF`（官方汇率，本币/美元）
- 经济体：USA、GBR、JPN、SGP、CHN、HKG
- 解析：跳过第 1 个分页元数据元素；`value=null` 的年份不写 `fact`，记 `issue`
- 注意：2025 年值可能尚未发布；确认后若仍缺，派生指标自然留空

#### 3.2.2 BEA（纽约 GDP）

- 端点：`https://apps.bea.gov/regional/zip/CAGDP1.zip`（约 1.9 MB，免 key）
- 已验证：`Last-Modified: 2026-02-05`，内含 `CAGDP1_NY_2001_2024.csv` 与 `CAGDP1__definition.xml`
- 解析：
  1. 在内存中解压，按 `CAGDP1_*_*.csv` 通配匹配（**不硬编码年份段**）；
  2. 过滤 `LineCode == 3`（现价 GDP）与 `GeoFIPS ∈ {36005, 36047, 36061, 36081, 36085}`；
  3. 按年份求和 → `gdp_lcu`（单位千美元 → ×1e3 转美元）；
  4. 暂不保留 `LineCode == 1`（不变价）：其余城市暂无同口径实际序列，先留空，S6 若做不变价敏感性再补。
- 版本：从压缩包内文件名解析，如 `CAGDP1_NY_2001_2024.csv` → `BEA-CAGDP1-2024`；ETag、Last-Modified、SHA256 记录在 manifest。
- 兜底：若 ZIP 路径失效，改走 BEA API（需免费 key）或人工下载放入 `data/manual`。

#### 3.2.3 美国人口普查局（纽约人口）

三个 vintage 按年份分段使用（同年重叠时用较新 vintage）：

| 年份区间 | 文件 | 说明 |
|---|---|---|
| 2000–2009 | `2000-2010/intercensal/county/co-est00int-tot.csv` | 全国总量文件（370 KB） |
| 2010–2019 | `2010-2020/counties/totals/co-est2020-alldata.csv` | 全国文件（4 MB） |
| 2020–2024 | `2020-2024/counties/totals/co-est2024-alldata.csv` | 全国文件（1.7 MB） |

- 过滤 `STATE == 36` 且 `COUNTY ∈ {5,47,61,81,85}`，按年求和 `POPESTIMATE{year}`。
- **编码**：三个文件都是 `latin-1`（县名含西文重音字符），用 UTF-8 会报错。
- **FIPS 补零不一致**：2000–2010 文件的 `COUNTY` 是 `5`，后两个是 `005`；统一按整数比较，不要按字符串。
- **注意**：三段基期不同，2010 / 2020 处有跳变（2020 年用 2020–2024 vintage 的 blended base，8,740,306，而非普查数 8,804,190）；同一序列内不跨段拼接，跳变写入 `fact.note`。

#### 3.2.4 ONS（伦敦 GDP 与人口）

- 数据页：`https://www.ons.gov.uk/economy/grossdomesticproductgdp/datasets/regionalgrossdomesticproductallnutslevelregions`
- 抓取：解析页面 HTML 中形如 `/{YYYY}to{YYYY}/…xlsx` 的链接，取年份区间最大者（当前 `1998to2024`）。
- **一份工作簿同时提供 GDP 与人口**，同源同版本：

| 工作表 | 内容 | 单位 |
|---|---|---|
| `Table 5` | GDP at current market prices | 百万英镑 |
| `Table 6` | Total resident population numbers | 人 |

- 解析：找到首列 `ITL` 的表头行建立「列号→年份」映射，再取 `ITL1` + `London` 行；`Table 6` 同理。
- 版本：文件名中的年份区间（`1998to2024`），`source_id` 为 `ONS-RGDP-1998to2024`。
- 注意：ONS 现版本使用 balanced 估计，同一版本内一致；**不得跨版本拼接**。人口与 GDP 同版本，天然一致，不再单独取 ONS 人口数据集。

#### 3.2.5 SingStat（新加坡）

三张表，均走 `tablebuilder.singstat.gov.sg/api/table/tabledata/{table}`，无需 key：

| 表号 | 内容 | 行（rowText） | 单位 |
|---|---|---|---|
| M014871 | 现价 GDP（**季度**） | `GDP At Current Market Prices` | Million Dollars |
| M810001 | 人口（年度） | `Total Population` | Number |
| M890151 | 土地面积（年度，12 月） | `Total Land Area` | Square Kilometre |

- **M014871 是季度表**（`INIT.md` 未说明这一点）：年度值由四个季度**加总**得到。不足四个季度的年份（如当年只到 Q2）跳过，避免把部分年份当全年。
- 版本取 `Data.dataLastUpdated`（`DD/MM/YYYY`），转 ISO 后写入 `source_id`。
- 人口用总人口（含非居民），符合 SPEC §6.3。
- **仅对现价序列做季度加总**：现价年度值即四季之和（SNA 恒等式），已用 2024/2025 官方年度值验证一致。不变价（chained）年度值**不可**由季度加总得到（链式指数不可加），若将来需要实际 GDP，必须另取年度链式序列。

#### 3.2.6 香港 C&SD

三张表，均走 `api/get.php?id={table}&lang=en&full_series=1`，无需 key、无需 `param`：

| 表号 | 内容 | 过滤条件 | 单位 |
|---|---|---|---|
| 310-31002 | 现价 GDP（开支法） | `GDP_COMPONENTDesc=Total`、`freq=Y`、`svDesc=HK$ million` | 百万港元 |
| 110-01001 | 人口（半年表） | `SEXDesc/AGEDesc=Total`、`period` 以 `06` 结尾、`svDesc` 以 `Number` 开头 | 千人 |
| 110-02001 | 土地面积（分区） | `DCDesc=Total`、`sv=LA` | 平方公里 |

**两个坑（已踩过）**：

1. 310-31002 的 `Total` 行同时包含「百万港元」和「同比 %」两套 `figure`，二者 `sv` 都是 `CUR`，**只能按 `svDesc` 区分**；否则会把 6.9% 当成 6.9 百万港元。
2. 110-01001 的总人口行与占比行 `sv` 同为 `POP`，同样必须按 `svDesc` 过滤（否则得到 100）。

**土地面积口径**：110-02001 的 `Total` 为**分区土地面积合计（不含水塘等水域）**，2024 年为 1,089.72 km²；香港常用的 1,114.57 km² 为含水域总面积。按 SPEC「陆地面积」规则采用前者，差异约 2.3%。

**2000 年面积**：该表自 2002 年起，2000 年用 2002 年值回填并标记 `provisional`（年变化 <1%），已记入决策 DR-14。

#### 3.2.7 东京都

年報页 `keizaik/nenpou/kkne-index.htm` 上直接给出 CSV 链接，解析出最新的 `kk{YY}qv0110.csv` 即可，无需开放数据 API：

| 文件 | 内容 | 单位 |
|---|---|---|
| `kk{YY}qv0110.csv` | 統合勘定(1) 都内総生産勘定（生産側及び支出側） | 百万円 |
| `kk{YY}qv0410.csv` | 関連指標(1) うち「3．人口(1) 総人口」 | 千人 |

- 解析：表头中 `YYYY年度` 建列映射；GDP 取行首为「都内総生産（生産側）」的行，人口取含「総人口」的行。
- **年度 → 年份按起始年对齐**：令和 5 年度 = FY2023 → `year=2023`，写入 `fact.note`。
- **覆盖只有 13 个年度**（当前 FY2011–FY2023）。旧版年報可补更早年份，但同一指标在版本间修订很大（2005 年 +7.2%、2010 年 +6.7%），**不做跨版本拼接**（DR-15）；2000/2005/2010 留空。
- 人口与 GDP 取自同一版年報，口径一致（人口引用「東京都の人口（推計）」）。
- 面积 2,194.07 km² 为常数，走 `REF-GEO-TYO`。

#### 3.2.8 中国三市（半自动）

- 近期年份：统计公报 HTML（含 GDP、常住人口、人均 GDP），可直接解析。
- 历史年份：统计年鉴「综合核算」章节（Excel/PDF/网页表格）。
- 流程：脚本无法稳定抓取时，人工下载至 `data/manual/CN-<CITY>/`，脚本按约定文件名识别并解析；登记表 `acquisition=manual`。
- **一致性要求**：同一城市全序列尽量取同一版年鉴；跨版本时在 `fact.note` 记录版本。
- **深圳**：2024 年起含深汕特别合作区（陆域 468.3 km²；2024 年该区 GDP 242.15 亿元）。实施时先核实官方全市 GDP 是否已含该区：
  - 已含 → 直接采用，备注口径变更；
  - 未含 → 暂停并请需求方确认，**不得自行加总**。

---

## 4. 原始数据保存方案

### 4.1 目录与命名

```
data/raw/<source_id>/
├── <原始文件名>            # 原样保存，不重命名、不清洗
└── manifest.json          # 抓取元数据
```

`source_id` 规则：`组织-数据集-版本`，版本用「数据发布时间」表示：

- `WB-WDI-2026-10-20`
- `BEA-CAGDP1-2026-02-05`
- `ONS-RGDP-2026-09-23`
- `SINGSTAT-M014871-2026-10-20`
- `HKCSD-310-31002-2026-10-20`
- `CN-BJ-GB-2025`（统计公报）、`CN-BJ-YB-2020`（年鉴）

### 4.2 manifest.json

```json
{
  "source_id": "HKCSD-310-31002-2025",
  "dataset_key": "HKCSD-310-31002",
  "meta": {
    "id": "HKCSD-310-31002-2025",
    "dataset_key": "HKCSD-310-31002",
    "city_code": "HKG",
    "indicator": "gdp",
    "organization": "Census and Statistics Department, Hong Kong SAR",
    "dataset_title": "Gross Domestic Product (GDP) by major expenditure component at current market prices",
    "table_id": "310-31002",
    "url": "https://www.censtatd.gov.hk/api/get.php?id=310-31002&lang=en&full_series=1",
    "vintage": "2025",
    "published_at": null,
    "acquisition": "auto",
    "notes": "数据版本以最新期间年度标识；无独立发布日期字段"
  },
  "urls": ["https://www.censtatd.gov.hk/api/get.php?id=310-31002&lang=en&full_series=1"],
  "http_status": 200,
  "etag": "\"6a1f-5f0c\"",
  "last_modified": "Tue, 04 Nov 2025 00:00:00 GMT",
  "fetched_at": "2026-10-20T21:35:12+08:00",
  "acquisition": "auto",
  "files": [
    {"name": "310-31002.json", "sha256": "…", "bytes": 2077683}
  ]
}
```

要点：

- `meta` 完整保存 `SourceMeta`，使 `ingest` 可以完全离线重建。
- 多文件来源（如世界银行 6 个 `{ISO}.json`）共用同一个 `manifest`，逐个文件记录哈希。
- `dataset_key` 是去掉版本号的前缀，用于在 `ingest` 时清理该数据集的旧版本 fact。
- `source.sha256`：单文件来源取其哈希；多文件来源取「文件名:哈希」拼接后的 SHA256，保证登记表每行都有指纹。

### 4.3 规则

1. **只增不改**：`raw` 下文件写入后不再修改；清洗一律发生在 `fact` 层。
2. **同版本幂等**：同 `source_id` 重复抓取覆盖同目录，`manifest.fetched_at` 更新。
3. **新版本另立目录**：数据发布新版时新建 `source_id`，旧目录保留。
4. **手工区**：`data/manual/<source_id>/` + `PLACEHOLDER.md` 说明期望文件名与来源；脚本对 `manual` 与 `raw` 使用同一 parser。
5. **完整性校验**：`ingest` 前比对 `manifest.sha256` 与磁盘文件；不一致则拒绝解析。
6. **不提交大数据**：`data/raw` 体积预计 < 50 MB，可入库；`data/db` 可重建，可不入库（由 `.gitignore` 控制，最终由用户决定）。

---

## 5. 中间数据库设计

SQLite，路径 `data/db/city_gdp.sqlite`。选择理由：零运维、单文件、可直接用 `sqlite3` 人工核查、与 pandas 集成简单。

### 5.1 实体关系

```
city 1 ────* fact *──── 1 source
  │                        │
  │                        └── manifest.json（文件侧）
  └────* derived
  └────* issue

（country / currency 通过 fact.entity_type + entity_code 表达，不单设表）
```

### 5.2 DDL

```sql
PRAGMA foreign_keys = ON;

CREATE TABLE city (
  code         TEXT PRIMARY KEY,
  name_cn      TEXT NOT NULL,
  name_en      TEXT NOT NULL,
  country_iso3 TEXT NOT NULL,
  currency     TEXT NOT NULL,
  boundary     TEXT NOT NULL,
  pop_basis    TEXT NOT NULL,
  area_basis   TEXT NOT NULL,
  note         TEXT
);

CREATE TABLE source (
  id                 TEXT PRIMARY KEY,
  city_code          TEXT REFERENCES city(code),
  indicator          TEXT NOT NULL,
  organization       TEXT NOT NULL,
  dataset_title      TEXT NOT NULL,
  table_id           TEXT,
  url                TEXT NOT NULL,
  vintage            TEXT,
  published_at       TEXT,
  accessed_at        TEXT NOT NULL,
  http_etag          TEXT,
  http_last_modified TEXT,
  sha256             TEXT,
  local_path         TEXT,
  acquisition        TEXT NOT NULL CHECK (acquisition IN ('auto','manual')),
  notes              TEXT
);

CREATE TABLE fact (
  id          INTEGER PRIMARY KEY,
  source_id   TEXT NOT NULL REFERENCES source(id),
  entity_type TEXT NOT NULL CHECK (entity_type IN ('city','country','currency')),
  entity_code TEXT NOT NULL,
  indicator   TEXT NOT NULL CHECK (indicator IN (
                'gdp_lcu','gdp_real_lcu','population','area_km2',
                'country_gdp_usd','fx_lcu_per_usd')),
  year        INTEGER NOT NULL,
  value       REAL NOT NULL,
  unit        TEXT NOT NULL,
  status      TEXT NOT NULL DEFAULT 'final'
              CHECK (status IN ('final','preliminary','provisional')),
  note        TEXT,
  UNIQUE (source_id, entity_type, entity_code, indicator, year)
);
CREATE INDEX idx_fact_lookup ON fact(entity_code, indicator, year);

CREATE TABLE derived (
  city_code   TEXT NOT NULL REFERENCES city(code),
  year        INTEGER NOT NULL,
  metric      TEXT NOT NULL CHECK (metric IN (
                'gdp_usd','primacy_pct','gdp_per_capita_usd','gdp_per_km2_usd')),
  value       REAL,
  unit        TEXT NOT NULL,
  formula     TEXT NOT NULL,
  inputs_json TEXT NOT NULL,
  computed_at TEXT NOT NULL,
  PRIMARY KEY (city_code, year, metric)
);

CREATE TABLE issue (
  id         INTEGER PRIMARY KEY,
  step       TEXT,
  city_code  TEXT,
  year       INTEGER,
  metric     TEXT,
  severity   TEXT NOT NULL CHECK (severity IN ('info','warn','error')),
  message    TEXT NOT NULL,
  created_at TEXT NOT NULL
);
```

> 本 DDL 已在 SQLite 3 上试建并通过功能验证：建表成功、外键生效、CHECK 拦截非法指标、UNIQUE 拦截重复单元格、`PRAGMA foreign_key_check` 无输出。S1 会在项目库上再执行一次并纳入门禁。

### 5.3 字段约定

- `fact.value` 一律规范化为**基本单位**：本币元、人、km²、美元。原始单位与缩放记录在 `fact.note`（如 `原始单位=亿元，×1e8`）。
- `fact.entity_type`：
  - `city` — `entity_code` 为城市代码；
  - `country` — `entity_code` 为 ISO3（USA/GBR/JPN/SGP/CHN）；
  - `currency` — `entity_code` 为币种（CNY/JPY/GBP/SGD/HKD）。
- `derived.inputs_json` 记录参与计算的 `fact.id` 列表，实现单元格级追溯。
- **单值约束**：同一 `(entity_type, entity_code, indicator, year)` 只允许存在一条 `fact`。若出现多源（如人口同时有普查值与估计值），必须在 `config/params.yaml` 的 `adopted_source` 中显式指定采纳源，其余来源不得入库、仅可用于校验。此约束由 R11 强制。
- 所有金额派生值以 `REAL` 存储，**不做四舍五入**；仅在导出阶段格式化。

### 5.4 幂等与重建

- `ingest`：按 `fact` 唯一键 upsert；同 `source_id` 先删后插（保证不残留旧行）。
- `build`：`DELETE FROM derived` 后全量重算。
- `issue`：每次 `build`/`validate` 清空后重写。
- 删除 `data/db` 后执行 `ingest → build` 即可完全重建（不联网）。

---

## 6. 本地目录结构

```
showcases/
├── INIT.md
├── SPEC.md
├── DESIGN.md
├── PLAN.md
├── README.md
├── pyproject.toml
├── uv.lock
├── config/
│   ├── cities.yaml          # 城市、边界、币种、人口/面积口径
│   ├── params.yaml          # 年份、指标、输出路径、取整规则
│   └── anchors.yaml         # 校验锚点（官方公布值）
├── data/
│   ├── raw/<source_id>/…    # 不可变原始数据 + manifest.json
│   ├── manual/<source_id>/… # 人工投递区
│   └── db/city_gdp.sqlite   # 可重建
├── src/citygdp/
│   ├── __init__.py
│   ├── __main__.py          # python -m citygdp
│   ├── cli.py               # 命令入口（doctor/fetch/ingest/…）
│   ├── config.py            # 配置加载与校验
│   ├── schema.sql           # DDL 唯一来源
│   ├── db.py                # 建表、连接、健康检查
│   ├── http.py              # 统一请求：UA、重试、限速
│   ├── ingest.py            # 写 source / fact（含旧版本清理）
│   ├── adapters/
│   │   ├── base.py          # Fact / SourceMeta / Fetched / commit_raw
│   │   ├── worldbank.py
│   │   ├── singstat.py
│   │   ├── hkcsd.py
│   │   ├── bea.py           # S3
│   │   ├── census.py        # S3
│   │   ├── ons.py           # S3
│   │   ├── tokyo.py         # S4
│   │   └── china.py         # S5
│   ├── build.py             # 派生指标（S6）
│   ├── validate.py          # 规则校验（S6）
│   └── export.py            # Excel / 说明输出（S7）
├── scripts/
│   └── run_all.sh           # uv run citygdp all 的快捷入口
├── tests/
│   ├── fixtures/            # 解析器回归用的小样本
│   └── test_*.py
└── output/
    ├── 城市GDP分析.xlsx
    ├── 数据来源登记表.xlsx
    ├── 数据说明.md
    └── qa/S1.md … S7.md      # 每步验收记录
```

依赖（最小集）：`httpx`、`polars`、`openpyxl`、`xlrd`、`pypdf`、`pyyaml`；开发依赖 `pytest`。PDF 解析（如 `pdfplumber`）仅在东京/中国源确实需要时引入。选型理由见 §15。

---

## 7. 配置设计

### 7.1 `config/cities.yaml`（节选）

```yaml
cities:
  - code: NYC
    name_cn: 纽约
    name_en: New York City
    country_iso3: USA
    currency: USD
    boundary: "Bronx+Kings+New York+Queens+Richmond 五县之和"
    population: {basis: "5县合计，7月1日估计"}
    area: {basis: "5县陆地面积", note: "含水域口径约 1,223 km²，不采用"}
  - code: SZX
    name_cn: 深圳
    country_iso3: CHN
    currency: CNY
    boundary: "全市"
    population: {basis: "年平均常住人口"}
    area: {basis: "全市陆域面积"}
    breaks:
      - from: 2024
        change: "含深汕特别合作区（+468.3 km²）"
```

### 7.2 `config/params.yaml`

```yaml
years: [2000, 2005, 2010, 2015, 2020, 2022, 2023, 2024, 2025]
fx_indicator: PA.NUS.FCRF
country_gdp_indicator: NY.GDP.MKTP.CD
rounding:
  gdp_usd_yi: 1
  primacy_pct: 2
  per_capita_usd: 0
  per_km2_usd: 0
output:
  workbook: output/城市GDP分析.xlsx
  registry: output/数据来源登记表.xlsx
  notes: output/数据说明.md
```

### 7.3 `config/anchors.yaml`

用于 QA 的官方锚点（实施时补全并注明出处）：

```yaml
anchors:
  - {city: SGP, year: 2025, metric: gdp_lcu, value: 789.5292e9, unit: SGD}
  - {city: HKG, year: 2024, metric: gdp_lcu, value: 3186.526e9, unit: HKD}
  - {city: BJS, year: 2025, metric: gdp_lcu, value: 5207.34e9,  unit: CNY}
  - {city: SHA, year: 2025, metric: gdp_lcu, value: 5670.871e9, unit: CNY}
  - {city: SZX, year: 2025, metric: gdp_lcu, value: 3873.180e9, unit: CNY}
```

---

## 8. 换算与派生规则

### 8.1 单位规范化（ingest 阶段）

| 城市 | 原始单位 | 缩放 | 说明 |
|---|---|---|---|
| NYC | 千美元 | ×1e3 | BEA `CAGDP1` 现价 GDP |
| LDN | 百万英镑 | ×1e6 | ONS 现价 GDP |
| TYO | 百万日元 | ×1e6 | 都内総生産（名目） |
| SGP | 百万新元 | ×1e6 | 季度加总后 |
| BJS/SHA/SZX | 亿元 | ×1e8 | 统计年鉴/公报 |
| HKG | 百万港元 | ×1e6 | C&SD |
| 中国城市人口 | 万人 | ×1e4 | |
| 人口（其余） | 人 | ×1 | |
| 面积 | km² | ×1 | 平方公里/平方英里需换算 |

### 8.2 派生计算（build 阶段）

```
gdp_usd        = gdp_lcu / fx(cur, y)
primacy_pct    = gdp_usd / country_gdp_usd(country, y) × 100
gdp_per_capita = gdp_usd / population
gdp_per_km2    = gdp_usd / area_km2
```

- 任一输入缺失 → 该指标不写 `derived` 行（导出即空）。
- 新加坡 `primacy_pct` 直接取 100.0，并在 `formula` 中注明「城市国家」。
- 香港 `primacy_pct` 分母取 `country_gdp_usd(CHN)`。

### 8.3 取整

只在 **export** 阶段按 `params.yaml` 格式化；数据库保留全精度，避免二次计算误差。

---

## 9. 校验设计

| 编号 | 规则 | 级别 |
|---|---|---|
| R1 | 每城每年每指标至多一条 `fact`；重复即报错 | error |
| R2 | 汇率区间：CNY 6.0–9.0、JPY 90–160、GBP 0.50–0.95、SGD 1.20–1.80、HKD 7.70–7.90 | error |
| R3 | 首位度 ∈ (0, 100]；新加坡 = 100.00±0.01 | error |
| R4 | 城市 GDP 美元序列同比 ∈ [−25%, +45%]（超界仅告警，需人工确认） | warn |
| R5 | 人均 GDP 区间（城市级下限/上限，配置化） | warn |
| R6 | 地均 GDP 区间（城市级，配置化） | warn |
| R7 | 量级哨兵：中国城市 GDP ∈ [1e11, 2e13] 元；日本 ∈ [1e14, 2e14] 日元 | error |
| R8 | 锚点比对：与 `anchors.yaml` 相对偏差 ≤ 0.5% | error |
| R9 | 缺失格必须落在 SPEC §4.3 白名单内，白名单外的空值报错 | error |
| R10 | 来源登记表必填字段非空；`local_path` 文件存在且哈希匹配 | error |
| R11 | 同一 `(entity_type, entity_code, indicator, year)` 不得有多条 `fact`（多源须显式指定采纳源） | error |

校验结果写入 `issue` 表，并生成 `output/qa_report.md`（步骤级）。

---

## 10. 导出设计

### 10.1 工作簿结构

`output/城市GDP分析.xlsx`，**单个工作表** `城市GDP`，把 4 项指标纵向堆叠：

```
行1:  城市 GDP 主要指标（现价美元口径）
行2:  区域GDP 亿美元｜首位度 %｜人均 美元/人｜地均 美元/km²；按世界银行年均汇率折算；缺失值留空
行3:  指标 | 年份 | 纽约 | 伦敦 | 东京 | 新加坡 | 北京 | 上海 | 深圳 | 香港 | 备注
行4:  区域GDP（亿美元） | 2000 |    |    | ... 
...
行12: 区域GDP（亿美元） | 2025 | ...
行13: 经济首位度（%） | 2000 | ...
...
行39: 地均GDP（美元/km²） | 2025 | ...
行40:  （空行）
行41+: 注：1) 新加坡为城市国家，首位度恒为 100%；2) 香港首位度以中国（不含港澳台）为分母；
       3) 2024 年起深圳数据含深汕特别合作区；4) 空白表示数据不可得，原因见《数据说明》
```

- 行：4 个指标块 × 9 年 = 36 行；指标名每行重复（**不合并单元格**，保证可被 pandas/CSV 直接读取）；用隔块底色区分。
- 列：A=指标、B=年份、C–J=8 城、K=备注。
- 数字格式：金额 `#,##0.0`、百分比 `0.00`、人数与密度 `#,##0`。
- 冻结窗格 `C4`（锁定表头与前两列）；列宽：A 22、B 8、C–J 14、K 30。
- 空值保持空单元格（不写 `—`、`N/A`、`0`）。
- 备注列仅在该行有特殊说明时填写（如 2024 年深圳行），其余为空。

### 10.2 来源登记表

`output/数据来源登记表.xlsx`：一行一个 `source`，列同 §7.2 的字段清单，附「覆盖年度」「数据状态」两列。

### 10.3 数据说明

`output/数据说明.md`：口径摘要、缺失清单（城市×年份×原因）、状态说明（初步/最终）、换算方法、生成时间与数据版本。

---

## 11. 运行方式

```bash
uv sync
uv run citygdp doctor                 # 环境/配置/DB 自检
uv run citygdp fetch --source all     # 下载到 data/raw
uv run citygdp ingest --source all    # 解析入 fact
uv run citygdp build                  # 计算 derived
uv run citygdp validate [--rule R1,R2,…]  # 规则校验 → issue + qa_report
uv run citygdp export                 # 生成 output/*
uv run citygdp all                    # 全流程
```

约束：`build/validate/export` **不得发起网络请求**。

---

## 12. 测试策略

| 层次 | 内容 |
|---|---|
| 单元测试 | 每个 adapter 的 `parse()` 用 `tests/fixtures` 小样本断言（NYC 五县求和、东京年度映射、中国单位换算） |
| 集成测试 | `ingest → build` 后对 `derived` 做黄金值断言（少量年份） |
| 回归测试 | 锚点校验（R8）纳入 `pytest`，任一锚点失败即红 |
| 人工抽检 | 每个步骤结束抽 3–5 个数字与官方页面比对，记录在 PLAN 的验收记录中 |

---

## 13. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| 中国年鉴站点反爬/改版 | 进度延误 | 人工下载 + 固定文件名约定；每年份单独 `source_id` |
| ONS/BEA 发布新版导致口径变化 | 序列断裂 | 一城一版本；`fact.note` 记录版本；不跨版本拼接 |
| 世界银行 2025 年数据未发布 | 2025 派生指标为空 | 已知并接受；发布后重跑即可补 |
| 东京都开放数据序列不全 | 需回退年报 | 保留 Excel/PDF 解析路径 |
| 深圳深汕口径与官方不一致 | 数据错误 | 实施前核实；未含则暂停并确认，不自行加总 |
| 填海导致面积逐年变化 | 地均 GDP 趋势被误读 | 面积逐年取数并在说明中披露 |
| 单位换算错误（亿/万/百万） | 量级错误 | R7 量级哨兵 + 锚点 R8 + 单元测试 |

---

## 14. 设计决策记录

| 编号 | 决策 | 备选 | 理由 |
|---|---|---|---|
| DD-01 | SQLite 作为中间库 | CSV/Parquet/DuckDB | 单文件、零运维、可直接人工查询；数据量极小 |
| DD-02 | 原始文件按 `source_id` 分目录、只增不改 | 单一 `raw/` 平铺 | 版本隔离，复现时不会被新版覆盖 |
| DD-03 | 全量重建而非增量更新 | 增量 upsert | 数据量小，重建更简单且结果确定 |
| DD-04 | 派生值不落盘取整 | 落盘即取整 | 避免误差累积；格式在导出层解决 |
| DD-05 | `fact` 用统一长表而非每源一表 | 宽表 | 8 城 × 9 年规模小，长表便于校验与追溯 |
| DD-06 | BEA 用 ZIP 而非 API | API + key | 免注册、单文件、含 definition 与脚注 |
| DD-07 | 东京年度按起始年对齐 | 按结束年 / 跨年加权 | 与日本官方表述一致，最易核对 |
| DD-08 | 校验规则配置化 | 硬编码阈值 | 城市差异大，阈值需按城调整 |
| DD-09 | 交付物单表纵向堆叠 | 4 个分表 | 便于 4 指标 × 8 城横向比较；减少翻表 |
| DD-10 | `fact` 唯一键不含 `source_id` | 含 `source_id` | 在数据库层强制「一格一值」，多源冲突在入库时即暴露 |
| DD-11 | 指标名每行重复、不合并单元格 | 合并指标列 | 保证交付表可被 pandas/CSV 直接读取，不牺牲可解析性 |
| DD-12 | 数据处理库用 polars | pandas | 需求方指定；本项目计算量小，polars 主要用于后续分析层 |

---

## 15. 依赖选型

| 用途 | 选型 | 备选 | 说明 |
|---|---|---|---|
| HTTP | `httpx` | `requests` | 连接池、超时与重试语义清晰；已在 S2 使用 |
| 数据处理 | `polars` | `pandas` | 需求方指定 polars；S2 解析为纯 Python，尚未依赖该库 |
| Excel 读写 | `openpyxl` | `xlsxwriter` | 需要单元格格式、冻结窗格、隔块底色；S7 使用 |
| 配置 | `PyYAML` | `ruamel.yaml` | 标准 YAML，无特殊需求 |
| 旧版 Excel | `xlrd` | 先转 xlsx | 北京年鉴表为 BIFF `.xls`，openpyxl 不支持 |
| PDF 文本 | `pypdf` | `pdfplumber` | 深圳年鉴为整本 PDF，仅需文本层，`pypdf` 更轻 |
| CLI | `argparse`（标准库） | `typer` / `click` | 子命令结构简单，不引入额外依赖 |
| 测试 | `pytest` | `unittest` | fixtures 与断言表达力更好 |
| HTML 解析 | 待定（S4/S5） | `selectolax` / `BeautifulSoup` | 能走 API 就不解析 HTML |
| PDF 解析 | 待定（S4/S5） | `pdfplumber` | 仅在中国年鉴或东京都年报确需时引入 |

原则：能走官方 API 就不引解析库；能用手工下载 + 简单解析就不引入重型依赖。新增依赖前先在 PLAN 对应步骤说明理由。
