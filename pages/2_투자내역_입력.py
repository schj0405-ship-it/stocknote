from datetime import date

import pandas as pd
import streamlit as st

from auth import get_supabase_client, require_login

st.set_page_config(page_title="스톡노트 - 투자내역", layout="centered")
st.title("투자내역 입력")

# 로그인 안 되어 있으면 여기서 화면 실행이 멈추고, 로그인/회원가입 화면만 보여줍니다.
user = require_login()

# 로그인한 사용자의 인증 정보가 실려있는 연결 객체입니다.
# (이 객체로 trades 테이블에 접근하면, Supabase가 자동으로 "이 사람이 맞는지" 확인합니다.)
supabase = get_supabase_client()


def load_trades():
    """로그인한 사용자 본인의 투자내역만 불러옵니다."""
    response = (
        supabase.table("trades")
        .select("*")
        .eq("user_id", user.id)
        .order("id", desc=True)
        .execute()
    )
    df = pd.DataFrame(response.data)
    if not df.empty:
        # 날짜 글자(TEXT)를 화면에서 달력으로 고를 수 있는 날짜 형식으로 바꿔줍니다.
        df["buy_date"] = pd.to_datetime(df["buy_date"], errors="coerce").dt.date
        df["sell_date"] = pd.to_datetime(df["sell_date"], errors="coerce").dt.date
        # 화면에는 본인 데이터만 보이므로 user_id 칸은 굳이 보여줄 필요가 없어 뺍니다.
        df = df.drop(columns=["user_id"])
    return df


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

    memo = st.text_area("매매 사유 메모")
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
            "id": st.column_config.NumberColumn("id", disabled=True, help="자동으로 매겨지는 번호라 수정할 수 없습니다."),
            "stock_name": st.column_config.TextColumn("종목명"),
            "stock_code": st.column_config.TextColumn("종목코드"),
            "buy_date": st.column_config.DateColumn("매수일"),
            "buy_price": st.column_config.NumberColumn("매수가"),
            "quantity": st.column_config.NumberColumn("수량"),
            "sell_date": st.column_config.DateColumn("매도일"),
            "sell_price": st.column_config.NumberColumn("매도가"),
            "fee": st.column_config.NumberColumn("수수료"),
            "tax": st.column_config.NumberColumn("세금"),
            "memo": st.column_config.TextColumn("매매 사유 메모"),
            "result_tag": st.column_config.SelectboxColumn("결과 태그", options=["성공", "실패", "보류"]),
        },
    )

    if st.button("변경사항 저장", type="primary"):
        replace_all_trades(edited_df)
        st.success("수정 내용이 저장되었습니다.")
        st.rerun()
