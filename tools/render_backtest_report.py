"""tools/render_backtest_report.py — 模擬績效報表 (self-contained interactive HTML).

Reads every reports/backtest/*.json (strategy results + param scans) and renders
one browser-openable report with Chart.js: KPI cards, equity curve, return
distribution, exit-reason breakdown, per-trade table, and parameter-scan
comparison. Deterministic, no network at build time (Chart.js loads from CDN
when the page is opened).

Usage:
    python -m tools.render_backtest_report          # → reports/backtest/report.html
"""
from __future__ import annotations

import glob
import json
import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_AI_STOCK = _HERE.parent
OUT_DIR = _AI_STOCK / "reports" / "backtest"


def _load():
    by_strategy: dict[str, dict] = {}   # keep only the latest (by end-date) per strategy
    scans = []
    for f in sorted(glob.glob(str(OUT_DIR / "*.json"))):
        name = pathlib.Path(f).name
        if name == "report.json":
            continue
        try:
            d = json.loads(pathlib.Path(f).read_text(encoding="utf-8"))
        except Exception:
            continue
        if name.startswith("scan_"):
            scans.append(d)
        elif "trades" in d:
            key = d.get("strategy", name)
            end = (d.get("date_range") or ["", ""])[-1]
            prev = by_strategy.get(key)
            if prev is None or end >= (prev.get("date_range") or ["", ""])[-1]:
                by_strategy[key] = d
    return list(by_strategy.values()), scans


def _equity_curve(trades: list[dict]) -> list[float]:
    eq, out = 1.0, []
    for t in sorted(trades, key=lambda x: x.get("entry_date", "")):
        eq *= (1 + (t.get("return_pct") or 0))
        out.append(round(eq, 4))
    return out


def _histogram(trades: list[dict]) -> dict:
    buckets = ["<-5%", "-5~0%", "0~5%", "5~10%", "10~20%", ">20%"]
    counts = [0] * 6
    for t in trades:
        r = (t.get("return_pct") or 0) * 100
        i = (0 if r < -5 else 1 if r < 0 else 2 if r < 5 else 3 if r < 10 else 4 if r < 20 else 5)
        counts[i] += 1
    return {"labels": buckets, "counts": counts}


def build_html(strategies: list[dict], scans: list[dict]) -> str:
    payload = {
        "strategies": [
            {
                "name": s.get("strategy"),
                "date_range": s.get("date_range"),
                "summary": s.get("summary", {}),
                "limitations": s.get("limitations", []),
                "trades": s.get("trades", []),
                "equity": _equity_curve(s.get("trades", [])),
                "hist": _histogram(s.get("trades", [])),
            }
            for s in strategies
        ],
        "scans": scans,
    }
    data_json = json.dumps(payload, ensure_ascii=False)
    zh = {"momentum_continuation": "動能延續 (積極)", "chip_anchored_swing": "籌碼錨定波段 (保守)"}
    zh_json = json.dumps(zh, ensure_ascii=False)
    return _TEMPLATE.replace("/*DATA*/", data_json).replace("/*ZH*/", zh_json)


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-Hant"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Maitreya 模擬績效報表</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
 :root{--bg:#0d1117;--card:#13191f;--ink:#cdd5e0;--muted:#7a8694;--line:#1f2a37;
   --green:#52b788;--red:#e05c7a;--gold:#d4a84b;--blue:#7eb8d4;}
 *{box-sizing:border-box;margin:0;padding:0}
 body{background:var(--bg);color:var(--ink);font-family:-apple-system,"Noto Sans TC",sans-serif;padding:24px;max-width:1100px;margin:0 auto}
 h1{font-size:22px;color:var(--gold);font-weight:600;margin-bottom:2px}
 h2{font-size:18px;margin:28px 0 12px;font-weight:500;border-left:3px solid var(--gold);padding-left:10px}
 .sub{color:var(--muted);font-size:13px;margin-bottom:8px}
 .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px;margin:12px 0}
 .kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}
 .kpi .l{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
 .kpi .v{font-size:24px;font-weight:600;margin-top:4px}
 .grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin:12px 0}
 @media(max-width:720px){.grid2{grid-template-columns:1fr}}
 .panel{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}
 .panel h3{font-size:13px;color:var(--muted);font-weight:500;margin-bottom:8px}
 table{width:100%;border-collapse:collapse;font-size:12px;margin-top:8px}
 th,td{text-align:right;padding:6px 8px;border-bottom:1px solid var(--line)}
 th{color:var(--muted);font-weight:500}td:first-child,th:first-child{text-align:left}
 .pos{color:var(--green)}.neg{color:var(--red)}
 .note{color:var(--muted);font-size:11px;margin-top:8px;line-height:1.6}
 canvas{max-height:240px}
</style></head><body>
<h1>Maitreya 模擬績效報表</h1>
<div class="sub" id="hdr"></div>
<div id="root"></div>
<script>
const DATA=/*DATA*/; const ZH=/*ZH*/;
const fmtPct=x=>x==null?"—":(x*100).toFixed(1)+"%";
const cls=x=>x>0?"pos":(x<0?"neg":"");
function kpi(l,v,c){return `<div class="kpi"><div class="l">${l}</div><div class="v ${c||''}">${v}</div></div>`}
const root=document.getElementById('root');
const charts=[];
DATA.strategies.forEach((s,idx)=>{
  const su=s.summary||{};
  const zh=ZH[s.name]||s.name;
  const sec=document.createElement('div');
  sec.innerHTML=`<h2>${zh}</h2>
   <div class="sub">${(s.date_range||[]).join(' → ')} · ${s.name}</div>
   <div class="cards">
     ${kpi('交易數',su.trades??'—')}
     ${kpi('勝率',fmtPct(su.win_rate),su.win_rate>=0.5?'pos':'neg')}
     ${kpi('平均報酬',fmtPct(su.avg_return),cls(su.avg_return))}
     ${kpi('中位數',fmtPct(su.median_return),cls(su.median_return))}
     ${kpi('夏普(每筆·參考)',su.sharpe_per_trade==null?'—':su.sharpe_per_trade,su.sharpe_per_trade>1?'pos':'')}
     ${kpi('最大回撤',fmtPct(su.max_drawdown),'neg')}
     ${kpi('平均持有',(su.avg_holding_days??'—')+'d')}
   </div>
   <div class="grid2">
     <div class="panel"><h3>權益曲線 (累積)</h3><canvas id="eq${idx}"></canvas></div>
     <div class="panel"><h3>報酬分布</h3><canvas id="hi${idx}"></canvas></div>
   </div>
   <div class="grid2">
     <div class="panel"><h3>出場原因</h3><canvas id="ex${idx}"></canvas></div>
     <div class="panel"><h3>逐筆交易</h3><div style="max-height:240px;overflow:auto">${tradeTable(s.trades)}</div></div>
   </div>
   ${s.limitations&&s.limitations.length?`<div class="note">⚠ ${s.limitations.join('；')}</div>`:''}`;
  root.appendChild(sec);
  // equity
  new Chart(document.getElementById('eq'+idx),{type:'line',
    data:{labels:s.equity.map((_,i)=>i+1),datasets:[{data:s.equity,borderColor:'#52b788',backgroundColor:'#52b78822',fill:true,tension:.2,pointRadius:0}]},
    options:opt({y:{ticks:{callback:v=>v.toFixed(2)+'x'}}})});
  // histogram
  new Chart(document.getElementById('hi'+idx),{type:'bar',
    data:{labels:s.hist.labels,datasets:[{data:s.hist.counts,backgroundColor:s.hist.labels.map(l=>l.includes('-')?'#e05c7a':'#52b788')}]},
    options:opt()});
  // exit reasons
  const er=su.exit_reasons||{};
  new Chart(document.getElementById('ex'+idx),{type:'doughnut',
    data:{labels:Object.keys(er),datasets:[{data:Object.values(er),backgroundColor:['#7eb8d4','#d4a84b','#e05c7a','#52b788','#9e8ac8']}]},
    options:{plugins:{legend:{labels:{color:'#cdd5e0',font:{size:11}}}}}});
});
// scans
DATA.scans.forEach((sc,i)=>{
  const sec=document.createElement('div');
  sec.innerHTML=`<h2>參數掃描 · ${sc.param}</h2><div class="sub">${(ZH[sc.strategy]||sc.strategy)} · ${(sc.date_range||[]).join(' → ')}</div>
   <div class="panel"><canvas id="sc${i}"></canvas></div>
   <div class="note">調高 ${sc.param} 觀察勝率/平均報酬的變化,挑甜點。</div>`;
  root.appendChild(sec);
  new Chart(document.getElementById('sc'+i),{type:'bar',
    data:{labels:sc.rows.map(r=>String(r.value)),datasets:[
      {label:'勝率',data:sc.rows.map(r=>(r.win_rate||0)*100),backgroundColor:'#7eb8d4',yAxisID:'y'},
      {label:'平均報酬%',data:sc.rows.map(r=>(r.avg_return||0)*100),backgroundColor:'#d4a84b',yAxisID:'y'},
      {label:'交易數',data:sc.rows.map(r=>r.trades||0),backgroundColor:'#52b78866',type:'line',borderColor:'#52b788',yAxisID:'y1'},
    ]},
    options:{responsive:true,plugins:{legend:{labels:{color:'#cdd5e0',font:{size:11}}}},
      scales:{x:{ticks:{color:'#7a8694'},grid:{color:'#1f2a37'}},
        y:{position:'left',ticks:{color:'#7a8694'},grid:{color:'#1f2a37'}},
        y1:{position:'right',ticks:{color:'#7a8694'},grid:{display:false}}}}});
});
function tradeTable(tr){
  if(!tr||!tr.length)return '<div class="note">無交易</div>';
  let h='<table><tr><th>標的</th><th>進場</th><th>出場</th><th>報酬</th><th>原因</th><th>天</th></tr>';
  tr.slice().sort((a,b)=>(b.return_pct||0)-(a.return_pct||0)).forEach(t=>{
    h+=`<tr><td>${t.ticker} ${t.name||''}</td><td>${t.entry_date}</td><td>${t.exit_date}</td>
     <td class="${cls(t.return_pct)}">${fmtPct(t.return_pct)}</td><td>${t.exit_reason}</td><td>${t.holding_days}</td></tr>`});
  return h+'</table>';
}
function opt(extra){return {responsive:true,plugins:{legend:{display:false}},
  scales:Object.assign({x:{ticks:{color:'#7a8694'},grid:{color:'#1f2a37'}},
   y:{ticks:{color:'#7a8694'},grid:{color:'#1f2a37'}}},extra||{})}}
document.getElementById('hdr').textContent=`${DATA.strategies.length} 策略 · ${DATA.scans.length} 掃描 · 籌碼定義出場 · 次日開盤/收盤結算`;
</script></body></html>"""


def main() -> int:
    strategies, scans = _load()
    if not strategies and not scans:
        print("[report] no backtest JSON found in reports/backtest/", file=sys.stderr)
        return 1
    html = build_html(strategies, scans)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "report.html"
    out.write_text(html, encoding="utf-8")
    print(f"[report] wrote {out.relative_to(_AI_STOCK)} "
          f"({len(strategies)} strategies, {len(scans)} scans)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
