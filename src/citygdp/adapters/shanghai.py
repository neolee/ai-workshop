"""上海市统计局：统计年鉴在线版 + 年度统计公报。

年鉴页面是 iframe 结构：
  年鉴索引 index.html → 年份页 → iframe tjnj{YYYY}.htm（目录）
  → 表页 C03/C0301.htm（框架）→ C03/C0301B.htm（数据）

表 3.1「上海市生产总值（1978～2024）」单位为亿元；
表 2.1「户数、人口、人口密度」第 2 列为年末常住人口（万人）。
最新一年的数据（2025）从统计公报取。
"""

from __future__ import annotations

import re
from pathlib import Path

from ._html import decode_page, table_rows
from .base import Fact, Fetched, SourceMeta, commit_raw

NAME = "shanghai"
SITE = "https://tjj.sh.gov.cn"
INDEX_URL = f"{SITE}/tjnj/index.html"
BULLETIN_URL = f"{SITE}/tjgb/20260330/e0772941e8e041eaaad2df850b44ef98.html"

GDP_TABLE_KEYWORD = "上海市生产总值（1978"
POP_TABLE_KEYWORD = "户数、人口、人口密度"


class ShanghaiAdapter:
    name = NAME
    dataset_keys = ("SHSI-TJNJ", "SHSI-GB")

    # -- 抓取 -----------------------------------------------------------
    def fetch(self, client, raw_root: Path) -> list[Fetched]:
        index = client.get(INDEX_URL)
        html = decode_page(index.content)

        editions = re.findall(r'href="(/tjnj/\d{8}/[0-9a-f]+\.html)"[^>]*>\s*(20\d\d)年上海统计年鉴', html)
        if not editions:
            raise ValueError("年鉴索引页未找到年份链接")
        path, year = max(editions, key=lambda x: int(x[1]))

        edition = client.get(f"{SITE}{path}")
        iframe = re.search(r'src="([^"]*tjnj(\d{4})\.htm)"', decode_page(edition.content))
        if iframe is None:
            raise ValueError("年份页未找到 iframe 地址")
        toc_src = iframe.group(1)
        toc_url = toc_src if toc_src.startswith("http") else f"{SITE}{toc_src}"
        folder = iframe.group(2)

        toc = client.get(toc_url)
        gdp_rel = _find_table(toc.content, GDP_TABLE_KEYWORD, folder)
        pop_rel = _find_table(toc.content, POP_TABLE_KEYWORD, folder)

        items = [
            ("gdp.htm", client.get(f"{SITE}/tjnj/{gdp_rel}")),
            ("population.htm", client.get(f"{SITE}/tjnj/{pop_rel}")),
        ]
        meta = SourceMeta(
            id=f"SHSI-TJNJ-{year}",
            dataset_key="SHSI-TJNJ",
            city_code="SHA",
            indicator="gdp+population",
            organization="上海市统计局",
            dataset_title=f"{year}年上海统计年鉴 — 表3.1 上海市生产总值、表2.1 户数人口",
            table_id="C0301 / C0201",
            url=toc_url,
            vintage=str(year),
            published_at=None,
            notes="生产总值 1978–上年；人口为年末常住人口",
        )
        results = [commit_raw(raw_root, meta, items)]

        bulletin = client.get(BULLETIN_URL)
        results.append(
            commit_raw(
                raw_root,
                SourceMeta(
                    id="SHSI-GB-2025",
                    dataset_key="SHSI-GB",
                    city_code="SHA",
                    indicator="gdp+population",
                    organization="上海市统计局",
                    dataset_title="2025年上海市国民经济和社会发展统计公报",
                    table_id=None,
                    url=BULLETIN_URL,
                    vintage="2025",
                    published_at="2026-03-30",
                    notes="初步核算数；年末常住人口",
                ),
                [("bulletin.html", bulletin)],
            )
        )
        return results

    # -- 解析 -----------------------------------------------------------
    def parse(self, fetched: Fetched) -> list[Fact]:
        if fetched.meta.dataset_key == "SHSI-GB":
            return _parse_bulletin(fetched.directory / "bulletin.html")

        gdp = _year_series(fetched.directory / "gdp.htm")
        pop = _year_series(fetched.directory / "population.htm")

        facts = [
            Fact("city", "SHA", "gdp_lcu", y, v * 1e8, "CNY", note="现价，亿元换算")
            for y, v in sorted(gdp.items())
        ]
        facts += [
            Fact("city", "SHA", "population", y, v * 1e4, "person", note="年末常住人口，万人换算")
            for y, v in sorted(pop.items())
        ]
        return facts


def _find_table(raw: bytes, keyword: str, folder: str) -> str:
    """在年鉴目录中定位表页，返回其数据框架的相对路径（如 2025tjnj/C03/C0301B.htm）。"""
    html = decode_page(raw)
    for match in re.finditer(r'd1=\d{4}tjnj/(C\d{4})\.htm"[^>]*>([^<]*)<', html):
        table, title = match.group(1), match.group(2)
        if keyword in title:
            return f"{folder}tjnj/{table[:3]}/{table}B.htm"
    raise ValueError(f"年鉴目录中未找到「{keyword}」表")


def _year_series(path: Path) -> dict[int, float]:
    text = decode_page(path.read_bytes())
    series: dict[int, float] = {}
    for row in table_rows(text):
        if len(row) < 2 or not re.fullmatch(r"(19|20)\d\d", row[0]):
            continue
        try:
            series[int(row[0])] = float(row[1].replace(",", ""))
        except ValueError:
            continue
    return series


def _parse_bulletin(path: Path) -> list[Fact]:
    html = decode_page(path.read_bytes())
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)

    gdp = re.search(r"全年实现地区生产总值\s*([\d,]+\.?\d*)\s*亿元", text)
    pop = re.search(r"全市常住人口为\s*([\d,]+\.?\d*)\s*万人", text)
    if not gdp or not pop:
        raise ValueError("公报中未找到生产总值或常住人口")

    return [
        Fact("city", "SHA", "gdp_lcu", 2025, float(gdp.group(1).replace(",", "")) * 1e8,
             "CNY", status="preliminary", note="初步核算"),
        Fact("city", "SHA", "population", 2025, float(pop.group(1).replace(",", "")) * 1e4,
             "person", status="preliminary", note="年末常住人口"),
    ]
