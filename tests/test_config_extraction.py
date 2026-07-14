"""Phase 1 第 1 線 — 判斷參數 config 化 (C11 remediation).

憲法 §7 / NOTES #33:引擎判斷門檻/權重若寫死在 code 內,改一個數字就
無痕改變歷史意見(C11 陽性)。本輪把 golden / state_machine / chip_score /
market_context(含 TIER_A)的判斷參數外置到 core/engine_params.py。

This suite locks two invariants:

  1. **Bit-identical / single source** — every engine constant now equals its
     core/engine_params.py source (值不變,只換來源). Fixed-fixture value
     checks guard against silent numeric drift on either side.

  2. **C11 demonstration** — a parameter truly *lives* in config, not a second
     hardcoded copy: mutate the config source → engine output changes; restore
     → output restores. Proven two ways (module-scalar reload + shared-dict).
"""
from __future__ import annotations

import importlib
import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
if str(_AI_STOCK) not in sys.path:
    sys.path.insert(0, str(_AI_STOCK))

from core import engine_params as ep          # noqa: E402
from core import golden, state_machine, chip_score  # noqa: E402
from core import market_context as mc          # noqa: E402
from core.market_context import regime_shift, weakening_profile  # noqa: E402


# ═══════════════════════════════════════════════════════════════════════════
# 1. Single source — engine constants equal their config source (值不變)
# ═══════════════════════════════════════════════════════════════════════════

def test_golden_constants_sourced_from_config():
    assert golden.GOLD_SPON_MIN      == ep.GOLDEN_GOLD_SPON_MIN
    assert golden.SCORE_STREAK_HIGH  == ep.GOLDEN_SCORE_STREAK_HIGH
    assert golden.SCORE_STREAK_MID   == ep.GOLDEN_SCORE_STREAK_MID
    assert golden.SCORE_SPON_HIGH    == ep.GOLDEN_SCORE_SPON_HIGH
    assert golden.SCORE_SPON_MID     == ep.GOLDEN_SCORE_SPON_MID
    assert golden.TIER_PRIME         == ep.GOLDEN_TIER_PRIME
    assert golden.TIER_STRONG        == ep.GOLDEN_TIER_STRONG
    assert golden.SECTOR_TOP_N_TIGHT == ep.GOLDEN_SECTOR_TOP_N_TIGHT


def test_state_machine_constants_sourced_from_config():
    assert state_machine.STREAK_ACCUMULATING   == ep.SM_STREAK_ACCUMULATING
    assert state_machine.STREAK_STRENGTHENING  == ep.SM_STREAK_STRENGTHENING
    assert state_machine.STREAK_CONFIRMED      == ep.SM_STREAK_CONFIRMED
    assert state_machine.SPON_STRENGTHENING    == ep.SM_SPON_STRENGTHENING
    assert state_machine.SPON_CONFIRMED        == ep.SM_SPON_CONFIRMED
    assert state_machine.SECTOR_TOP_N_CONFIRM  == ep.SM_SECTOR_TOP_N_CONFIRM
    assert state_machine.BREADTH_CONFIRMED     == ep.SM_BREADTH_CONFIRMED
    assert state_machine.ABSENT_EXITED         == ep.SM_ABSENT_EXITED
    assert state_machine.COLLAPSE_WINDOW       == ep.SM_COLLAPSE_WINDOW
    assert state_machine.DAYS_SINCE_FAIL_RISK  == ep.SM_DAYS_SINCE_FAIL_RISK
    assert state_machine.ACCEL_DISTRIBUTING    == ep.SM_ACCEL_DISTRIBUTING
    assert state_machine.DEBOUNCE_SNAPSHOTS    == ep.SM_DEBOUNCE_SNAPSHOTS
    assert state_machine.DIST_LOCKOUT_SNAPSHOTS == ep.SM_DIST_LOCKOUT_SNAPSHOTS
    assert state_machine.FLIPS_UNSTABLE_30D    == ep.SM_FLIPS_UNSTABLE_30D


def test_market_context_constants_sourced_from_config():
    assert mc._W2_FII_RATIO   == ep.MC_W2_FII_RATIO
    assert mc._W5_SELL_RATIO  == ep.MC_W5_SELL_RATIO
    assert mc._W5_CHURN_RATIO == ep.MC_W5_CHURN_RATIO
    assert mc._COST_DIVERGENCE_PCT_DEFAULT == ep.MC_COST_DIVERGENCE_PCT


def test_config_dicts_are_shared_not_copied():
    # Identity, not just equality — proves there is exactly ONE authoring
    # object, so a change cannot desync a hidden second copy.
    assert chip_score.CHIP_SCORE_CONFIG is ep.CHIP_SCORE_CONFIG
    assert chip_score.GRADE_PCT_MAP is ep.GRADE_PCT_MAP
    from core.watchlists import TIER_A as wl_tier_a
    assert wl_tier_a is ep.TIER_A


def test_tier_a_membership_unchanged():
    # TIER_A is a judgment parameter (golden +0.10 conviction). Lock the roster.
    assert set(ep.TIER_A) == {"2330", "2454", "2317", "2382", "2308",
                              "2881", "2882", "2891"}


# ═══════════════════════════════════════════════════════════════════════════
# 2. Fixed-fixture value checks (drift guard — 逐欄比對)
# ═══════════════════════════════════════════════════════════════════════════

def test_chip_score_known_values():
    cs = chip_score.compute(
        streak=5, sponsorship=0.0, fii_sync_count=3, main_force_buy=1000,
        market_volume=5000, main_force_cost=100.0, current_price=101.0,
    )
    # vol_ratio 0.20→8, streak 5→8, institutional 3→8, cost 1.01→6; conc N/A
    assert cs.total == 30
    assert cs.max_total == 32           # concentration excluded (unavailable)
    assert cs.grade == "強"             # 30/32 = 0.9375 ≥ 0.80


def test_golden_conviction_known_values():
    # Uncapped: streak_mid 0.15 + spon_mid 0.10 + velocity 0.10 = 0.35 → qualified
    score, bd = golden._score_conviction(
        "Y", streak=3, sponsorship=0.55, sm_state="strengthening",
        is_tier_a=False, velocity_3d=100.0, acceleration=None,
        sector="x", sector_rank_latest=["a", "b", "c"],
    )
    assert round(score, 4) == 0.35
    assert bd == {"streak_mid": 0.15, "spon_mid": 0.10, "velocity_positive": 0.10}
    assert golden._tier_from_score(score) == golden.TIER_QUALIFIED_KEY

    # Capped: every bonus fires → raw 1.15 clamped to CONVICTION_CAP (1.0)
    score2, _ = golden._score_conviction(
        "X", streak=5, sponsorship=0.72, sm_state="confirmed", is_tier_a=True,
        velocity_3d=100.0, acceleration=50.0, sector="semiconductor",
        sector_rank_latest=["semiconductor", "x", "y"],
    )
    assert score2 == 1.0
    assert golden._tier_from_score(score2) == golden.TIER_PRIME_KEY


def test_regime_known_values():
    def mk(date, mfbs, chg):
        return {"date": date, "stocks": [
            {"ticker": f"T{i}", "main_force_buy": v, "change_pct": chg,
             "fii_net_buy": 10, "volume": 1000} for i, v in enumerate(mfbs)]}
    snaps = [mk("2026-01-01", [1, 1, -1, 1], 4.0),
             mk("2026-01-02", [1, 1, 1, 1], 4.0)]
    r = regime_shift(snaps)
    assert r["regime_label_en"] == "Risk-On / Offensive"   # breadth 1.0, chg 4.0
    assert r["latest_breadth"] == 1.0
    assert r["transition_detected"] is True                # breadth jump 0.75→1.0


def test_weakening_known_values():
    def snap(d, mfb):
        return {"date": d, "stocks": [{"ticker": "AAA",
                "main_force_buy": mfb, "fii_net_buy": 5}]}
    snaps = [snap("2026-01-01", 500), snap("2026-01-02", 400), snap("2026-01-03", 300)]
    w = weakening_profile("AAA", snaps)
    # streak 3, velocity_3d -100 (<0), 300 < 400 → W1 only → yellow 失速
    assert w["severity"] == "yellow"
    assert [f["code"] for f in w["flags"]] == ["W1"]


# ═══════════════════════════════════════════════════════════════════════════
# 3. C11 demonstration — the parameter truly lives in config, not a 2nd copy
# ═══════════════════════════════════════════════════════════════════════════

def test_c11_golden_tier_cut_lives_in_config():
    """Mutate the STRONG cut in config, reload golden, watch a fixed input
    cross the tier boundary — then restore and confirm it returns.

    reload re-executes golden's module body, which reads TIER_STRONG from
    config. If golden held its own hardcoded 0.40, reload would ignore the
    config change and this test would fail — proving single source.
    """
    probe = 0.50   # STRONG under 0.40 cut, QUALIFIED under a 0.55 cut
    original = ep.GOLDEN_TIER_STRONG
    try:
        assert golden._tier_from_score(probe) == golden.TIER_STRONG_KEY

        ep.GOLDEN_TIER_STRONG = 0.55
        importlib.reload(golden)
        assert golden.TIER_STRONG == 0.55
        assert golden._tier_from_score(probe) == golden.TIER_QUALIFIED_KEY  # changed
    finally:
        ep.GOLDEN_TIER_STRONG = original
        importlib.reload(golden)

    assert golden.TIER_STRONG == original
    assert golden._tier_from_score(probe) == golden.TIER_STRONG_KEY          # restored


def test_c11_chip_score_config_drives_output():
    """The chip streak sub-score reads the *shared* config dict at runtime.
    Swap one score cell → compute() changes; restore → it returns.
    """
    kwargs = dict(streak=3, sponsorship=0.0, fii_sync_count=None,
                  main_force_buy=None, market_volume=None,
                  main_force_cost=None, current_price=None)
    base = chip_score.compute(**kwargs)
    assert base.total == 6            # streak 3 → scores[2] == 6

    cell = ep.CHIP_SCORE_CONFIG["streak"]["scores"]
    original = cell[2]
    try:
        cell[2] = 99
        assert chip_score.compute(**kwargs).total == 99   # config drives output
    finally:
        cell[2] = original

    assert chip_score.compute(**kwargs).total == 6         # restored


# ═══════════════════════════════════════════════════════════════════════════
# 4. P2-W2 — config_snapshot 雙來源 + config_hash 覆蓋 engine_params(§4/C11)
# ═══════════════════════════════════════════════════════════════════════════

def test_as_config_dict_is_deterministic_and_env_free():
    from core.hashing import canonical_sha256
    a = ep.as_config_dict()
    b = ep.as_config_dict()
    # 同 code 兩次呼叫 → 位元相同(確定性、零環境依賴)
    assert canonical_sha256(a) == canonical_sha256(b)
    # 收錄所有 public UPPERCASE 判斷參數
    for k in ("TIER_A", "CHIP_SCORE_CONFIG", "GRADE_PCT_MAP",
              "GOLDEN_TIER_PRIME", "SM_BREADTH_CONFIRMED", "MC_COST_DIVERGENCE_PCT"):
        assert k in a, f"as_config_dict missing {k}"
    # 頂層鍵已排序(確定性輸出)
    assert list(a.keys()) == sorted(a.keys())


def test_as_config_dict_is_deep_copied():
    # 回傳深拷貝 — 呼叫端變更不得回頭 desync 存活引擎正在用的共享 config
    d = ep.as_config_dict()
    d["CHIP_SCORE_CONFIG"]["streak"]["max"] = 99999
    assert ep.CHIP_SCORE_CONFIG["streak"]["max"] == 10


def _ingest_snapshot():
    import yaml
    from data.adapters.legacy import adapt_legacy
    from core.ingest import ingest
    cfg = yaml.safe_load((_AI_STOCK / "config" / "scd.example.yaml").read_text(encoding="utf-8"))
    return ingest(adapt_legacy(), cfg), cfg


def test_config_snapshot_is_two_source_without_strategies():
    snap, _cfg = _ingest_snapshot()
    cs = snap["config_snapshot"]
    assert set(cs.keys()) == {"yaml", "engine_params"}        # 雙來源
    assert "strategies" not in cs                              # 裁定 D-4
    assert cs["engine_params"]["GOLDEN_TIER_PRIME"] == ep.GOLDEN_TIER_PRIME


def test_config_hash_covers_engine_params():
    """改 engine_params 任一值 → config_hash 變;還原 → 復原(C11,涵蓋雙來源)。"""
    from core.ingest import ingest
    import yaml
    from data.adapters.legacy import adapt_legacy
    cfg = yaml.safe_load((_AI_STOCK / "config" / "scd.example.yaml").read_text(encoding="utf-8"))
    a = adapt_legacy()
    h0 = ingest(a, cfg)["config_hash"]
    original = ep.GOLDEN_TIER_PRIME
    try:
        ep.GOLDEN_TIER_PRIME = 0.999
        assert ingest(a, cfg)["config_hash"] != h0            # engine_params 進 hash
    finally:
        ep.GOLDEN_TIER_PRIME = original
    assert ingest(a, cfg)["config_hash"] == h0                # 還原復原


def test_config_hash_covers_yaml():
    from core.ingest import ingest
    import copy as _copy
    import yaml
    from data.adapters.legacy import adapt_legacy
    cfg = yaml.safe_load((_AI_STOCK / "config" / "scd.example.yaml").read_text(encoding="utf-8"))
    a = adapt_legacy()
    h0 = ingest(a, cfg)["config_hash"]
    cfg2 = _copy.deepcopy(cfg)
    cfg2["tiers"]["golden_min"] = 999
    assert ingest(a, cfg2)["config_hash"] != h0               # yaml 也進 hash


def test_i_columns_and_obs_landing_land():
    snap, _cfg = _ingest_snapshot()
    # 頂層 I 欄 + obs_landing
    assert snap["obs_landing"] is True
    assert isinstance(snap["fii_sell_raw"], list)
    assert isinstance(snap["main_force_sell_raw"], list)
    # per-ticker I 欄:trust_net_buy 與 dealer_net_buy 同值雙寫;prop_net_buy 存在
    for rec in snap["stocks"]:
        assert "trust_net_buy" in rec and "prop_net_buy" in rec
        assert rec["trust_net_buy"] == rec["dealer_net_buy"]   # 正名同值雙寫
    # W2:O 欄尚未落地(空掛點不寫欄)
    for rec in snap["stocks"]:
        assert not [k for k in rec if k.startswith("obs_")]


def test_obs_landing_false_still_skips_o_and_writes_flag():
    """W6 backfill 模式契約前置:obs_landing=False → 旗標 False、仍不含 obs_* 欄。"""
    import yaml
    from data.adapters.legacy import adapt_legacy
    from core.ingest import ingest
    cfg = yaml.safe_load((_AI_STOCK / "config" / "scd.example.yaml").read_text(encoding="utf-8"))
    snap = ingest(adapt_legacy(), cfg, obs_landing=False)
    assert snap["obs_landing"] is False
    for rec in snap["stocks"]:
        assert not [k for k in rec if k.startswith("obs_")]
