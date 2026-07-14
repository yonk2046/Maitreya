"""core/history_view.py — Epoch-aware historical snapshot read layer

補充裁定 A（FORWARD-RISK-REGISTER R4）：W3 前置構件。

引擎在 1.9.0 pipeline 內讀 20 日歷史窗，窗內會同時出現三種 epoch 的快照：

  • pre-obs  (schema_version < 1.9.0)          —— 1.8.x，**無任何 obs_* 欄**
  • backfill (1.9.0, obs_landing == False)     —— 有 I 欄、無 O 欄（W6 回填模式）
  • landed   (1.9.0, obs_landing == True)      —— 全欄（正常 pipeline 落地）

R4 判定：引擎裸讀舊快照的 KeyError／None 未防護是 W3/W4 最大宗 bug 源。本層是
**唯一的歷史讀取介面**：引擎（尤其 as-was 路徑依賴的 days_in_state 累計）一律透過
它讀歷史 O 欄，絕不裸讀 dict。對缺 obs 的舊快照回傳明確的 `ABSENT` sentinel，
呼叫端據此區分「landed 但值為 None」與「該 epoch 根本沒有這個欄」。

明確不做（憲法「絕不做」同位階，FORWARD-RISK-REGISTER）：不建通用 ORM／schema
抽象層——一個 history view 函數層就是全部。
"""
from __future__ import annotations

from typing import Any


# ── ABSENT sentinel ───────────────────────────────────────────────────────────
class _Absent:
    """Distinct from None: 'this epoch has no such observation field at all'
    (vs. a landed field whose value is legitimately null)."""
    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return "ABSENT"

    def __bool__(self) -> bool:
        return False


ABSENT = _Absent()


# ── Epoch classification ──────────────────────────────────────────────────────
EPOCH_PRE_OBS = "pre-obs"     # 1.8.x — no obs_* fields
EPOCH_BACKFILL = "backfill"   # 1.9.0, obs_landing=False — I only, no O
EPOCH_LANDED = "landed"       # 1.9.0, obs_landing=True — full obs

_OBS_LANDING_MIN = (1, 9, 0)


def _version_tuple(v: str) -> tuple[int, ...]:
    parts: list[int] = []
    for p in str(v).split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def snapshot_epoch(snap: dict[str, Any]) -> str:
    """Classify a snapshot into one of the three obs epochs."""
    if _version_tuple(snap.get("schema_version", "0.0.0")) < _OBS_LANDING_MIN:
        return EPOCH_PRE_OBS
    # 1.9.0+ : obs_landing flag decides whether O was actually landed.
    if not bool(snap.get("obs_landing", False)):
        return EPOCH_BACKFILL
    return EPOCH_LANDED


def has_landed_obs(snap: dict[str, Any]) -> bool:
    """True only for a normal 1.9.0 snapshot whose O engines actually ran."""
    return snapshot_epoch(snap) == EPOCH_LANDED


# ── Per-ticker record access ──────────────────────────────────────────────────
def record_for(snap: dict[str, Any], ticker: str) -> dict[str, Any] | None:
    """The StockRecord for `ticker` in `snap`, or None if the ticker is absent
    from that snapshot's universe."""
    for rec in snap.get("stocks", []) or []:
        if rec.get("ticker") == ticker:
            return rec
    return None


def obs_field(snap: dict[str, Any], ticker: str, field: str) -> Any:
    """Read a per-ticker landed O field, epoch-aware.

    Returns:
      • ABSENT   — snapshot is pre-obs/backfill epoch, ticker absent, or the
                   field is not present on the landed record.
      • value    — the landed value (may itself be None for a landed null).
    """
    if not has_landed_obs(snap):
        return ABSENT
    rec = record_for(snap, ticker)
    if rec is None or field not in rec:
        return ABSENT
    return rec[field]


def obs_sm_state(snap: dict[str, Any], ticker: str) -> Any:
    """Landed obs_sm_state for a ticker, or ABSENT if not a landed epoch."""
    return obs_field(snap, ticker, "obs_sm_state")


# ── As-was days-in-state (C10 bootstrap discipline) ───────────────────────────
def days_in_state_from_landed(
    history_snaps: list[dict[str, Any]],
    ticker: str,
    current_state: str,
    current_date: str,
) -> tuple[int, str]:
    """Count `days_in_state` / `state_entered` from the **landed** as-was
    obs_sm_state series only (#30「已落地者必改讀」+ C10 bootstrap).

    `history_snaps` is the prior window (oldest→newest), NOT including today.
    Walking backwards, only *landed* prior snapshots whose obs_sm_state equals
    `current_state` extend the streak; a pre-obs/backfill snapshot (ABSENT) or a
    different state stops it.

    C10 bootstrap: on the first 1.9.0 production day every prior snapshot is
    pre-obs/backfill → ABSENT → streak 0 → days_in_state = 1, state_entered =
    today. We never回算 raw history to fabricate an earlier entry date (#48
    look-ahead). As landed snapshots accumulate, counting becomes real.

    Returns (days_in_state, state_entered).
    """
    count = 0
    entered = current_date
    for snap in reversed(history_snaps):
        st = obs_sm_state(snap, ticker)
        if st is ABSENT or st != current_state:
            break
        count += 1
        entered = snap.get("date", entered) or entered
    return count + 1, entered
