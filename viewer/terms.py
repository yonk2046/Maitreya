"""viewer/terms.py — Maitreya 術語契約(一詞一義一來源)

憲法 C12:呈現映射(顏色/中文/emoji/HTML)歸 viewer 單一擁有。本檔是 viewer
呈現層「中文詞 ↔ 語意 ↔ 落地來源」的**唯一術語法典**,把散落在 cockpit.py 各處
的顯示標籤集中為機器可查驗的契約:

  • 同一個語意值只有一個中文詞(zh 唯一,雙射)。
  • 同一個落地欄/來源只綁一個中文詞(field 唯一,雙射)。
  • 被淘汰的舊名(同詞多義/一義多名的歷史殘留)列入 DEPRECATED_LABELS,
    tests/test_terms_contract.py 掃 cockpit 原始碼,一出現即 fail。

本檔為純呈現常數 — 零環境依賴、零 I/O、不 import 任何 core 引擎(它只描述
「怎麼稱呼」,不做任何判斷/計算)。所有數值門檻歸 viewer/view_params.py。

法典正本(Yonki 裁定,不得自行增改語意):
  key            中文(唯一)   綁定來源
  streak_strict  連買          落地欄 main_force_strict_streak_days(缺席即斷)
  streak_on_board 榜上連買     render-time accumulation_velocity.streak(只計在榜日,缺席不中斷)
  presence_streak 連續在榜     persistence_ranker.current_streak(僅出席在買超榜)
  window_buy_days 20日內買超   落地欄 main_force_positive_days_in_window
  net_window     20日累計買超  落地欄 net_accumulation_in_window
  net_alltime    歷史累計      render-time net_cumulative(未裁窗)
  weak_net_window 轉弱窗累計   weakening.net_cumulative(轉弱側量測,與 net_window 不同值,見下註)
  sponsorship    主力回頭率    sponsorship_score(一律顯示為百分比)
  velocity_3d    3日速度       落地 velocity_3d(render==落地,同值)
  momentum_glyph 動能方向      _momentum_glyph 輸出
  weakening      轉弱等級      weakening.severity
  chip_grade     籌碼分        obs_chip_grade
  fii_sync       外資同向      fii_net_buy 對齊
  appearance     出現          persistence coverage,N=實際快照數(禁用「窗口」字樣)

註(weak_net_window):2026-07-22 最新快照實測,weakening.net_cumulative(轉弱引擎
的缺席前累計)與 net_accumulation_in_window(20 日窗口買超)在全部 29 檔皆**不同值**
(例:1301 = 94,020 vs 101,627)。兩者來源與語意不同,故各給獨立中文詞;轉弱面板
的累計欄讀 weakening.net_cumulative → 稱「轉弱窗累計」,不可與「20日累計買超」混名。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Term:
    key: str
    zh: str            # 唯一中文詞
    unit: str          # 單位(日/張/%/快照…;無單位為 "")
    field: str         # 唯一綁定來源(落地欄名或 render-time 取值路徑)
    source: str        # 來源類別:landed / render-time
    window: str        # 窗口語意註記(如 20日 / 缺席即斷 / 未裁窗 / None)
    definition_zh: str  # hover/tooltip 用的一句定義


TERMS: dict[str, Term] = {
    "streak_strict": Term(
        "streak_strict", "連買", "日",
        "main_force_strict_streak_days", "landed", "缺席即斷",
        "主力嚴格連續尾部淨買超天數;任何缺日或賣超皆中斷。",
    ),
    "streak_on_board": Term(
        "streak_on_board", "榜上連買", "日",
        "accumulation_velocity.streak", "render-time", "只計在榜日,缺席不中斷",
        "只計算出現在買超榜當日的連續買超,缺席不視為中斷(較寬語意)。",
    ),
    "presence_streak": Term(
        "presence_streak", "連續在榜", "日",
        "persistence_ranker.current_streak", "render-time", "僅出席在買超榜",
        "連續出現在買超榜的天數,與淨買超金額無關,只看是否上榜。",
    ),
    "window_buy_days": Term(
        "window_buy_days", "20日內買超", "日",
        "main_force_positive_days_in_window", "landed", "20日",
        "過去 20 個交易日內主力買超天數(忽略缺日,不要求連續)。",
    ),
    "net_window": Term(
        "net_window", "20日累計買超", "張",
        "net_accumulation_in_window", "landed", "20日",
        "過去 20 個交易日內主力買超累計張數。",
    ),
    "net_alltime": Term(
        "net_alltime", "歷史累計", "張",
        "net_cumulative", "render-time", "未裁窗",
        "全歷史主力買超累計(未裁 20 日窗),黃金引擎 G5 用的整體淨買。",
    ),
    "weak_net_window": Term(
        "weak_net_window", "轉弱窗累計", "張",
        "weakening.net_cumulative", "landed", "轉弱缺席前累計",
        "轉弱引擎量測的缺席前累計買超;與「20日累計買超」來源不同、數值不同,不可混名。",
    ),
    "sponsorship": Term(
        "sponsorship", "主力回頭率", "%",
        "sponsorship_score", "landed", None,
        "同一家分點回頭買的頻率(高＝同一主力鎖碼;低＝每天換人像散戶追價);"
        "分點樣本 <3 天不評分。一律以百分比顯示。",
    ),
    "velocity_3d": Term(
        "velocity_3d", "3日速度", "張/日",
        "velocity_3d", "landed", "近3日",
        "近 3 個實際觀測日主力買超的平均每日變化(張/日)。",
    ),
    "momentum_glyph": Term(
        "momentum_glyph", "動能方向", "",
        "_momentum_glyph", "render-time", None,
        "由 velocity_3d 與 acceleration 合成的方向標記(加速/增溫/持平/減速)。",
    ),
    "weakening": Term(
        "weakening", "轉弱等級", "",
        "weakening.severity", "landed", None,
        "轉弱/出貨嚴重度(red/orange/yellow/none)。",
    ),
    "chip_grade": Term(
        "chip_grade", "籌碼分", "",
        "obs_chip_grade", "landed", None,
        "籌碼強度評分(投量比＋連買＋集中度＋法人同向＋成本支撐);強/中/弱。",
    ),
    "fii_sync": Term(
        "fii_sync", "外資同向", "",
        "fii_net_buy", "landed", None,
        "外資淨買方向是否與主力同向(同向/反向/持平)。",
    ),
    "appearance": Term(
        "appearance", "出現", "快照",
        "persistence.coverage_pct", "render-time", "N=實際快照數",
        "在觀察窗內的買超榜出現 X / N 個快照(N＝實際快照數,非固定窗口)。",
    ),
    # ── 策略標示徽章(Part 1;來源＝reports/strategy_tags sidecar,不算/不裝)──
    "strat_chip": Term(
        "strat_chip", "籌碼錨定", "",
        "strategy_tags.A", "landed", "sidecar",
        "策略 A 籌碼錨定波段:進黃金名單且現價在主力成本容忍帶內(來源 would_enter)。",
    ),
    "strat_momentum": Term(
        "strat_momentum", "動能延續", "",
        "strategy_tags.B", "landed", "sidecar",
        "策略 B 動能延續:連買達門檻、3日速度與加速度皆正、外資同向(來源 would_enter)。",
    ),
    "strat_consensus": Term(
        "strat_consensus", "雙策略共識", "檔",
        "strategy_tags.consensus", "render-time", "sidecar",
        "同時符合策略 A 與 B 的標的數(兩套獨立進場邏輯共同指向)。",
    ),
}


def label(key: str) -> str:
    """術語的唯一中文詞(欄名/卡片標籤一律經此取得)。"""
    return TERMS[key].zh


def defn(key: str) -> str:
    """術語的一句定義(hover/tooltip 用)。"""
    return TERMS[key].definition_zh


def col(key: str) -> str:
    """表格欄名 = 中文詞(單位) — 如 連買(日)、3日速度(張/日)、主力回頭率(%)。"""
    t = TERMS[key]
    return f"{t.zh}({t.unit})" if t.unit else t.zh


# 淘汰名(cockpit 原始碼中不得再出現;test_terms_contract 掃描原始碼即 fail)。
# 同詞多義/一義多名的歷史殘留 — 一律改綁法典 key。
DEPRECATED_LABELS: frozenset[str] = frozenset({
    "贊助強度", "贊助持續", "贊助度", "贊助分",  # → 主力回頭率
    "20日回買",                                  # → 主力回頭率(刪回頭率×20 假日數)
    "淨累計",                                    # → 歷史累計
    "籌碼動能",                                  # → 籌碼分
    "窗口出現",                                  # → 出現(X/N 快照)
    "窗口買",                                    # → 20日內買超
    "窗口累計",                                  # → 20日累計買超 / 轉弱窗累計
    "連買天數 Strict",                           # → 連買
})
