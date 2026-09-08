import requests
import zipfile
import io
import xml.etree.ElementTree as ET
import pandas as pd

# 1. 발급받은 OpenDART 인증키(40자리)를 여기 큰따옴표 안에 붙여넣으세요
API_KEY = "068ed29ef6fe1329f7ac5998c3b5b075081c72d5"

# 2. OpenDART에 "전체 회사 고유번호 목록"을 요청
url = "https://opendart.fss.or.kr/api/corpCode.xml"
params = {"crtfc_key": API_KEY}
response = requests.get(url, params=params)

# 3. 응답은 zip(압축 파일) 형태로 옵니다 -> 파일로 저장하지 않고 메모리에서 바로 압축 풀기
zip_file = zipfile.ZipFile(io.BytesIO(response.content))
xml_data = zip_file.read("CORPCODE.xml")

# 4. XML(태그<>로 구조화된 문서 형식)을 파싱(글자 뭉치를 프로그램이 읽을 수 있는 구조로 분석)해서 표로 만들기
root = ET.fromstring(xml_data)

companies = []
for company in root.findall("list"):
    companies.append({
        "corp_code": company.findtext("corp_code"),       # 회사 고유번호 (8자리)
        "corp_name": company.findtext("corp_name"),        # 회사 이름
        "stock_code": company.findtext("stock_code"),       # 주식 종목코드 (상장사만 있음)
        "modify_date": company.findtext("modify_date"),     # 정보 최종 수정일
    })

df = pd.DataFrame(companies)  # DataFrame = pandas가 다루는 엑셀 표 같은 자료구조

# 5. 상장사만 남기기 (주식 코드가 있는 회사 = 실제로 사고팔 수 있는 회사)
listed_df = df[df["stock_code"].str.strip() != ""]

# 6. CSV(엑셀에서도 열리는 표 형식 파일)로 저장
listed_df.to_csv("corp_codes.csv", index=False, encoding="utf-8-sig")

print(f"전체 회사 수: {len(df)}개")
print(f"상장사(주식 코드 있는 회사) 수: {len(listed_df)}개")
print("corp_codes.csv 파일로 저장 완료!")