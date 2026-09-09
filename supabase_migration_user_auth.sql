-- ============================================================
-- 스톡노트: 회원가입/로그인 도입에 따른 마이그레이션
-- Supabase 대시보드 > SQL Editor 에서 이 파일 내용을 전체 붙여넣고 실행하세요.
-- (한 번만 실행하면 됩니다.)
-- ============================================================

-- 1) trades 테이블에 "누구의 기록인지" 표시하는 user_id 컬럼을 추가합니다.
--    auth.users(id)를 참조하므로, 실제로 회원가입된 사용자의 id만 들어갈 수 있습니다.
alter table trades
  add column if not exists user_id uuid references auth.users(id);

-- 저장할 때 코드에서 user_id를 채워 넣지만, 혹시 빠뜨리는 경우를 대비해
-- 로그인한 사용자의 id가 자동으로 채워지도록 기본값을 정해둡니다.
alter table trades
  alter column user_id set default auth.uid();

-- 2) (선택) 로그인 기능이 없던 시절 "누구나 허용" 정책으로 쌓였던 예전 테스트 데이터 정리
--    앞으로 이 데이터는 user_id가 비어있어서 어차피 아무에게도 보이지 않습니다.
--    완전히 지우고 싶다면 아래 줄 맨 앞의 "--"를 지우고 실행하세요.
-- delete from trades where user_id is null;

-- 3) 기존에 있던 "누구나 허용" 정책을 이름에 상관없이 전부 삭제합니다.
--    (정책 이름을 정확히 몰라도 되도록, trades 테이블에 걸린 정책을 모두 찾아서 지웁니다.)
do $$
declare
  pol record;
begin
  for pol in select policyname from pg_policies where tablename = 'trades'
  loop
    execute format('drop policy if exists %I on trades', pol.policyname);
  end loop;
end $$;

-- 4) 행 단위 보안(RLS, Row Level Security = "행마다 누가 접근 가능한지 검사하는 보안 기능")을 켭니다.
--    (이미 켜져 있었다면 이 줄은 그냥 넘어갑니다.)
alter table trades enable row level security;

-- 5) "로그인한 본인 데이터만 보이고, 본인 데이터만 만들고 고치고 지울 수 있음" 정책을 새로 만듭니다.
--    auth.uid()는 "지금 로그인해서 요청을 보낸 사람의 id"를 뜻합니다.
create policy "본인 투자내역 조회"
  on trades for select
  using (auth.uid() = user_id);

create policy "본인 투자내역 추가"
  on trades for insert
  with check (auth.uid() = user_id);

create policy "본인 투자내역 수정"
  on trades for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

create policy "본인 투자내역 삭제"
  on trades for delete
  using (auth.uid() = user_id);

-- ============================================================
-- 실행 후 확인 방법:
-- Supabase 대시보드 > Table Editor > trades 표에 user_id 컬럼이 생겼는지 확인
-- Supabase 대시보드 > Authentication > Policies 에서 trades 테이블에
-- 위 4개 정책(조회/추가/수정/삭제)만 남아있는지 확인
-- ============================================================
