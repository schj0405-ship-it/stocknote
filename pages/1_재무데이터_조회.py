import datetime

import pandas as pd
import streamlit as st

from auth import render_auth_ui
from company_search import search_companies
from get_financial_data import (
    REPRT_CODES,
    find_corp_code,
    find_stock_code,
    format_amount,
    get_per,
)
from quarterly_compare import (
    METRICS,
    build_comparison_data,
    build_quarter_list,
    compute_growth,
)

st.set_page_config(page_title="스톡노트 - 재무데이터 조회", layout="centered")

render_auth_ui()  # 이 화면은 로그인 없이도 누구나 쓸 수 있지만, 사이드바에 로그인 상태는 보여줍니다.

st.title("재무데이터 조회")

# 분기별 비교 표에서 지표별로 다른 배경색을 주기 위한 색상표.
# 흰색 배경 위에서 은은하게 잘 보이도록 옅은 파스텔톤으로 골랐습니다.
METRIC_COLORS = {
    "매출액": "rgba(59, 130, 246, 0.14)",     # 파란 계열
    "영업이익": "rgba(34, 197, 94, 0.14)",    # 초록 계열
    "당기순이익": "rgba(249, 115, 22, 0.14)",  # 주황 계열
}


def render_company_picker(state_key, label="회사 이름 검색"):
    """
    회사 이름을 입력하면 corp_codes.csv에서 비슷한 이름을 찾아 버튼 목록으로
    보여주고, 그중 하나를 클릭하면 그 회사가 "선택"되는 위젯입니다.
    (검색창에 입력 → 목록에서 클릭 → 선택 완료, 이 세 단계로 동작합니다.)

    state_key: 화면 안에 이 위젯을 여러 개 쓸 수 있도록 구분해주는 이름
               (예: "single", "compare")
    반환값: 지금까지 선택된 회사 이름 (아직 선택 안 했으면 빈 문자열 "")
    """
    query_key = f"{state_key}_query"
    selected_key = f"{state_key}_selected"

    if selected_key not in st.session_state:
        st.session_state[selected_key] = ""

    query = st.text_input(label, key=query_key, placeholder="예: 삼성전자")

    if query.strip():
        matches, total_count = search_companies(query.strip(), limit=15)
        if matches:
            st.caption("아래 목록에서 회사를 클릭해서 선택하세요.")
            for i, name in enumerate(matches):
                if st.button(name, key=f"{state_key}_match_{i}"):
                    st.session_state[selected_key] = name
                    st.rerun()
            if total_count > len(matches):
                st.caption(
                    f"검색된 {total_count}개 회사 중 {len(matches)}개만 보여주고 있어요. "
                    "원하는 회사가 안 보이면 이름을 한두 글자 더 입력해보세요."
                )
        else:
            st.caption("일치하는 회사가 없습니다.")

    if st.session_state[selected_key]:
        st.success(f"선택된 회사: **{st.session_state[selected_key]}**")
        if st.button("선택 취소", key=f"{state_key}_clear"):
            st.session_state[selected_key] = ""
            st.rerun()

    return st.session_state[selected_key]


def format_growth(rate):
    """
    compute_growth()가 돌려준 값(숫자 또는 "흑자전환"/"적자전환" 또는 None)을
    표에 보여줄 글자로 바꿔줍니다.
    """
    if rate is None:
        return "-"
    if isinstance(rate, str):
        return rate
    arrow = "▲" if rate > 0 else ("▼" if rate < 0 else "‒")
    return f"{arrow} {abs(rate):.1f}%"


def style_growth_cell(value):
    """
    증감률 칸을 작은 색깔 배지처럼 꾸며줍니다: 증가(▲, 흑자전환)는 초록,
    감소(▼, 적자전환)는 빨강. 흰색 배경에서 또렷하게 잘 보이도록 글자는
    진한 색을, 배경은 그보다 옅은 색을 같이 씁니다.
    """
    if isinstance(value, str):
        if value.startswith("▲") or value == "흑자전환":
            return "background-color: rgba(34, 197, 94, 0.15); color: #15803d; font-weight: 700"
        if value.startswith("▼") or value == "적자전환":
            return "background-color: rgba(239, 68, 68, 0.15); color: #b91c1c; font-weight: 700"
    return ""


def style_metric_row(row):
    """표의 각 줄(행)을 어떤 지표인지에 따라 다른 배경색으로 칠해줍니다."""
    metric = row.name[0]
    color = METRIC_COLORS.get(metric, "")
    return [f"background-color: {color}" for _ in row]


tab_single, tab_compare = st.tabs(["단일 조회", "여러 분기 비교"])

# ------------------------------------------------------------------
# 세부 메뉴 1: 단일 조회 (기존 기능 + 회사 이름 검색·클릭 선택 기능 추가)
# ------------------------------------------------------------------
with tab_single:
    st.caption("한 시점(분기·반기·연간)의 재무데이터와 PER을 조회합니다.")

    selected_company = render_company_picker("single")

    col1, col2 = st.columns(2)
    with col1:
        bsns_year = st.text_input("사업연도", value="2025", key="single_year")
    with col2:
        reprt_label = st.selectbox(
            "보고서 종류", list(REPRT_CODES.keys()), index=3, key="single_reprt"
        )

    if st.button("조회", key="single_submit"):
        if not selected_company:
            st.error("회사를 먼저 검색해서 선택해주세요.")
        else:
            corp_code = find_corp_code(selected_company)
            stock_code = find_stock_code(selected_company)

            if corp_code is None:
                st.session_state["single_result"] = {
                    "error": f"'{selected_company}'을(를) corp_codes.csv에서 찾지 못했습니다."
                }
            else:
                reprt_code = REPRT_CODES[reprt_label]
                result = get_per(corp_code, stock_code, bsns_year, reprt_code)
                st.session_state["single_result"] = {
                    "company": selected_company,
                    "year": bsns_year,
                    "reprt_label": reprt_label,
                    "stock_code": stock_code,
                    "result": result,
                }

    # 버튼을 누른 그 순간뿐 아니라, 다른 위젯을 눌러 화면이 다시 그려질 때도
    # 마지막 조회 결과가 계속 보이도록 session_state에서 꺼내서 보여줍니다.
    single_state = st.session_state.get("single_result")
    if single_state:
        if "error" in single_state:
            st.error(single_state["error"])
        else:
            result = single_state["result"]
            if "오류" in result:
                st.error(f"조회 실패: {result['오류']}")
            else:
                st.subheader(
                    f"{single_state['company']} {single_state['year']}년 {single_state['reprt_label']}"
                )

                per_text = "정보 없음" if result["PER"] is None else f"{result['PER']}배"
                shares_text = (
                    "정보 없음"
                    if result["유통주식수"] is None
                    else f"{result['유통주식수']:,}주"
                )

                rows = {
                    "매출액": format_amount(result["매출액"]),
                    "영업이익": format_amount(result["영업이익"]),
                    "당기순이익": format_amount(result["당기순이익"]),
                    "지배주주순이익": format_amount(result["지배주주순이익"]),
                    "현재가": format_amount(result["현재가"]),
                    "유통주식수": shares_text,
                    "PER": per_text,
                }

                df = pd.DataFrame({"항목": list(rows.keys()), "값": list(rows.values())})
                st.table(df.set_index("항목"))

                if single_state["stock_code"] is None:
                    st.caption(
                        "corp_codes.csv에서 종목코드를 못 찾아 현재가·PER을 조회하지 못했습니다."
                    )
                elif single_state["reprt_label"] != "사업보고서(연간)":
                    st.caption(
                        "PER은 지배주주순이익을 기준으로 계산하는데, "
                        f"지금 고르신 '{single_state['reprt_label']}'는 1년 전체가 아니라 "
                        "그 기간까지의 누적 순이익이라 PER이 실제보다 크게(부풀려) "
                        "나옵니다. 정확한 PER은 '사업보고서(연간)'으로 조회해주세요."
                    )

# ------------------------------------------------------------------
# 세부 메뉴 2: 여러 분기 비교 (신규)
# ------------------------------------------------------------------
with tab_compare:
    st.caption(
        "같은 회사의 여러 분기를 한 표에 나란히 놓고, 매출액·영업이익·당기순이익이 "
        "직전 분기보다 얼마나 늘었는지·줄었는지 비교합니다."
    )
    st.caption(
        "※ OpenDART는 1분기·반기·3분기·연간 누적 금액만 제공하기 때문에, "
        "2~4분기 금액은 누적 금액끼리 빼서 계산합니다 (예: 2분기 = 반기 누적 − 1분기)."
    )

    compare_company = render_company_picker("compare")

    current_year = datetime.date.today().year

    col1, col2, col3 = st.columns(3)
    with col1:
        start_year = st.number_input(
            "시작 연도",
            min_value=2015,
            max_value=current_year,
            value=current_year - 1,
            step=1,
            key="compare_start_year",
        )
    with col2:
        start_quarter = st.selectbox(
            "시작 분기",
            [1, 2, 3, 4],
            format_func=lambda q: f"{q}분기",
            key="compare_start_quarter",
        )
    with col3:
        n_quarters = st.slider(
            "비교할 분기 개수", min_value=2, max_value=8, value=4, key="compare_n"
        )

    quarters_preview = build_quarter_list(int(start_year), start_quarter, n_quarters)
    preview_text = " → ".join(f"{y}년 {q}분기" for y, q in quarters_preview)
    st.caption(f"비교 대상: {preview_text}")

    if st.button("분기 비교 조회", key="compare_submit"):
        if not compare_company:
            st.error("회사를 먼저 검색해서 선택해주세요.")
        else:
            corp_code = find_corp_code(compare_company)
            if corp_code is None:
                st.session_state["compare_result"] = {
                    "error": f"'{compare_company}'을(를) corp_codes.csv에서 찾지 못했습니다."
                }
            else:
                with st.spinner(
                    "여러 분기 데이터를 불러오는 중입니다... 분기 수가 많으면 시간이 좀 걸려요."
                ):
                    values, errors = build_comparison_data(corp_code, quarters_preview)
                st.session_state["compare_result"] = {
                    "company": compare_company,
                    "quarters": quarters_preview,
                    "values": values,
                    "errors": errors,
                }

    compare_state = st.session_state.get("compare_result")
    if compare_state:
        if "error" in compare_state:
            st.error(compare_state["error"])
        else:
            quarters = compare_state["quarters"]
            values = compare_state["values"]
            errors = compare_state["errors"]

            st.subheader(f"{compare_state['company']} 분기별 비교")

            labels = [f"{y}년 {q}분기" for y, q in quarters]
            index_tuples = []
            data_rows = []

            for metric in METRICS:
                amount_row = []
                growth_row = []
                for i, key in enumerate(quarters):
                    val = values[key][metric]
                    amount_row.append(format_amount(val))
                    if i == 0:
                        growth_row.append("-")
                    else:
                        prev_val = values[quarters[i - 1]][metric]
                        rate = compute_growth(prev_val, val)
                        growth_row.append(format_growth(rate))
                index_tuples.append((metric, "금액"))
                data_rows.append(amount_row)
                index_tuples.append((metric, "전분기 대비"))
                data_rows.append(growth_row)

            df = pd.DataFrame(
                data_rows,
                index=pd.MultiIndex.from_tuples(index_tuples, names=["지표", "구분"]),
                columns=labels,
            )

            styler = df.style.apply(style_metric_row, axis=1)
            # pandas 2.1부터는 applymap 대신 map을 쓰라고 권장하는데, 배포 서버의
            # pandas 버전이 정확히 몇인지 고정돼 있지 않아서 둘 다 지원하도록 처리합니다.
            if hasattr(styler, "map"):
                styler = styler.map(style_growth_cell)
            else:
                styler = styler.applymap(style_growth_cell)
            styled = styler.set_properties(**{"text-align": "center"})
            # column_order를 명시적으로 지정해서, 화면(특히 좁은 화면에서
            # 가로 스크롤할 때) 분기 순서가 뒤섞이지 않고 항상 시간 순서
            # 그대로(labels 순서 그대로) 보이도록 강제합니다.
            try:
                # 최신 Streamlit은 width="stretch"를 씁니다.
                st.dataframe(styled, width="stretch", column_order=labels)
            except TypeError:
                # 배포 서버의 Streamlit 버전이 예전 것이면 옛날 옵션으로 대신 시도합니다.
                st.dataframe(styled, use_container_width=True, column_order=labels)

            st.caption(
                "🟦 매출액 배경 · 🟩 영업이익 배경 · 🟧 당기순이익 배경  /  "
                "▲초록 = 직전 분기보다 증가, ▼빨강 = 직전 분기보다 감소, "
                "흑자전환·적자전환 = 손익이 반대로 바뀜"
            )
            st.caption("첫 분기는 비교할 이전 분기가 없어서 '-' 로 표시됩니다.")

            if errors:
                st.warning("일부 분기는 데이터를 가져오지 못했습니다.")
                for (y, q), msg in errors.items():
                    st.caption(f"- {y}년 {q}분기: {msg}")
