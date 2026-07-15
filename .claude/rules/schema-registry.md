---
paths: ["schema/**"]
---
# schema/ 操作鐵則（規範正本＝docs/ARCHITECTURE_BLUEPRINT.md §4 欄位生命週期）

- `field_registry.yaml` 是欄位契約正本，CI 對拍（`make verify-registry`＋tests/test_field_registry.py）；
  改欄位先改 registry，counts 與 meta.notes 要同步。
- **單一 bump 紀律**：1.9.0 之後不再 minor bump——每次 bump 使全歷史 full-replay 保證歸零，下一次即 2.0。
- deprecated-pending 欄（temporal_state、market_regime stub）持續照舊值寫入到 major 移除，不提前停寫。
- canonical_schema.json 加 enum 值（如 audit event）後必跑 `make test`——快照 schema 驗證會抓漏。
- 欄位命名必須宣告母體/語意（如 breadth.universe=twse_listed_stocks）；alias 只給真同義，概念後繼不是 alias。
