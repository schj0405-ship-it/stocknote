-- 스톡노트: 매도수량(sell_quantity) 칼럼 추가 마이그레이션
--
-- 지금까지는 "매입수량(quantity)"과 "매도수량"을 따로 구분하지 않고,
-- 매도가가 입력되면 산 만큼 전부 다 팔았다고 가정했습니다.
-- 이제부터는 일부만 팔았을 때도 정확히 기록할 수 있도록 "매도수량"을
-- 별도 칼럼으로 추가합니다.
--
-- 실행 방법: Supabase 대시보드 → 왼쪽 메뉴 "SQL Editor" → 아래 내용을
-- 붙여넣고 "Run" 버튼 클릭 (이전에 supabase_migration_user_auth.sql을
-- 실행하셨던 것과 같은 화면입니다).
--
-- ⚠️ 중요: 이 SQL을 먼저 실행한 뒤에 코드를 재배포해야 "변경사항 저장"이
-- 정상적으로 동작합니다. (코드에 방어 로직을 넣어뒀지만, 실제로 저장하려면
-- DB에 이 칼럼이 있어야 합니다.)

-- 1) sell_quantity 칼럼 추가 (기본값 0)
ALTER TABLE trades ADD COLUMN IF NOT EXISTS sell_quantity numeric NOT NULL DEFAULT 0;

-- 2) 기존에 이미 매도가가 입력된(매도 완료로 취급하던) 데이터는,
--    예전 방식대로 "산 만큼 전부 팔았다"고 가정하고 매도수량을
--    매입수량과 같게 한 번만 채워 넣습니다.
UPDATE trades
SET sell_quantity = quantity
WHERE sell_price > 0 AND sell_quantity = 0;
