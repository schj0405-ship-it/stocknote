"""
웹페이지(HTML)에서 표를 읽어오는 도구입니다.

[왜 직접 만들었는가]
원래는 pandas의 read_html 기능을 썼습니다. 그런데 배포 서버에서 연결 진단을
해보니 ImportError(필요한 부품을 못 찾음)가 났습니다. read_html은 겉보기엔
pandas 기능이지만, 실제로 HTML을 해석할 때는 lxml이라는 별도 부품을 추가로
필요로 합니다. requirements.txt에 lxml을 적어놨는데도 배포 서버에서는 이
부품을 못 찾는 상태였고, 그 결과 네이버에서 재무데이터도 주가도 못 읽고
있었습니다.

그래서 이 파일은 파이썬에 기본으로 들어있는 기능(html.parser)만 써서 표를
읽습니다. 추가로 설치할 부품이 전혀 없기 때문에, 배포 서버의 설치 상태와
상관없이 항상 동작합니다.

읽어온 표는 아래 형태의 파이썬 자료로 돌려줍니다.
  table = [
      [ {"text": "매출액", "colspan": 1, "rowspan": 1, "header": True}, ... ],   # 한 줄
      ...
  ]
"""

from html.parser import HTMLParser


def _to_int(value, default=1):
    try:
        number = int(str(value).strip())
        return number if number > 0 else default
    except (TypeError, ValueError):
        return default


class _TableCollector(HTMLParser):
    """HTML 글자를 처음부터 끝까지 훑으면서 <table> 안의 내용을 모읍니다."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []          # 다 읽은 표들
        self._open_tables = []    # 지금 읽는 중인 표들(표 안에 표가 있는 경우 대비)
        self._row = None
        self._cell = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "table":
            self._open_tables.append([])
        elif tag == "tr" and self._open_tables:
            self._row = []
        elif tag in ("td", "th") and self._open_tables:
            self._cell = {
                "parts": [],
                "colspan": _to_int(attributes.get("colspan"), 1),
                "rowspan": _to_int(attributes.get("rowspan"), 1),
                "header": tag == "th",
            }

    def handle_data(self, data):
        if self._cell is not None:
            self._cell["parts"].append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th"):
            if self._cell is not None:
                text = " ".join("".join(self._cell["parts"]).split())
                cell = {
                    "text": text,
                    "colspan": self._cell["colspan"],
                    "rowspan": self._cell["rowspan"],
                    "header": self._cell["header"],
                }
                if self._row is not None:
                    self._row.append(cell)
                self._cell = None
        elif tag == "tr":
            if self._open_tables and self._row is not None:
                self._open_tables[-1].append(self._row)
            self._row = None
        elif tag == "table":
            if self._open_tables:
                self.tables.append(self._open_tables.pop())


def parse_tables(html_text):
    """HTML 글자를 받아서, 그 안의 모든 표를 읽어 목록으로 돌려줍니다."""
    collector = _TableCollector()
    collector.feed(html_text)
    collector.close()
    return collector.tables


def table_text(table):
    """표 전체의 글자를 한 줄로 이어붙입니다(원하는 표를 찾을 때 씁니다)."""
    return " ".join(cell["text"] for row in table for cell in row)


def split_header_and_data(table):
    """
    표를 '제목 줄'과 '내용 줄'로 나눕니다.
    제목 줄 = 칸이 전부 <th>인 줄, 내용 줄 = 그 외.
    """
    header_rows = [row for row in table if row and all(cell["header"] for cell in row)]
    data_rows = [row for row in table if row and not all(cell["header"] for cell in row)]
    return header_rows, data_rows
