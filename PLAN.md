# PLAN.md — 城市 GDP 数据分析：分步实施计划

| 项目 | 内容 |
|---|---|
| 文档版本 | v1.0 |
| 状态 | 待确认（确认后方可开工） |
| 编制日期 | 2026-10-20 |
| 上游文档 | `SPEC.md`、`DESIGN.md` |
| 执行方式 | 每步完成后先自检，再提交验收证据，经确认后进入下一步 |

---

## 1. 总览

| 步骤 | 名称 | 主要产出 | 预估 | 依赖 |
|---|---|---|---|---|
| **S1** | 骨架与口径固化 | 配置、DB schema、CLI 骨架、`doctor` | 0.5 天 | — |
| **S2** | 基准数据：世界银行 + 港澳新 | 汇率、国家 GDP、新加坡/香港全部数据 | 1 天 | S1 |
| **S3** | 纽约 + 伦敦 | 两城的 GDP、人口、面积 | 1 天 | S1 |
| **S4** | 东京 | 都内総生産（FY2000–FY2023）、推计人口 | 1 天 | S1 |
| **S5** | 中国三市 | 京沪深 GDP、常住人口、面积 | 1.5 天 | S1 |
| **S6** | 派生指标与 QA | 4 项指标、校验报告 | 0.5 天 | S2–S5 |
| **S7** | 导出与交付 | Excel 汇总表（单表 4 指标）+ 来源登记表 + 数据说明 | 0.5 天 | S6 |

合计约 **6 个工作日**。S2–S5 均为取数环节、彼此独立，可按任意顺序推进（表中顺序按风险从低到高排列）；若同时开工，S2/S3 与 S4/S5 可两两并行。

```
S1 ──┬── S2 ──┐
     ├── S3 ──┤
     ├── S4 ──┼── S6 ── S7
     └── S5 ──┘
```

**里程碑**

- **M1（S1–S3）**：自动化链路打通，3 个城市（纽约、伦敦、新加坡）+ 香港 + 基准数据入库。
- **M2（S4–S5）**：8 城数据全部入库，覆盖率达到 SPEC §4.3 要求。
- **M3（S6–S7）**：交付物生成并通过验收。

---

## 2. 通用约定

1. **每步都必须可独立验证**：产出物 + 自检命令 + 抽检数字 + 简短验收记录。
2. **验收记录**写入 `output/qa/S{N}.md`，内容包括：行数、覆盖率、抽检值对照、异常与例外。
3. **不跳步**：S6 之前不生成交付表；S7 之前不改动 `output/` 下的最终文件。
4. **不联网阶段**：S6、S7 禁止网络请求，确保「离线可重建」这条质量要求真实成立。
5. **git 由你管理**：我不执行任何 git 操作，只在每步结束时说明变更了哪些文件。

---

## 3. 步骤详情

### S1 · 骨架与口径固化

**目标**：把 SPEC 里的口径变成可执行的配置和空数据库，后续所有步骤只填数据、不改结构。

**动作**

1. `uv sync`，补齐依赖：`httpx`、`pandas`、`openpyxl`、`pyyaml`、`pytest`。
2. 建目录：`config/`、`data/raw/`、`data/manual/`、`data/db/`、`src/citygdp/`、`tests/`、`output/qa/`。
3. 写 `config/cities.yaml`、`config/params.yaml`、`config/anchors.yaml`（初版，锚点先放已知的 5 条）。
4. 写 `src/citygdp/schema.sql`（DDL 单独成文件，便于审阅与复用）与 `db.py`（执行建表）、`config.py`（配置加载与校验）、`cli.py`（`doctor` / `fetch` / `ingest` / `build` / `validate` / `export` 命令骨架，后五个先抛 `NotImplementedError`）。
5. **DDL 实跑验证**：在项目库上建表 → 插入 1 行合法数据 → 依次验证外键、CHECK、UNIQUE 三条约束均能拦截非法写入 → 清空测试数据。
6. 写 `data/manual/README.md`：说明手工投递区的文件名约定。
7. 更新 `README.md`：项目一句话说明 + 文档索引 + 运行方式。

**产出**

- 可运行的 `uv run citygdp doctor`；
- `data/db/city_gdp.sqlite`（5 张空表）；
- 三份配置文件。

**自检**

```bash
uv run citygdp doctor
# 期望：打印 8 城市 × 9 年份的矩阵、5 张表名、配置校验通过
sqlite3 data/db/city_gdp.sqlite ".tables"          # 期望 5 张表
sqlite3 data/db/city_gdp.sqlite "PRAGMA foreign_key_check;"   # 期望无输出
uv run pytest -q                                    # 含 test_schema.py：约束拦截测试
```

`test_schema.py` 至少覆盖：重复 `(entity, indicator, year)` 被 UNIQUE 拒绝、非法 `indicator` 被 CHECK 拒绝、悬空 `source_id` 被外键拒绝。

**需你确认**

- `config/cities.yaml` 里的城市边界、人口/面积口径描述是否与你的理解一致；
- 目录结构是否可接受（尤其 `src/` 布局与 `output/` 位置）。

**风险**：低。

---

### S2 · 基准数据 + 港澳新

**目标**：打通「开放 API → raw → fact」全链路，并完成 3 个最稳的来源。

**动作**

1. `http.py`：统一 UA、超时、重试（3 次，指数退避）、限速（≥1 秒/请求）、`manifest.json` 写入。
2. `adapters/worldbank.py`：拉取 6 个经济体 × 2 个指标，写入 `country_gdp_usd`、`fx_lcu_per_usd`。
3. `adapters/singstat.py`：`M014871`（季度现价 GDP，按年加总）、`M810001`（总人口）、`M890151`（土地面积）。
4. `adapters/hkcsd.py`：`310-31002`（现价 GDP）、`110-01001`（年中人口，取 6 月）、`110-02001`（土地面积）。
5. 建 `tests/fixtures/`，为三个 adapter 各存裁剪样本并写解析回归（含单位过滤的坑）。

**产出**：`data/raw/` 下 8 个 source 目录、`fact` 表 639 行（世界银行 1990–2025 全序列 + 港澳 36 年序列）、`doctor` 覆盖矩阵中新加坡与香港全部点亮。

**自检**

```bash
uv run citygdp fetch --source worldbank,singstat,hkcsd
uv run citygdp ingest --source worldbank,singstat,hkcsd
uv run citygdp doctor            # 覆盖矩阵应点亮新加坡、香港
uv run pytest -q                 # 含三个适配器的解析回归
# 离线重建：删除 DB 后不联网重灌，结果应与之前一致
rm data/db/city_gdp.sqlite && uv run citygdp ingest --source all
```

> `validate` 的规则实现统一放在 S6，避免 S2 出现半成品规则集；本步用 `doctor` 覆盖矩阵 + 解析回归 + 离线重建作为门禁。

**抽检数字（人工比对官方页面）**

| 项 | 期望值 |
|---|---|
| 新加坡 2025 GDP | 789,529.2 百万新元 |
| 香港 2024 GDP | 3,186,526 百万港元 |
| CNY/USD 2000 年均汇率 | ≈ 8.2784 |
| 新加坡 2024 总人口 | ≈ 604 万 |
| 香港 2024 年中人口 | 752.41 万 |
| 新加坡 2025 土地面积 | 744.3 km² |
| 香港 2024 土地面积 | 1,089.72 km²（不含水域） |

**需你确认**：新加坡季度加总得到的年度值是否可接受（若你更希望用 SingStat 年度表，我在这一步换源）；香港面积按「不含水域」口径（1,089.72 km²）是否符合预期。

**风险**：世界银行 2025 年数据可能未发布 → 记 `issue`（warn），不算失败。

---

### S3 · 纽约 + 伦敦

**目标**：完成两个「文件型」来源，验证批量下载 + 多表解析路径。

**动作**

1. `adapters/bea.py`：下载 `CAGDP1.zip` → 内存解压 → 通配匹配州文件 → 过滤 5 县 + `LineCode=3` → 按年求和。
2. `adapters/census.py`：三个 vintage 的县级人口文件（2000–2010 intercensal、2010–2020、2020–2024），按年分段取 5 县合计；注意 `latin-1` 编码与 FIPS 补零不一致。
3. `adapters/ons.py`：解析数据页取最新 xlsx（`1998to2024`），同一工作簿的 `Table 5` 取 London GDP、`Table 6` 取 London 人口——**人口与 GDP 同源同版本**，无需另找 ONS 人口数据集。
4. 面积：纽约、伦敦为行政区常数，在 `config/cities.yaml` 标 `area.kind: constant` 并附来源，由 `ingest_constant_areas()` 统一写入 `fact`（`source_id = REF-GEO-{CODE}`，`acquisition = manual`）。

**产出**：纽约 7 个可用年份（2000、2025 空）、伦敦 8 个可用年份（2025 空）的 GDP + 人口 + 面积；覆盖 33/67。

**自检**

```bash
uv run citygdp fetch --source bea,census,ons
uv run citygdp ingest --source all
uv run citygdp doctor            # 覆盖矩阵应点亮纽约、伦敦
uv run pytest -q                 # 含三个适配器的解析回归
```

**抽检数字**

| 项 | 期望值 |
|---|---|
| 纽约 5 县合计 2024 GDP | ≈ 13,777.8 亿美元（BEA 2026-02-05 版） |
| 纽约 2024 人口 | ≈ 848 万 |
| 伦敦 2024 GDP | 与 ONS 发布值一致（英镑，需现场核对） |
| 伦敦 2024 人口 | 9,089,736 |
| 伦敦 2024 GDP | 656,291 百万英镑 |
| 纽约 2024 人口 | 8,478,072 |

**需你确认**：纽约人口在 2010/2020 两处因 vintage 切换产生的跳变，是否接受「以最新 vintage 为主、旧年份回退」的处理方式。

**风险**：ONS 页面改版导致 xlsx 链接解析失败 → 人工下载兜底。

---

### S4 · 东京

**目标**：完成口径最特殊的一城（年度制、日文表、开放数据与年报双路径）。

**动作**

1. `adapters/tokyo.py`：从年報页解析最新 `kk{YY}qv0110.csv`（GDP）与 `kk{YY}qv0410.csv`（人口），直接取 CSV，无需开放数据 API。
2. 年度 → 年份映射：`令和 5 年度 → 2023`（起始年），`fact.note` 记录「年度，4 月–翌年 3 月」。
3. 面积：2,194.07 km²，走 `REF-GEO-TYO` 常数。
4. **不做跨版本拼接**：旧版年報可补 2000/2005/2010，但 2005 年跨版修订 +7.2%、2010 年 +6.7%，拼接会在 2010→2015 之间造成约 7% 的口径断点。按 DR-15 留空并上报。

**产出**：东京 4 个可用年份（2015、2020、2022、2023）的 GDP + 人口 + 面积；2000/2005/2010/2024/2025 留空。覆盖 37/64。

**自检**

```bash
uv run citygdp fetch --source tokyo
uv run citygdp ingest --source tokyo
sqlite3 data/db/city_gdp.sqlite "select year, value/1e6 from fact
  where entity_code='TYO' and indicator='gdp_lcu' order by year;"
```

**抽检数字**

| 项 | 期望值 |
|---|---|
| 东京 FY2023 都内総生産（名目） | 125,018,533 百万日元 |
| 东京 2023 人口 | 14,096,000 |

**需你确认**：① 东京「年度按起始年对齐」（FY2023 → 2023）是否认可；② 2000/2005/2010 是留空，还是接受约 7% 的拼接断点（或改用其他长期序列，见 S4 验收记录）。

**风险**：开放数据序列可能不覆盖 2000 年 → 回退年报；日文 PDF 解析成本高，必要时人工转录 7 个数字（可接受）。

---

### S5 · 中国三市

**目标**：完成唯一需要人工介入的一组来源，并落实深圳深汕口径。

**动作**

1. `adapters/china.py`：支持两种输入——
   - 统计公报 HTML（近期年份）：解析 GDP、常住人口；
   - 年鉴表格（历史年份）：Excel/PDF/网页表格。
2. 若自动抓取失败：生成 `data/manual/CN-BJ|CN-SH|CN-SZ/` 下的下载清单，人工投递后由同一 parser 解析。
3. 人口：年平均常住人口 =（上年末 + 本年末）/ 2；2000 年需 1999 年末值。
4. **深圳口径核实**：确认 2024/2025 年官方全市 GDP 是否含深汕特别合作区。
   - 已含 → 直接采用，`fact.note` 注明；
   - 未含 → **暂停**并提交你确认，不自行加总。
5. 面积：北京 16,410.54 km²、上海 6,340.5 km²、深圳 1,997.47 km²（2024 起 2,465.77 km²）。

**产出**：京沪深各 9 年 × {GDP、人口、面积}。

**自检**

```bash
uv run citygdp fetch --source china
uv run citygdp ingest --source china
uv run citygdp validate --rule R4,R7,R9
```

**抽检数字**

| 项 | 期望值 |
|---|---|
| 北京 2025 GDP | 52,073.4 亿元 |
| 上海 2025 GDP | 56,708.71 亿元 |
| 深圳 2025 GDP | 38,731.80 亿元 |
| 北京 2025 人均 GDP | 23.9 万元（官方口径） |

**需你确认**：深圳 2024 年起含深汕的处理结果（含/未含官方口径），以及三市历史序列取用的年鉴版本。

**风险**：最高。年鉴站点反爬、页面结构多变；预留手工兜底。

---

### S6 · 派生指标与 QA

**目标**：把 `fact` 变成 4 项指标，并让所有校验规则跑通。

**动作**

1. `build.py`：按 DESIGN §8.2 计算 `gdp_usd`、`primacy_pct`、`gdp_per_capita_usd`、`gdp_per_km2_usd`；写入 `inputs_json`。
2. `validate.py`：实现 R1–R11，结果写 `issue`。
3. 缺失白名单校验（R9）：白名单直接来自 SPEC §4.3。
4. 生成 `output/qa/S6.md`：覆盖率表、异常清单、锚点比对结果。

**产出**：`derived` 表全量、`issue` 表、`output/qa/S6.md`。

**自检**

```bash
uv run citygdp build
uv run citygdp validate
sqlite3 data/db/city_gdp.sqlite \
  "select metric, count(*) from derived group by 1;"
```

**抽检数字**

| 项 | 期望值 |
|---|---|
| 东京 2023 首位度 | ≈ 20–22% |
| 伦敦 2023 首位度 | ≈ 22–25% |
| 纽约 2024 首位度 | ≈ 4–5% |
| 北京 2025 首位度 | ≈ 3.5–4% |
| 香港 2024 首位度 | ≈ 2–2.5% |
| 新加坡任意年首位度 | 100.00 |

**需你确认**：`output/qa/S6.md` 中的异常清单——每条要么解释清楚，要么修正。

**风险**：若世界银行 2025 年国家 GDP 未发布，2025 年首位度为空，需你确认接受。

---

### S7 · 导出与交付

**目标**：产出最终交付物，并通过 SPEC §11 的全部验收项。

**动作**

1. `export.py`：生成 `output/城市GDP分析.xlsx`（**单表**：指标/年份/8 城/备注，4 个指标块纵向堆叠）、`output/数据来源登记表.xlsx`、`output/数据说明.md`。
2. 格式：表头上方 2 行口径说明、指标名含单位、小数位、冻结窗格 `C4`、列宽、隔块底色、空值留空、表末脚注。
3. 追加 `output/qa/S7.md`：验收清单逐条打勾 + 重建验证。

**离线重建验证（关键）**

```bash
mv data/db/city_gdp.sqlite /tmp/  # 备份而非删除
uv run citygdp ingest --source all
uv run citygdp build && uv run citygdp validate && uv run citygdp export
# 对比导出文件的关键单元格与备份前一致
```

**产出**：三个交付文件。

**自检**

```bash
uv run citygdp export
python -c "import openpyxl; wb=openpyxl.load_workbook('output/城市GDP分析.xlsx'); \
ws=wb.active; print(ws.title, ws.max_row, ws.max_column)"
# 期望：工作表名 城市GDP；max_column = 11；max_row ≈ 44（3 行表头 + 36 行数据 + 空行 + 脚注）
```

人工检查四项：① 4 个指标块各 9 行、年份升序；② 空单元格确实为空（不是 0 或 "nan"）；③ 数字格式与单位匹配；④ 脚注齐备。

**需你确认**：最终交付物验收。

**风险**：低。

---

## 4. 验收方式

每一步完成后我会提供：

1. **一句话结论**：本步做了什么、结果如何。
2. **证据**：命令输出摘要、`output/qa/S{N}.md`、关键数字对照表。
3. **变更清单**：新增/修改了哪些文件（方便你提交 git）。
4. **待确认项**：本步需要你拍板的具体问题（如无则明确说「无」）。

你确认后我才进入下一步。若某步失败，我会说明失败原因和两个备选方案，而不是自行降级口径。

---

## 5. 完成定义（DoD）

项目完成需同时满足：

- [ ] `uv run citygdp all` 从零可跑通；
- [ ] 删除 `data/db` 后可离线重建，导出结果一致；
- [ ] SPEC §11 的 7 条验收标准全部通过；
- [ ] `output/qa/` 下每一步的验收记录齐备；
- [ ] 来源登记表中每条记录都能对应到 `data/raw` 下的真实文件与哈希；
- [ ] 交付表中没有任何插值、外推或未标注的估算值。

---

## 6. 需要你提前准备的事

1. **手工下载的配合**（仅在中国三市自动抓取失败时触发）：我会给出文件名与来源页，你下载后放入 `data/manual/CN-*/`。
2. **深圳口径的判断**（S5）：若官方未含深汕，需要你决定是否接受「只到 2023 年口径 + 备注」或另想办法。
3. **东京年度对齐的确认**（S4）。
