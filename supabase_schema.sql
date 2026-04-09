-- ═══════════════════════════════════════════
-- SEPA Scanner - Supabase 테이블 스키마
-- ═══════════════════════════════════════════

-- 1. 사용자 프로필 (Supabase Auth 확장)
CREATE TABLE IF NOT EXISTS profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email TEXT,
    display_name TEXT,
    initial_capital_kr NUMERIC DEFAULT 0,
    initial_capital_us NUMERIC DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can view own profile" ON profiles FOR SELECT USING ((SELECT auth.uid()) = id);
CREATE POLICY "Users can update own profile" ON profiles FOR UPDATE USING ((SELECT auth.uid()) = id);
CREATE POLICY "Users can insert own profile" ON profiles FOR INSERT WITH CHECK ((SELECT auth.uid()) = id);

-- 2. 포지션 (매수/매도 내역 포함)
CREATE TABLE IF NOT EXISTS positions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    market TEXT NOT NULL DEFAULT 'KR',  -- 'KR' or 'US'
    ticker TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',  -- 'open' or 'closed'
    trades JSONB NOT NULL DEFAULT '[]',
    stop_loss_history JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_positions_user_id ON positions(user_id);
CREATE INDEX idx_positions_user_market ON positions(user_id, market);

ALTER TABLE positions ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can view own positions" ON positions FOR SELECT USING ((SELECT auth.uid()) = user_id);
CREATE POLICY "Users can insert own positions" ON positions FOR INSERT WITH CHECK ((SELECT auth.uid()) = user_id);
CREATE POLICY "Users can update own positions" ON positions FOR UPDATE USING ((SELECT auth.uid()) = user_id);
CREATE POLICY "Users can delete own positions" ON positions FOR DELETE USING ((SELECT auth.uid()) = user_id);

-- 3. 거래 로그
CREATE TABLE IF NOT EXISTS trade_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    market TEXT NOT NULL DEFAULT 'KR',
    position_id UUID REFERENCES positions(id) ON DELETE SET NULL,
    ticker TEXT NOT NULL,
    name TEXT NOT NULL,
    type TEXT NOT NULL,  -- 'buy' or 'sell'
    date TEXT NOT NULL,
    price NUMERIC NOT NULL,
    quantity INTEGER NOT NULL,
    stop_loss NUMERIC,
    take_profit NUMERIC,
    entry_reason TEXT,
    reason TEXT,
    memo TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_trade_log_user_id ON trade_log(user_id);

ALTER TABLE trade_log ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can view own trade_log" ON trade_log FOR SELECT USING ((SELECT auth.uid()) = user_id);
CREATE POLICY "Users can insert own trade_log" ON trade_log FOR INSERT WITH CHECK ((SELECT auth.uid()) = user_id);
CREATE POLICY "Users can update own trade_log" ON trade_log FOR UPDATE USING ((SELECT auth.uid()) = user_id);
CREATE POLICY "Users can delete own trade_log" ON trade_log FOR DELETE USING ((SELECT auth.uid()) = user_id);

-- 4. 자본 입출금
CREATE TABLE IF NOT EXISTS capital_flows (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    market TEXT NOT NULL DEFAULT 'KR',
    date TEXT NOT NULL,
    amount NUMERIC NOT NULL,
    memo TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_capital_flows_user_id ON capital_flows(user_id);

ALTER TABLE capital_flows ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can view own capital_flows" ON capital_flows FOR SELECT USING ((SELECT auth.uid()) = user_id);
CREATE POLICY "Users can insert own capital_flows" ON capital_flows FOR INSERT WITH CHECK ((SELECT auth.uid()) = user_id);
CREATE POLICY "Users can delete own capital_flows" ON capital_flows FOR DELETE USING ((SELECT auth.uid()) = user_id);

-- 5. 그룹 워치리스트 (산업/테마 그룹)
CREATE TABLE IF NOT EXISTS watchlist_groups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    market TEXT NOT NULL DEFAULT 'KR',
    group_name TEXT NOT NULL,
    tickers JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, market, group_name)
);

CREATE INDEX idx_watchlist_groups_user_id ON watchlist_groups(user_id);

ALTER TABLE watchlist_groups ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can view own watchlist_groups" ON watchlist_groups FOR SELECT USING ((SELECT auth.uid()) = user_id);
CREATE POLICY "Users can insert own watchlist_groups" ON watchlist_groups FOR INSERT WITH CHECK ((SELECT auth.uid()) = user_id);
CREATE POLICY "Users can update own watchlist_groups" ON watchlist_groups FOR UPDATE USING ((SELECT auth.uid()) = user_id);
CREATE POLICY "Users can delete own watchlist_groups" ON watchlist_groups FOR DELETE USING ((SELECT auth.uid()) = user_id);

-- 6. 관심종목 (개별 종목 메모)
CREATE TABLE IF NOT EXISTS watchlist_stocks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    ticker TEXT NOT NULL,
    name TEXT,
    market TEXT NOT NULL DEFAULT 'KR',
    status TEXT DEFAULT '대기',
    wait_reason TEXT,
    entry_condition TEXT,
    memo TEXT,
    tags JSONB DEFAULT '[]',
    added_date TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, ticker)
);

CREATE INDEX idx_watchlist_stocks_user_id ON watchlist_stocks(user_id);

ALTER TABLE watchlist_stocks ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can view own watchlist_stocks" ON watchlist_stocks FOR SELECT USING ((SELECT auth.uid()) = user_id);
CREATE POLICY "Users can insert own watchlist_stocks" ON watchlist_stocks FOR INSERT WITH CHECK ((SELECT auth.uid()) = user_id);
CREATE POLICY "Users can update own watchlist_stocks" ON watchlist_stocks FOR UPDATE USING ((SELECT auth.uid()) = user_id);
CREATE POLICY "Users can delete own watchlist_stocks" ON watchlist_stocks FOR DELETE USING ((SELECT auth.uid()) = user_id);

-- 7. RS 스캔 결과 캐시 (공통 — RLS 없음, 모든 사용자 공유)
CREATE TABLE IF NOT EXISTS scan_cache (
    id SERIAL PRIMARY KEY,
    cache_type TEXT NOT NULL,    -- 'ranking', 'vcp', 'stage2', 'vcp_pattern', 'short'
    market TEXT NOT NULL,
    period INTEGER NOT NULL DEFAULT 60,
    scan_date TEXT NOT NULL,
    data JSONB NOT NULL,
    saved_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(cache_type, market, period, scan_date)
);

-- scan_cache는 공통 데이터이므로 RLS 없이 모든 인증 사용자가 읽기 가능
ALTER TABLE scan_cache ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Authenticated users can read scan_cache" ON scan_cache FOR SELECT TO authenticated USING (true);

-- 8. 신규 사용자 가입 시 자동 프로필 생성 트리거
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO public.profiles (id, email, display_name)
    VALUES (NEW.id, NEW.email, COALESCE(NEW.raw_user_meta_data->>'display_name', split_part(NEW.email, '@', 1)));
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE OR REPLACE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();
