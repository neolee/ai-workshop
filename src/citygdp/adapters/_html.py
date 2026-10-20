"""极简 HTML 表格解析：把 <table> 拆成二维文本数组。

中文统计站点的在线年鉴多为 FrontPage/Excel 导出的 HTML 表格，
结构简单，用标准库即可，不引入 BeautifulSoup。
"""

from __future__ import annotations

import re
from html.parser import HTMLParser


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._row is not None:
            self._row.append(re.sub(r"\s+", "", "".join(self._cell or [])))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if any(self._row):
                self.rows.append(self._row)
            self._row = None


def table_rows(text: str) -> list[list[str]]:
    parser = _TableParser()
    parser.feed(text)
    return parser.rows


def decode_page(raw: bytes, encodings: tuple[str, ...] = ("utf-8", "gb18030")) -> str:
    for encoding in encodings:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")
