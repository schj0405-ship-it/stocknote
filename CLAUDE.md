# 스톡노트 — Claude 작업 규칙

이 파일은 Claude가 이 폴더에서 일을 시작할 때마다 먼저 읽는 규칙이에요. 규칙을 바꾸고 싶으면 이 파일을 고치면 돼요.

## 1. 프로젝트 한눈에

- **서비스**: 종목의 재무데이터(매출액·영업이익·순이익)를 조회하고, 나의 매수·매도 기록을 저장·확인하는 개인 투자 노트
- **기술**: Python, Streamlit(화면), Supabase(데이터베이스·로그인), DART 전자공시 API, 네이버 금융(재무데이터 대체 경로)
- **GitHub**: `schj0405-ship-it/stocknote` (`main` 브랜치)
- **이 폴더(코드)**: `C:\Users\USER\Desktop\stocknote`
- **기획·참고 자료(코드 아님)**: `C:\Users\USER\Desktop\주식투자\주식 프로그램 개발` (기획안 docx 등). 읽기만 하고 고치지 않는다.
- **주요 파일**
  - `홈.py`: 첫 화면(실행 시작 파일). `app.py`는 같은 내용의 예전 시작 파일
  - `pages/`: 왼쪽 메뉴 화면 (`1_재무데이터_조회`, `2_투자내역_입력`, `3_연결_진단`)
  - `auth.py`: 로그인·회원가입, Supabase 연결
  - `get_financial_data.py`(DART), `naver_financials.py`·`html_table.py`(네이버), `stock_price.py`(주가), `quarterly_compare.py`(분기 비교), `company_search.py`·`corp_codes.csv`(종목 검색)
  - `supabase_migration_*.sql`: Supabase에서 실행한 SQL
  - `debug_*.py`, `test_per.py`: 확인용 임시 스크립트

## 2. 실행 방법

- 가상환경(파이썬 프로그램 묶음 폴더)은 **`venv/`**를 쓴다. (`.venv/`에는 streamlit이 설치돼 있지 않음)
- 실행 명령: `venv\Scripts\streamlit.exe run 홈.py --server.port 8501`
- Claude의 미리보기 설정: `.claude/launch.json`의 `stocknote` (주소 http://localhost:8501)
- 포트(접속 번호)는 **8501 고정**. 우주대선은 3000번을 쓰므로 동시에 켜도 겹치지 않는다.

## 3. 대화 규칙

- 안내와 답변은 **항상 한국어**. **결론 먼저**, 근거는 2~3가지로 간결하게.
- 사용자는 **코딩 완전 초보**. 전문용어는 괄호 안에 쉽게 설명하고, 비유 대신 **해야 할 순서를 번호로 명확하고 자세하게** 나열한다.
- 채팅으로 코드를 보여줄 때는 일부만 보여주지 말고, 고친 내용이 반영된 전체를 보여준다.
- 구현이 어렵거나 잘못된 방향이면 억지로 하지 말고 **솔직하게** 말한다.
- 결정이 필요한 것만 묻고, 물을 때는 선택지와 추천안을 함께 준다.
- Claude가 할 수 있는 건 최대한 직접 한다. 사용자가 꼭 해야 하는 일만 **"내가 할 일" 목록**으로 순서대로 준다.
  - 사용자가 하는 일: 계정 가입·로그인, 비밀값 입력, Supabase 대시보드 설정, Supabase SQL 실행
- 종목을 사라·팔라는 **투자 추천은 하지 않는다.** 데이터 조회·기록 기능만 만든다.

## 4. 코드 규칙

- 코드를 고친 뒤에는 실제로 띄워서 해당 화면이 오류 없이 열리는지 확인한다.
- 외부 사이트(DART, 네이버) 읽기가 실패해도 화면 전체가 멈추지 않게, 안내 문구를 보여주고 넘어간다.
- 새 기능 때문에 패키지가 늘면 `requirements.txt`에도 추가한다.

## 5. 데이터베이스(SQL) 규칙

- 이미 실행한 `supabase_migration_*.sql` 파일은 **고치지 않는다.** 바꿀 게 생기면 새 파일로 만든다.
- SQL 파일은 **여러 번 실행해도 안전하게** 만든다(if not exists, create or replace 등).
- SQL을 줄 때는 복사할 부분과 바꿀 곳을 정확히 표시한다.

## 6. 보안·운영 규칙

- `.streamlit/secrets.toml`(DART 키, Supabase 주소·키)과 `config.py`는 **채팅에 출력하지 않고, GitHub에 올리지 않는다.** 값이 필요하면 사용자가 직접 입력하도록 안내한다.
- **git 이메일 설정을 바꾸지 않는다.**
- commit·push는 사용자가 요청하거나 허락한 뒤에 한다.

## 7. 다른 프로젝트와 섞이지 않게 (중요)

- 이 폴더에서는 **스톡노트만** 작업한다. 다른 프로젝트 폴더의 파일은 읽지도 고치지도 않는다.
  - 우주대선: `C:\Users\USER\Desktop\ujudaeseon` (GitHub `schj0405-ship-it/ujudaeseon`)
  - 오늘도: `C:\Users\USER\Desktop\oneuldo` (GitHub `registr0716/oneuldo`)
- git 명령(commit, push, pull 등)은 **이 폴더 안에서만** 실행하고, 실행 전에 `git remote -v`가 `schj0405-ship-it/stocknote`인지 확인한다.
- Supabase 대시보드에서 프로젝트를 고를 때 반드시 **스톡노트 프로젝트**인지 확인한다. 우주대선의 Supabase·Vercel·도메인은 절대 건드리지 않는다.
- 다른 프로젝트 작업이 필요하면 그 폴더에서 새 세션을 열도록 안내한다.
