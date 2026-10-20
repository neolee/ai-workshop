# 城市 GDP 数据分析

## 需求目标

分析国际经济中心主要城市的经济总量指标情况。

- 城市：纽约，伦敦，东京，新加坡，北京，上海，深圳，香港
- 年份：2000，2005，2010，2015，2020，2022，2023，2024，2025（如果有数据）
- 统计指标：
  - 国内生产总值 GDP（亿美元）
  - 经济首位度
  - 人均 GDP（美元/人）
  - 地均 GDP（美元/平方公里）

> 金额统计口径：按各国（地区）官方数据，如果数据取所在国货币，按世界银行年度汇率平均值统一到美元金额。

## 原始数据来源

- 下面列出了目前建议的原始数据来源，仅供参考，需在任务中进行确认，如有更简单的可信数据获取方式可以提出建议
- 最终确认采纳的原始数据，需将数据的来源及更新时间（有效期）正确记录在案，可以设计一个专门的表格来进行记录（指标项、来源部门、网址、更新时间等）

### 宏观经济指标 - 城市 GDP

| 城市             | 数据来源                                | 官方 URL                                                     | 更新时间 | 备注                                                         |
| ---------------- | --------------------------------------- | ------------------------------------------------------------ | -------- | ------------------------------------------------------------ |
| 纽约 NYC         | U.S. Bureau of  Economic Analysis (BEA) | https://apps.bea.gov/itable/?ReqID=70&step=1                 | 2026.03  | 在 BEA 官网选择 GROSS  DOMESTIC PRODUCT (GDP) BY COUNTY → by county 表格，不要直接用 "New York - Newark - Jersey City" 都会区数据，需要将五个郡县加总起来得出：Bronx, Kings  (Brooklyn), New York (Manhattan), Queens, Richmond (Staten Island) |
| 伦敦 London      | Office for National  Statistics (ONS)   | https://www.ons.gov.uk/economy/grossdomesticproductgdp/datasets/regionalgrossdomesticproductallnutslevelregions |          | 下载表格 → 筛选 "Region: London" → Table 5                   |
| 东京 Tokyo       | 東京都総務局統計部 (Tokyo  Metro Govt)  | https://www.toukei.metro.tokyo.lg.jp/keizaik/nenpou/kkne-index.htm |          | 进入官网找 "都民経済計算" （Prefectural Accounts）           |
| 新加坡 Singapore | Department of  Statistics (SingStat)    | https://tablebuilder.singstat.gov.sg/table/TS/M014871        |          | 下载 "GDP at Current Market Prices"，注意筛选                |
| 香港 Hong Kong   | 政府统计处 (C&SD)                       | https://www.censtatd.gov.hk/sc/scode250.html                 |          | 进入“国民收入及国际收支” → “本地生产总值” → 选择“以当时市价计算” → 表 310-31002 |
| 北京 Beijing     | 北京市统计局                            | http://tjj.beijing.gov.cn/tjsj_31/                           |          | 查阅《北京统计年鉴》中的“综合核算”章节（通常是表3-1） → “地区生产总值 GDP” |
| 上海 Shanghai    | 上海市统计局                            | https://tjj.sh.gov.cn/tjnj/index.html                        |          | 《上海统计年鉴》“综合核算”章节                               |
| 深圳 Shenzhen    | 深圳市统计局                            | http://tjj.sz.gov.cn/tjsj/tjnj/                              |          | 《深圳统计年鉴》“综合核算”章节                               |

### 宏观经济指标 - 国家/地区 GDP

计算经济首位度所需的国家/地区 GDP 规模数据采用 World Bank / IMF 数据：
https://data.worldbank.org/indicator/NY.GDP.MKTP.CD 

> 为了统一口径计算占比，建议国家GDP统一使用  World Bank 数据，确保美元汇率折算标准一致

### 基础数据 - 城市人口与面积

- 国外：

  - 美国人口普查局 https://www.census.gov/
    - 首页选择 Data & Maps，进入 Tables and Maps，根据郡县选取五个郡县导出，指标选择Populations and People
  - 英国国家统计局 https://data.london.gov.uk/dataset/modelled-population-backseries-ex9jd
    - 推荐使用 London Datastore 的 "Housing-led population projections" 或 ONS 的年中人口预估
  - （日本）东京统计局 https://www.toukei.metro.tokyo.lg.jp/jsuikei/js-index2.htm
    - 下载总数 Excel 表格
  - 新加坡统计局公开数据 https://tablebuilder.singstat.gov.sg/table/TS/M810001
    - 表 110-01001 → 按性別及年齡組別劃分的人口 → 选取总数

- 国内：

  - 北京市统计局 http://tjj.beijing.gov.cn/tjsj_31/
  - 上海市统计局 https://tjj.sh.gov.cn/tjnj/index.html
  - 深圳市统计局 http://tjj.sz.gov.cn/tjsj/tjnj/
    - 2024 年后纳入深圳合作区相关指标
  - 香港采用中央人民政府驻香港特别行政区联络办公室数据 https://www.censtatd.gov.hk/en/EIndexbySubject.html?scode=460&pcode=B1010003

> 考虑到行政面积可获得性和准确性，以各地统计局官网公布最新统计年鉴或者调查表为准，东京、上海、北京为行政区划面积，其它城市为陆地面积