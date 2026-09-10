"""
재무데이터 조회 화면에서 회사 이름을 검색할 때 쓰는 함수입니다.
corp_codes.csv(1-3단계에서 만든 상장사 목록)에서, 입력한 글자가 이름에
들어가는 회사를 찾아 목록으로 돌려줍니다.
"""

import pandas as pd


def search_companies(query, limit=15):
    """
    query가 이름에 포함된 회사를 corp_codes.csv에서 찾아 리스트로 돌려줍니다.
    - 대소문자는 구분하지 않습니다.
    - 같은 이름이 중복으로 있으면 한 번만 보여줍니다.
    - 정확히 일치하는 이름 -> 그 글자로 시작하는 이름 -> 그 외 포함하는 이름
      순서로 정렬해서, 원하는 회사가 검색 결과 앞쪽에 나오게 합니다.
      (예: "삼성"만 입력하면 회사가 30곳 가까이 나오는데, 그중 "삼성으로 시작하는"
      회사를 앞으로 보내줍니다. 그래도 원하는 회사가 안 보이면, 이름을 한두 글자
      더 입력해서 검색 범위를 좁히면 됩니다.)

    반환값: (matches, total_count)
    - matches: 화면에 보여줄 회사 이름 목록 (최대 limit개)
    - total_count: 실제로 일치한 회사 전체 개수 (matches보다 많으면 더 있다는 뜻)
    """
    query = (query or "").strip()
    if not query:
        return [], 0

    df = pd.read_csv("corp_codes.csv", dtype=str)
    names = df["corp_name"].dropna().astype(str)
    lower_query = query.lower()
    mask = names.str.lower().str.contains(lower_query, regex=False)
    all_matches = names[mask].unique().tolist()

    def rank(name):
        lower_name = name.lower()
        if lower_name == lower_query:
            return (0, name)
        if lower_name.startswith(lower_query):
            return (1, name)
        return (2, name)

    all_matches.sort(key=rank)
    return all_matches[:limit], len(all_matches)
