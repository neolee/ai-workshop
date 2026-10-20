"""深圳市统计局：统计年鉴（整本 PDF，文本层）+ 年度统计公报。

年鉴只提供整本 PDF（约 12 MB），但**有文本层**，可用 pypdf 抽取：
  表 2-2 地区生产总值（1979–上年），单位万元
  表 3-2 人口、出生、死亡及自然增长（1979–上年），年末常住人口，单位万人

抓取阶段即抽取全文并落盘为 `shenzhen.txt`，使 ingest 不需重复解析 PDF。
最新一年（2025）从统计公报取。
"""

from __future__ import annotations

import re
from pathlib import Path

from pypdf import PdfReader

from ._html import decode_page
from .base import Fact, Fetched, SourceMeta, commit_raw

NAME = "shenzhen"
LIST_URL = "https://tjj.sz.gov.cn/zwgk/zfxxgkml/tjsj/tjnj/index.html"
BULLETIN_URL = "https://tjj.sz.gov.cn/zwgk/zfxxgkml/tjsj/tjgb/content/post_12803919.html"

PAGE_SEP = "\f"


class ShenzhenAdapter:
    name = NAME
    dataset_keys = ("SZX-TJNJ", "SZX-GB")

    def fetch(self, client, raw_root: Path) -> list[Fetched]:
        listing = decode_page(client.get(LIST_URL).content)
        editions: list[tuple[str, str]] = []
        for href, inner in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', listing, flags=re.S):
            label = re.sub(r'<[^>]+>', " ", inner)
            match = re.search(r"深圳统计年鉴\s*(20\d\d)", label)
            if match and href.endswith(".html"):
                editions.append((href, match.group(1)))
        if not editions:
            raise ValueError("年鉴列表页未找到年份条目")
        detail_url, year = max(editions, key=lambda x: int(x[1]))

        detail = decode_page(client.get(detail_url).content)
        pdf_match = re.search(r'href="([^"]+\.pdf)"', detail)
        if pdf_match is None:
            raise ValueError("年鉴页未找到 PDF 附件")
        pdf_url = pdf_match.group(1)
        pdf_response = client.get(pdf_url)

        text = _extract_text(pdf_response.content)
        meta = SourceMeta(
            id=f"SZX-TJNJ-{year}",
            dataset_key="SZX-TJNJ",
            city_code="SZX",
            indicator="gdp+population",
            organization="深圳市统计局",
            dataset_title=f"深圳统计年鉴{year} — 表2-2 地区生产总值、表3-2 人口",
            table_id="2-2 / 3-2",
            url=pdf_url,
            vintage=str(year),
            published_at=None,
            notes="整本 PDF 的文本层抽取；生产总值为万元，人口为年末常住人口（万人）",
        )
        results = [
            commit_raw(
                raw_root,
                meta,
                [("shenzhen.pdf", pdf_response), ("shenzhen.txt", _as_response(text, pdf_response))],
            )
        ]

        bulletin = client.get(BULLETIN_URL)
        results.append(
            commit_raw(
                raw_root,
                SourceMeta(
                    id="SZX-GB-2025",
                    dataset_key="SZX-GB",
                    city_code="SZX",
                    indicator="gdp+population",
                    organization="深圳市统计局",
                    dataset_title="深圳市2025年国民经济和社会发展统计公报",
                    table_id=None,
                    url=BULLETIN_URL,
                    vintage="2025",
                    published_at="2026-05-25",
                    notes="初步核算数；年末常住人口",
                ),
                [("bulletin.html", bulletin)],
            )
        )
        return results

    def parse(self, fetched: Fetched) -> list[Fact]:
        if fetched.meta.dataset_key == "SZX-GB":
            return _parse_bulletin(fetched.directory / "bulletin.html")

        text = (fetched.directory / "shenzhen.txt").read_text(encoding="utf-8")
        gdp = _page_series(text, ("2-2", "地区生产总值", "第一产业"), exclude="续表")
        pop = _page_series(text, ("3-2", "人口、出生、死亡"), exclude=None)

        facts = [
            Fact("city", "SZX", "gdp_lcu", y, v * 1e4, "CNY", note="现价，万元换算")
            for y, v in sorted(gdp.items())
        ]
        facts += [
            Fact("city", "SZX", "population", y, v * 1e4, "person", note="年末常住人口，万人换算")
            for y, v in sorted(pop.items())
        ]
        facts += [
            Fact(
                "city", "SZX", "area_km2", y,
                2465.77 if y >= 2024 else 1997.47, "km2",
                note="2024 年起含深汕特别合作区（+468.3 km²）" if y >= 2024 else None,
            )
            for y in range(1979, 2026)
        ]
        return facts


def _extract_text(pdf_bytes: bytes) -> str:
    import io

    reader = PdfReader(io.BytesIO(pdf_bytes))
    return PAGE_SEP.join((page.extract_text() or "") for page in reader.pages)


def _as_response(text: str, original):
    from ..http import Response

    return Response(
        url=original.url + "#text",
        status=original.status,
        content=text.encode("utf-8"),
        headers=original.headers,
        fetched_at=original.fetched_at,
    )


def _page_series(text: str, markers: tuple[str, ...], exclude: str | None) -> dict[int, float]:
    for page in text.split(PAGE_SEP):
        if not all(m in page for m in markers):
            continue
        if exclude and exclude in page:
            continue
        series: dict[int, float] = {}
        for line in page.splitlines():
            match = re.match(r"\s*((?:19|20)\d{2})\s+([\d,]+(?:\.\d+)?)", line)
            if match:
                series[int(match.group(1))] = float(match.group(2).replace(",", ""))
        if series:
            return series
    raise ValueError(f"PDF 中未找到表格：{markers}")


def _parse_bulletin(path: Path) -> list[Fact]:
    html = decode_page(path.read_bytes())
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)

    gdp = re.search(r"深圳地区生产总值\s*([\d,]+\.?\d*)\s*亿元", text)
    pop = re.search(r"年末常住人口\s*([\d,]+\.?\d*)\s*万人", text)
    if not gdp or not pop:
        raise ValueError("公报中未找到生产总值或常住人口")

    return [
        Fact("city", "SZX", "gdp_lcu", 2025, float(gdp.group(1).replace(",", "")) * 1e8,
             "CNY", status="preliminary", note="初步核算"),
        Fact("city", "SZX", "population", 2025, float(pop.group(1).replace(",", "")) * 1e4,
             "person", status="preliminary", note="年末常住人口"),
    ]
