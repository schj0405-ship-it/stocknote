import pandas as pd
import streamlit as st

from auth import render_auth_ui
from get_financial_data import (
    REPRT_CODES,
    find_corp_code,
    find_stock_code,
    format_amount,
    get_per,
)

st.set_page_config(page_title="스톡노트 - 재무데이터 조회", layout="centered")

render_auth_ui()  # 이 화면은 로그인 없이도 누구나 쓸 수 있지만, 사이드바에 로그인 상태는 보여줍니다.

st.title("재무데이터 조회")

with st.form("search_form"):
    company_name = st.text_input("회사 이름", placeholder="예: 삼성전자")
    bsns_year = st.text_input("사업연도", value="2025")
    reprt_label = st.selectbox("보고서 종류", list(REPRT_CODES.keys()), index=3)
    submitted = st.form_submit_button("조회")

if submitted:
    if not company_name.strip():
        st.error("회사 이름을 입력해주세요.")
    else:
        corp_code = find_corp_code(company_name.strip())
        stock_code = find_stock_code(company_name.strip())

        if corp_code is None:
            st.error(f"'{company_name}'을(를) corp_codes.csv에서 찾지 못했습니다.")
        else:
            reprt_code = REPRT_CODES[reprt_label]
            result = get_per(corp_code, stock_code, bsns_year, reprt_code)

            if "오류" in result:
                st.error(f"조회 실패: {result['오류']}")
            else:
                st.subheader(f"{company_name} {bsns_year}년 {reprt_label}")

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

                if stock_code is None:
                    st.caption(
                        "corp_codes.csv에서 종목코드를 못 찾아 현재가·PER을 조회하지 못했습니다."
                    )
                elif reprt_label != "사업보고서(연간)":
                    st.caption(
                        "PER은 지배주주순이익을 기준으로 계산하는데, "
                        f"지금 고르신 '{reprt_label}'는 1년 전체가 아니라 "
                        "그 기간까지의 누적 순이익이라 PER이 실제보다 크게(부풀려) "
                        "나옵니다. 정확한 PER은 '사업보고서(연간)'으로 조회해주세요."
                    )
