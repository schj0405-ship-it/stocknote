from datetime import date

import pandas as pd
import streamlit as st

from auth import get_supabase_client, require_login

st.set_page_config(page_title="스톡노트 - 투자내역", layout="wide")
st.title("투자내역 입력")

# 로그인 안 되어 있으면 여기서 화면 실행이 멈추고, 로그인/회원가입 화면만 보여줍니다.
user = require_login()

# 로그인한 사용자의 인증 정보가 실려있는 연결 객체입니다.
# (이 객체로 trades 테이블에 접근하면, Supabase가 자동으로 "이 사람이 맞는지" 확인합니다.)
supabase = get_supabase_client()

# 표에서 쓰는 화면 표시용 번호/손익 칸 이름 (DB에는 저장되지 않는, 화면에서만 계산해서 보여주는 칸)
DISPLAY_NO_COL = "번호"
PROFIT_COL = "손익"

# 흰색 배경에서 이익(초록)·손실(빨강)을 또렷하게 보여주기 위한 색상.
# 1_재무데이터_조회.py의 증감률 배지 색과 통일했습니다.
PROFIT_COLOR = "#15803d"
LOSS_COLOR = "#b91c1c"


def load_trades():
    """로그인한 사용자 본인의 투자내역만 불러옵니다."""
    response = (
        supabase.table("trades")
        .select("*")
        .eq("user_id", user.id)
        .order("id", desc=False)  # 오래된 순으로 받아와서 번호를 매긴 뒤, 화면에는 최신순으로 뒤집어 보여줍니다.
        .execute()
    )
    df = pd.DataFrame(response.data)
    if df.empty:
        return df

    # 날짜 글자(TEXT)를 화면에서 달력으로 고를 수 있는 날짜 형식으로 바꿔줍니다.
    df["buy_date"] = pd.to_datetime(df["buy_date"], errors="coerce").dt.date
    df["sell_date"] = pd.to_datetime(df["sell_date"], errors="coerce").dt.date
    # 화면에는 본인 데이터만 보이므로 user_id 칸은 굳이 보여줄 필요가 없어 뺍니다.
    df = df.drop(columns=["user_id"])

    # DB가 자동으로 매기는 id는 행을 지우면 번호에 구멍이 생깁니다(예: 1, 2, 4, 7...).
    # 화면 맨 앞 번호 칸은 "지금 저장된 내용이 몇 개인지"만 보여주도록,
    # id 대신 저장된 순서 그대로 1, 2, 3...으로 새로 번호를 매깁니다.
    df[DISPLAY_NO_COL] = range(1, len(df) + 1)
    df = df.drop(columns=["id"])

    # 매도가가 0보다 큰(=실제로 매도까지 끝난) 행만 손익을 계산합니다.
    # 손익 = (매도가 - 매수가) × 수량 - 수수료 - 세금
    def _row_profit(row):
        sell_price = row.get("sell_price") or 0
        if sell_price > 0:
            buy_price = row.get("buy_price") or 0
            quantity = row.get("quantity") or 0
            fee = row.get("fee") or 0
            tax = row.get("tax") or 0
            return (sell_price - buy_price) * quantity - fee - tax
        return None

    df[PROFIT_COL] = df.apply(_row_profit, axis=1)

    # 최근에 입력한 내용이 표 맨 위에 오도록 순서를 뒤집습니다(번호 자체는 그대로 유지됩니다).
    df = df.iloc[::-1].reset_index(drop=True)

    column_order = [
        DISPLAY_NO_COL,
        "stock_name",
        "stock_code",
        "buy_date",
        "buy_price",
        "quantity",
        "sell_date",
        "sell_price",
        "fee",
        "tax",
        PROFIT_COL,
        "memo",
        "result_tag",
    ]
    return df[column_order]


def insert_trade(row):
    row = dict(row)
    row["user_id"] = user.id  # 어떤 사용자의 기록인지 표시해서 저장합니다.
    supabase.table("trades").insert(row).execute()


def _clean(value, default=None):
    """표에서 빈칸으로 남은 값(NaN)을 안전한 기본값으로 바꿔주는 함수"""
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass
    return value


def replace_all_trades(df):
    """
    표에서 수정한 내용을 전부 반영합니다.
    로그인한 사용자 본인의 기존 데이터만 지우고, 표에 있는 내용으로 다시 채워 넣는 방식입니다
    (행을 수정하거나, 새 행을 추가하거나, 행을 삭제한 것 모두 이 방식으로 한 번에 반영됩니다).
    다른 사용자의 데이터는 건드리지 않습니다.
    "번호"·"손익" 칸은 화면에서만 보여주려고 계산한 값이라 저장 대상에서 제외합니다.
    """
    supabase.table("trades").delete().eq("user_id", user.id).execute()

    records = []
    for _, row in df.iterrows():
        stock_name = str(_clean(row.get("stock_name"), "")).strip()
        if not stock_name:
            continue  # 종목명이 빈 줄은 저장하지 않습니다.

        records.append(
            {
                "user_id": user.id,
                "stock_name": stock_name,
                "stock_code": str(_clean(row.get("stock_code"), "")),
                "buy_date": str(_clean(row.get("buy_date"))) if _clean(row.get("buy_date")) else None,
                "buy_price": float(_clean(row.get("buy_price"), 0)),
                "quantity": int(_clean(row.get("quantity"), 0)),
                "sell_date": str(_clean(row.get("sell_date"))) if _clean(row.get("sell_date")) else None,
                "sell_price": float(_clean(row.get("sell_price"), 0)),
                "fee": float(_clean(row.get("fee"), 0)),
                "tax": float(_clean(row.get("tax"), 0)),
                "memo": str(_clean(row.get("memo"), "")),
                "result_tag": str(_clean(row.get("result_tag"), "")),
            }
        )

    if records:
        supabase.table("trades").insert(records).execute()


with st.form("trade_form", clear_on_submit=True):
    col1, col2 = st.columns(2)

    with col1:
        stock_name = st.text_input("종목명")
        stock_code = st.text_input("종목코드 (선택)")
        buy_date = st.date_input("매수일", value=date.today())
        buy_price = st.number_input("매수가", min_value=0.0, step=100.0)
        quantity = st.number_input("수량", min_value=0, step=1)

    with col2:
        sell_date = st.date_input("매도일", value=date.today())
        sell_price = st.number_input("매도가", min_value=0.0, step=100.0)
        fee = st.number_input("수수료", min_value=0.0, step=10.0)
        tax = st.number_input("세금", min_value=0.0, step=10.0)
        result_tag = st.selectbox("결과 태그", ["성공", "실패", "보류"])

    memo = st.text_area("투자결과 분석 메모")
    submitted = st.form_submit_button("저장")

if submitted:
    if not stock_name.strip():
        st.error("종목명을 입력해주세요.")
    else:
        insert_trade(
            {
                "stock_name": stock_name.strip(),
                "stock_code": stock_code.strip(),
                "buy_date": str(buy_date),
                "buy_price": buy_price,
                "quantity": int(quantity),
                "sell_date": str(sell_date),
                "sell_price": sell_price,
                "fee": fee,
                "tax": tax,
                "memo": memo,
                "result_tag": result_tag,
            }
        )
        st.success(f"{stock_name} 매매 기록이 저장되었습니다.")

st.subheader("저장된 투자내역")
st.caption("표 안의 칸을 더블클릭하면 바로 수정할 수 있습니다. 행 왼쪽을 클릭해 선택한 뒤 휴지통 아이콘으로 삭제하거나, 표 맨 아래 빈 줄에 새로 입력해서 추가할 수도 있습니다.")
st.caption("'손익' 칸은 매도가를 0보다 크게 입력하면 자동으로 계산됩니다((매도가-매수가)×수량-수수료-세금). 값을 고치고 '변경사항 저장'을 눌러야 다시 계산됩니다.")

trades_df = load_trades()

if trades_df.empty:
    st.info("아직 저장된 투자내역이 없습니다.")
else:
    edited_df = st.data_editor(
        trades_df,
        width="stretch",
        hide_index=True,
        num_rows="dynamic",  # 행 추가/삭제 허용
        key="trades_editor",
        column_config={
            DISPLAY_NO_COL: st.column_config.NumberColumn(
                "번호",
                disabled=True,
                format="%d",
                help="지금 저장된 내용 순서대로 매겨지는 번호라 직접 수정할 수 없습니다.",
            ),
            "stock_name": st.column_config.TextColumn("종목명"),
            "stock_code": st.column_config.TextColumn("종목코드"),
            "buy_date": st.column_config.DateColumn("매수일"),
            "buy_price": st.column_config.NumberColumn("매수가", format="%,.0f"),
            "quantity": st.column_config.NumberColumn("수량", format="%,d"),
            "sell_date": st.column_config.DateColumn("매도일"),
            "sell_price": st.column_config.NumberColumn("매도가", format="%,.0f"),
            "fee": st.column_config.NumberColumn("수수료", format="%,.0f"),
            "tax": st.column_config.NumberColumn("세금", format="%,.0f"),
            PROFIT_COL: st.column_config.NumberColumn(
                "손익",
                disabled=True,
                format="%,.0f",
                help="매도가를 입력하면 자동으로 계산됩니다: (매도가-매수가)×수량-수수료-세금.",
            ),
            "memo": st.column_config.TextColumn("투자결과 분석 메모"),
            "result_tag": st.column_config.SelectboxColumn("결과 태그", options=["성공", "실패", "보류"]),
        },
    )

    if st.button("변경사항 저장", type="primary"):
        replace_all_trades(edited_df)
        st.success("수정 내용이 저장되었습니다.")
        st.rerun()

    # ------------------------------------------------------------------
    # 손익 분석: 매도까지 끝난 내역만 모아서 연도별·연도월별로 손익을 집계합니다.
    # ------------------------------------------------------------------
    st.divider()
    st.subheader("손익 분석")

    sell_df = trades_df[trades_df[PROFIT_COL].notna()].copy()

    if sell_df.empty:
        st.info("아직 매도까지 완료된 내역이 없어 손익 분석을 보여드릴 수 없습니다. 매도가를 입력하고 저장하면 여기에 집계됩니다.")
    else:
        st.caption("매도가가 0보다 큰(=매도까지 끝난) 내역만 집계합니다. 아직 보유 중인 종목은 제외됩니다.")

        total_profit = sell_df[PROFIT_COL].sum()
        total_color = PROFIT_COLOR if total_profit > 0 else (LOSS_COLOR if total_profit < 0 else "inherit")
        st.markdown(
            f"**총 손익 (전체 기간):** "
            f"<span style='color:{total_color}; font-size:1.4rem; font-weight:700'>{total_profit:,.0f}원</span>",
            unsafe_allow_html=True,
        )

        sell_df["연도"] = pd.to_datetime(sell_df["sell_date"]).dt.year
        sell_df["월"] = pd.to_datetime(sell_df["sell_date"]).dt.month

        def _style_profit_cell(value):
            if pd.isna(value):
                return ""
            if value > 0:
                return f"color: {PROFIT_COLOR}; font-weight: 700"
            if value < 0:
                return f"color: {LOSS_COLOR}; font-weight: 700"
            return ""

        def _apply_profit_style(styler, subset):
            # pandas 2.1부터는 applymap 대신 map을 쓰라고 권장하는데, 배포 서버의
            # pandas 버전이 정확히 몇인지 고정돼 있지 않아서 둘 다 지원하도록 처리합니다.
            if hasattr(styler, "map"):
                return styler.map(_style_profit_cell, subset=subset)
            return styler.applymap(_style_profit_cell, subset=subset)

        col_year, col_month = st.columns(2)

        with col_year:
            st.caption("연도별 손익")
            yearly = (
                sell_df.groupby("연도")[PROFIT_COL]
                .agg(손익합계="sum", 매매건수="count")
                .reset_index()
                .sort_values("연도")
            )
            styled_year = yearly.style.format({"손익합계": "{:,.0f}원"})
            styled_year = _apply_profit_style(styled_year, ["손익합계"])
            st.dataframe(styled_year, hide_index=True, width="stretch")

        with col_month:
            st.caption("연도·월별 손익")
            monthly = (
                sell_df.groupby(["연도", "월"])[PROFIT_COL]
                .agg(손익합계="sum", 매매건수="count")
                .reset_index()
                .sort_values(["연도", "월"])
            )
            styled_month = monthly.style.format({"손익합계": "{:,.0f}원"})
            styled_month = _apply_profit_style(styled_month, ["손익합계"])
            st.dataframe(styled_month, hide_index=True, width="stretch")
