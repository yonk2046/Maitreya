"""術語契約守門測試 — 一詞一義一來源。

三道:
  (a) 雙射     — TERMS 內 zh 不重複、field 不綁兩個 zh。
  (b) 禁用名掃描 — viewer/cockpit.py 原始碼含任一 DEPRECATED_LABELS 即 fail。
  (c) 鏡像一致   — view_params 標記為判斷鏡像者,值必須 is/== engine_params 正本。

紅綠證明:臨時在 TERMS 加重複 zh / 在 cockpit 塞禁用名 / 把鏡像改成複製數字,
本檔對應測試會轉紅(見任務回報)。
"""
from __future__ import annotations

import pathlib

import core.engine_params as ep
from viewer import terms, view_params

_COCKPIT = pathlib.Path(__file__).resolve().parents[1] / "viewer" / "cockpit.py"


# ── (a) 雙射 ──────────────────────────────────────────────────────────────
def test_terms_zh_unique():
    """每個語意值只有一個中文詞(zh 唯一)。"""
    zhs = [t.zh for t in terms.TERMS.values()]
    dupes = {z for z in zhs if zhs.count(z) > 1}
    assert not dupes, f"重複中文詞(同詞多義風險):{dupes}"


def test_terms_field_binds_one_zh():
    """每個落地來源(field)只綁一個中文詞(一義多名風險)。"""
    field_to_zh: dict[str, str] = {}
    for t in terms.TERMS.values():
        if t.field in field_to_zh and field_to_zh[t.field] != t.zh:
            raise AssertionError(
                f"field {t.field!r} 綁了兩個中文詞:"
                f"{field_to_zh[t.field]!r} 與 {t.zh!r}"
            )
        field_to_zh[t.field] = t.zh


def test_term_key_matches_dict_key():
    """Term.key 與 dict key 一致(避免取用錯位)。"""
    for k, t in terms.TERMS.items():
        assert t.key == k, f"{k!r} 的 Term.key={t.key!r} 不一致"


def test_label_defn_col_cover_all_keys():
    """label/defn/col 對每個 key 都可取值。"""
    for k in terms.TERMS:
        assert terms.label(k) == terms.TERMS[k].zh
        assert terms.defn(k)  # 非空定義
        assert terms.col(k).startswith(terms.TERMS[k].zh)


# ── (b) 禁用名掃描 ────────────────────────────────────────────────────────
def test_cockpit_source_has_no_deprecated_labels():
    """viewer/cockpit.py 原始碼(含註解/docstring)不得再出現任一淘汰名。"""
    src = _COCKPIT.read_text(encoding="utf-8")
    hits = sorted(d for d in terms.DEPRECATED_LABELS if d in src)
    assert not hits, f"cockpit.py 仍含禁用術語:{hits}"


def test_deprecated_not_collide_with_canonical():
    """淘汰名不得等於任何現行中文詞(否則掃描會誤傷正名)。"""
    canonical = {t.zh for t in terms.TERMS.values()}
    overlap = canonical & terms.DEPRECATED_LABELS
    assert not overlap, f"淘汰名與現行術語衝突:{overlap}"


# ── (c) 鏡像一致 ──────────────────────────────────────────────────────────
def test_judgment_mirrors_equal_engine_params():
    """view_params 判斷鏡像的值必須 is/== engine_params 正本(禁止複製數字)。"""
    for vp_name, ep_name in view_params.JUDGMENT_MIRRORS.items():
        vp_val = getattr(view_params, vp_name)
        ep_val = getattr(ep, ep_name)
        assert vp_val == ep_val, (
            f"鏡像漂移:view_params.{vp_name}={vp_val!r} != "
            f"engine_params.{ep_name}={ep_val!r}"
        )


def test_spon_gate_drift_bug_fixed():
    """漂移 bug 回歸鎖:回頭率 gate 鏡像 = 引擎正本 0.45,不得回退為 0.4。"""
    assert view_params.SPON_GATE == ep.GOLDEN_GOLD_SPON_MIN == 0.45
