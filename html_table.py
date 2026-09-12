"""
웹페이지(HTML)에서 표를 읽어오는 도구입니다.

[왜 직접 만들었는가]
원래는 pandas의 read_html 기능을 썼습니다. 그런데 배포 서버에서 연결 진단을
해보니 ImportError(필요한 부품을 못 찾음)가 났습니다. read_html은 겉보기엔
pandas 기능이지만, 실제로 HTML을 해석할 때는 lxml이라는 별도 부품을 추가로
필요로 합니다. 배포 서버에서는 이 부품을 못 찾는 상태였고, 그 결과 네이버에서
재무데이터도 주가도 못 읽고 있었습니다.

그래서 이 파일은 파이썬에 기본으로 들어있는 기능(html.parser)만 써서 표를
읽습니다. 추가로 설치할 부품이 전혀 없기 때문에, 배포 서버의 설치 상태와
상관없이 항상 동작합니다.

[2026-09-12 보강 1 - 닫는 표시가 빠진 HTML 대응]
네이버처럼 오래된 방식으로 만들어진 페이지는 </td>, </tr>, </table> 같은
'끝났다는 표시'를 생략하는 경우가 많습니다. 예전 버전은 이 표시가 나올 때만
칸과 줄을 완성했기 때문에, 표시가 없으면 표를 통째로 못 읽었습니다.
이제는 새 칸(<td>)이나 새 줄(<tr>)이 시작되면 앞의 것을 자동으로 닫고,
문서가 끝나면 남아있는 것도 모두 정리합니다.

[2026-09-12 보강 2 - 글자 깨짐(인코딩) 대응]
한글 페이지는 글자를 저장하는 방식이 두 가지(EUC-KR 계열, UTF-8)입니다.
방식을 잘못 골라서 읽으면 글자가 전부 깨져서, '매출액' 같은 단어를 찾을 수
없게 됩니다(표가 분명히 있는데 '표를 못 찾았다'고 나오는 원인). 그래서
decode_response()가 두 방식으로 모두 읽어본 뒤, 한글이 제대로 나온 쪽을
자동으로 고릅니다.

읽어온 표는 아래 형태의 파이썬 자료로 돌려줍니다.
  table = [
      [ {"text": "매출액", "colspan": 1, "rowspan": 1, "header": True}, ... ],   # 한 줄
      ...
  ]
"""

import re
from html.parser import HTMLParser

# 페이지 안에 적혀있는 '글자 저장 방식' 표시를 찾는 규칙입니다.
_CHARSET_IN_HTML = re.compile(rb"""charset\s*=\s*["']?\s*([A-Za-z0-9_\-]+)""", re.I)
_CHARSET_IN_HEADER = re.compile(r"""charset\s*=\s*["']?\s*([A-Za-z0-9_\-]+)""", re.I)

# 제대로 읽혔는지 판단할 때 쓰는 '한글이라면 당연히 있을 법한 단어'들입니다.
_KOREAN_HINTS = (
    "매출액",
    "영업이익",
    "당기순이익",
    "주요재무정보",
    "종가",
    "거래량",
    "날짜",
    "네이버",
    "금융",
)


def _to_int(value, default=1):
    try:
        number = int(str(value).strip())
        return number if number > 0 else default
    except (TypeError, ValueError):
        return default


# ----------------------------------------------------------------------
# 글자 저장 방식(인코딩) 자동 판별
# ----------------------------------------------------------------------
def _candidate_encodings(raw_bytes, declared=None):
    """시도해볼 글자 저장 방식 목록을 만듭니다(중복 제거, 순서 유지)."""
    candidates = [declared]

    found = _CHARSET_IN_HTML.search(raw_bytes[:4096])
    if found:
        candidates.append(found.group(1).decode("ascii", "ignore"))

    candidates.extend(["cp949", "utf-8"])

    normalized = []
    for name in candidates:
        text = (name or "").strip().lower()
        # euc-kr은 cp949에 포함되는 방식입니다. cp949가 더 많은 글자를 읽을 수
        # 있어서, euc-kr로 적혀 있어도 cp949로 읽습니다.
        if text in ("euc-kr", "euckr", "euc_kr", "ks_c_5601-1987", "ksc5601"):
            text = "cp949"
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def decode_html_bytes(raw_bytes, declared=None):
    """
    받아온 페이지(바이트)를 글자로 바꿉니다.

    방식을 여러 개 시도해보고, 한글이 가장 제대로 나온 결과를 고릅니다.
    (깨진 글자 '' 가 적을수록, 한글 단어가 많이 보일수록 좋은 결과입니다.)
    """
    if isinstance(raw_bytes, str):
        return raw_bytes

    best_text = None
    best_score = None

    for encoding in _candidate_encodings(raw_bytes, declared):
        try:
            text = raw_bytes.decode(encoding, errors="replace")
        except (LookupError, UnicodeDecodeError):
            continue
        score = sum(text.count(word) for word in _KOREAN_HINTS) * 10
        score -= text.count("�")  # 깨진 글자 수만큼 감점
        if best_score is None or score > best_score:
            best_text, best_score = text, score

    if best_text is None:
        best_text = raw_bytes.decode("utf-8", errors="replace")
    return best_text


def detect_encoding(raw_bytes, declared=None):
    """어떤 방식으로 읽었는지 이름만 돌려줍니다(진단 화면 표시용)."""
    best_name = None
    best_score = None
    for encoding in _candidate_encodings(raw_bytes, declared):
        try:
            text = raw_bytes.decode(encoding, errors="replace")
        except (LookupError, UnicodeDecodeError):
            continue
        score = sum(text.count(word) for word in _KOREAN_HINTS) * 10
        score -= text.count("�")
        if best_score is None or score > best_score:
            best_name, best_score = encoding, score
    return best_name or "utf-8"


def decode_response(response):
    """requests로 받아온 응답을 글자로 바꿉니다(위 함수를 그대로 사용)."""
    declared = None
    try:
        content_type = response.headers.get("Content-Type", "")
        found = _CHARSET_IN_HEADER.search(content_type or "")
        if found:
            declared = found.group(1)
    except Exception:
        declared = None
    return decode_html_bytes(response.content, declared)


# ----------------------------------------------------------------------
# 표 읽기
# ----------------------------------------------------------------------
class _TableCollector(HTMLParser):
    """HTML 글자를 처음부터 끝까지 훑으면서 <table> 안의 내용을 모읍니다."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []          # 다 읽은 표들
        self._open_tables = []    # 지금 읽는 중인 표들(표 안에 표가 있는 경우 대비)
        self._row = None
        self._cell = None

    # --- 내부 정리용 ---
    def _close_cell(self):
        if self._cell is None:
            return
        text = " ".join("".join(self._cell["parts"]).split())
        cell = {
            "text": text,
            "colspan": self._cell["colspan"],
            "rowspan": self._cell["rowspan"],
            "header": self._cell["header"],
        }
        if self._row is None:
            self._row = []  # <tr> 없이 <td>가 나오는 잘못된 HTML도 살려둡니다.
        self._row.append(cell)
        self._cell = None

    def _close_row(self):
        self._close_cell()
        if self._row is None:
            return
        if self._open_tables and self._row:
            self._open_tables[-1].append(self._row)
        self._row = None

    def _close_table(self):
        self._close_row()
        if self._open_tables:
            self.tables.append(self._open_tables.pop())

    # --- HTMLParser가 불러주는 함수들 ---
    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "table":
            self._close_row()          # 앞 표의 정리되지 않은 줄을 먼저 마무리
            self._open_tables.append([])
        elif tag == "tr" and self._open_tables:
            self._close_row()          # 닫는 표시가 없어도 앞 줄을 마무리
            self._row = []
        elif tag in ("td", "th") and self._open_tables:
            self._close_cell()         # 닫는 표시가 없어도 앞 칸을 마무리
            if self._row is None:
                self._row = []
            self._cell = {
                "parts": [],
                "colspan": _to_int(attributes.get("colspan"), 1),
                "rowspan": _to_int(attributes.get("rowspan"), 1),
                "header": tag == "th",
            }

    def handle_startendtag(self, tag, attrs):
        # <td />처럼 혼자 닫는 형태는 빈 칸으로 처리합니다.
        if tag in ("td", "th") and self._open_tables:
            self.handle_starttag(tag, attrs)
            self._close_cell()

    def handle_data(self, data):
        if self._cell is not None:
            self._cell["parts"].append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th"):
            self._close_cell()
        elif tag == "tr":
            self._close_row()
        elif tag == "table":
            self._close_table()

    def close(self):
        super().close()
        # 문서가 끝났는데도 닫히지 않고 남아있는 것들을 모두 정리합니다.
        while self._open_tables:
            self._close_table()
        self._close_row()


def parse_tables(html_text):
    """HTML 글자를 받아서, 그 안의 모든 표를 읽어 목록으로 돌려줍니다."""
    collector = _TableCollector()
    try:
        collector.feed(html_text)
    except Exception:
        # 형식이 심하게 망가진 페이지라도, 그때까지 읽은 표는 살려서 돌려줍니다.
        pass
    collector.close()
    return [table for table in collector.tables if table]


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
