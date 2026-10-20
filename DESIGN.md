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
  4. 同时保留 `LineCode == 1`（不变价）到 `fact`，供后续分析，不导出。
- 版本：以 `ETag` + `Last-Modified` + 文件 SHA256 识别；同一版本重复抓取覆盖同名目录。
- 兜底：若 ZIP 路径失效，改走 BEA API（需免费 key）或人工下载放入 `data/manual`。

#### 3.2.3 美国人口普查局（纽约人口）

- 三个 vintage 文件覆盖不同区间（文件名以 Census 站点为准，实施时确认）：
  - `co-est00int-alldata.csv`（2000–2010 intercensal，含 7/1/2000）
  - `co-est2020-alldata.csv`（2010–2020）
  - `co-est2024-alldata.csv`（2020–2024）
- 过滤 `STATE=36` 且 `COUNTY ∈ {005,047,061,081,085}`，求和 `POPESTIMATE{year}`。
- **注意**：三个文件基期不同，2010/2020 处存在跳变；优先使用最新 vintage 的回溯值，无法覆盖的年份才回退旧 vintage，并在 `fact.note` 标注所用 vintage。

#### 3.2.4 ONS（伦敦 GDP 与人口）

- GDP 数据集页：`https://www.ons.gov.uk/economy/grossdomesticproductgdp/datasets/regionalgrossdomesticproductallnutslevelregions`
- 解析：抓取页面 HTML，取最新 `.xlsx` 链接；在工作簿中定位 ITL1 现价 GDP 的 `London` 行。
- 人口：ONS 年中人口估计数据集（UK/England and Wales），取 London 区域合计。
- 注意：ONS 现版本使用 balanced 估计，同一版本内一致；**不得跨版本拼接**。

#### 3.2.5 SingStat（新加坡）

- GDP：`https://tablebuilder.singstat.gov.sg/api/table/tabledata/M014871`
  - **已确认该表为季度表**（Expenditure on GDP at Current Prices, Quarterly）。
  - 年度值 = 四个季度**加总**（现价加总成立），并校验与官方年度发布一致。
- 人口：`https://tablebuilder.singstat.gov.sg/api/table/tabledata/M810001`（总人口）。
- 解析：JSON 中 `Data.row` 为系列，列名形如 `2025 1Q`；按年聚合。

#### 3.2.6 香港 C&SD

- GDP：表 **310-31002**「按主要开支组成部分划分的本地生产总值 — 以当时市价计算」，单位百万港元。
- 人口：表 110-01001 或统计摘要年中人口。
- 获取：优先 `api/get.php?id=...`，回退 `web_table.html?id=...&download_csv=1`。

#### 3.2.7 东京都

- 主路径：東京都开放数据 API（`spec.api.metro.tokyo.lg.jp`）中的「都民経済計算」数据集，取「都内総生産（名目）」时间序列，可覆盖 2000 年起。
- 兜底：年报 `keizaik/nenpou/kkne-index.htm` 的 Excel/PDF，人工确认表号后解析。
- 人口：推计人口 `jsuikei/js-index2.htm` 的总数表。
- 注意：**年度值 → 年份映射为「起始年」**（令和 5 年度 → 2023），写入 `fact.note`。

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
  "source_id": "BEA-CAGDP1-2026-02-05",
  "url": "https://apps.bea.gov/regional/zip/CAGDP1.zip",
  "fetched_at": "2026-10-20T20:40:12+08:00",
  "http_status": 200,
  "etag": "\"4748349ca396dc1:0\"",
  "last_modified": "Thu, 05 Feb 2026 13:30:35 GMT",
  "sha256": "95b49283df20772ded04ea53e1142955b8ade5e7f93047c0a3dfaf403b166fe1",
  "bytes": 1928241,
  "files": ["CAGDP1_NY_2001_2024.csv", "CAGDP1__definition.xml"],
  "acquisition": "auto",
  "notes": null
}
```

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
│   ├── cli.py               # 命令入口
│   ├── config.py            # 配置加载与校验
│   ├── registry.py          # 来源登记表读写
│   ├── http.py              # 统一请求：UA、重试、限速、缓存
│   ├── db.py                # schema 初始化与连接
│   ├── adapters/
│   │   ├── base.py          # Adapter 协议：fetch() / parse()
│   │   ├── worldbank.py
│   │   ├── bea.py
│   │   ├── census.py
│   │   ├── ons.py
│   │   ├── singstat.py
│   │   ├── hkcsd.py
│   │   ├── tokyo.py
│   │   └── china.py
│   ├── build.py             # 派生指标
│   ├── validate.py          # 规则校验
│   └── export.py            # Excel / 说明输出
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

依赖（最小集）：`httpx`、`pandas`、`openpyxl`、`pyyaml`；开发依赖 `pytest`。PDF 解析（如 `pdfplumber`）仅在东京/中国源确实需要时引入。

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
