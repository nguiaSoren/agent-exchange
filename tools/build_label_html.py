"""Generate a self-contained calibration labeling tool from cases.json.

`python tools/build_label_html.py` → writes `label_calibration.html` with the cases
embedded (no server, no fetch). Open that file in a browser, click a verdict per case,
download `labels.json`. One source of truth (cases.json); the HTML is generated.
"""

from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CASES_PATH = os.path.join(HERE, "..", "data", "calibration", "cases.json")
OUT_PATH = os.path.join(HERE, "..", "label_calibration.html")

TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Verifier calibration — label the hard cases</title>
<style>
  :root{ --bg:#0f1216; --card:#171b21; --ink:#e8edf2; --muted:#9aa6b2; --line:#262d36;
         --green:#1f9d5a; --amber:#c8881a; --red:#c0392b; --gray:#4a5562; --accent:#5b8def; }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}
  .wrap{max-width:820px;margin:0 auto;padding:28px 20px 80px}
  h1{font-size:19px;margin:0 0 2px} .sub{color:var(--muted);font-size:13px;margin:0 0 18px}
  .bar{height:6px;background:var(--line);border-radius:6px;overflow:hidden;margin:14px 0 6px}
  .bar > i{display:block;height:100%;background:var(--accent);width:0;transition:width .2s}
  .meta{display:flex;justify-content:space-between;color:var(--muted);font-size:12px;margin-bottom:14px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px 18px 16px}
  .lab{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin:0 0 6px}
  .contract{white-space:pre-wrap;font:13px/1.6 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
            background:#0c0f13;border:1px solid var(--line);border-radius:8px;padding:12px 14px;max-height:300px;overflow:auto}
  .claim{margin-top:14px;font-size:16px;font-weight:600;background:#1d2530;border-left:3px solid var(--accent);
         border-radius:6px;padding:12px 14px}
  .q{margin:16px 0 10px;color:var(--muted);font-size:13px}
  .btns{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px}
  button.v{appearance:none;border:1px solid var(--line);border-radius:10px;padding:14px 10px;font-size:15px;font-weight:600;
           color:var(--ink);background:#1b2129;cursor:pointer;transition:transform .04s, box-shadow .15s}
  button.v:hover{box-shadow:0 0 0 2px var(--accent) inset}
  button.v:active{transform:translateY(1px)}
  .k{display:block;font-size:11px;color:var(--muted);font-weight:500;margin-top:3px}
  .v.confirmed{border-color:var(--green)} .v.partial{border-color:var(--amber)} .v.unsupported{border-color:var(--red)}
  .row2{display:flex;justify-content:space-between;align-items:center;margin-top:12px}
  .ghost{background:none;border:none;color:var(--muted);cursor:pointer;font-size:13px}
  .ghost:hover{color:var(--ink)}
  .peek{margin-top:10px;font-size:13px;color:var(--muted);background:#12161c;border:1px dashed var(--line);
        border-radius:8px;padding:10px 12px;display:none}
  .done{text-align:center;padding:30px 10px}
  .stats{display:inline-flex;gap:14px;margin:14px 0 20px;color:var(--muted);font-size:14px;flex-wrap:wrap;justify-content:center}
  .pill{background:var(--card);border:1px solid var(--line);border-radius:20px;padding:6px 12px}
  .dl{display:inline-block;background:var(--accent);color:#fff;border:none;border-radius:10px;padding:12px 18px;
      font-size:15px;font-weight:600;cursor:pointer;margin:6px}
  .dl.copy{background:#1b2129;border:1px solid var(--line);color:var(--ink)}
  a{color:var(--accent)}
  .hint{color:var(--muted);font-size:12px;margin-top:18px;text-align:center}
</style>
</head>
<body>
<div class="wrap">
  <h1>Verifier calibration — label the hard cases</h1>
  <p class="sub">For each case: does the <b>contract</b> support the <b>claim</b>? Judge <i>only</i> the contract text. Keys: <b>1</b> confirmed · <b>2</b> partial · <b>3</b> unsupported · <b>4</b> not&nbsp;sure · <b>←</b> back.</p>
  <div class="bar"><i id="prog"></i></div>
  <div class="meta"><span id="counter"></span><span id="saved">autosaved</span></div>

  <div id="cardArea"></div>

  <div id="doneArea" class="done" style="display:none">
    <h1>Done — thank you 🎉</h1>
    <div class="stats" id="stats"></div>
    <div>
      <button class="dl" onclick="downloadLabels()">⬇ Download labels.json</button>
      <button class="dl copy" onclick="copyLabels()">📋 Copy JSON</button>
    </div>
    <p class="hint">Send me <code>labels.json</code> (or paste it) and I'll run the calibration loop:<br>reliability curve + ECE + the pay/escalate threshold. You can re-open this page to revise.</p>
    <p><button class="ghost" onclick="restart()">↻ start over</button></p>
  </div>
</div>

<script>
const CASES = __CASES_JSON__;
const KEY = "agentexch_calib_v1";
let labels = JSON.parse(localStorage.getItem(KEY) || "{}");
let i = 0;

function firstUnlabeled(){ for(let k=0;k<CASES.length;k++){ if(!labels[CASES[k].id]) return k; } return CASES.length; }
function setSaved(){ localStorage.setItem(KEY, JSON.stringify(labels)); }

function render(){
  const counter=document.getElementById('counter'), prog=document.getElementById('prog');
  const done=Object.keys(labels).length;
  prog.style.width = (done/CASES.length*100)+'%';
  counter.textContent = `Case ${Math.min(i+1,CASES.length)} of ${CASES.length} · ${done} labeled`;
  if(i>=CASES.length){ showDone(); return; }
  const c=CASES[i];
  document.getElementById('cardArea').innerHTML = `
    <div class="card">
      <p class="lab">Contract (ground truth)</p>
      <div class="contract">${esc(c.contract)}</div>
      <p class="lab" style="margin-top:14px">Claim</p>
      <div class="claim">${esc(c.claim)}</div>
      <p class="q">Does the contract support this claim?</p>
      <div class="btns">
        <button class="v confirmed" onclick="pick('confirmed')">✅ Confirmed<span class="k">key 1</span></button>
        <button class="v partial" onclick="pick('partial')">🟡 Partially<span class="k">key 2</span></button>
        <button class="v unsupported" onclick="pick('unsupported')">❌ Unsupported<span class="k">key 3</span></button>
      </div>
      <div class="row2">
        <button class="ghost" onclick="back()">← back</button>
        <span>
          <button class="ghost" onclick="pick('uncertain')">🤔 not sure (4)</button>
          <button class="ghost" onclick="togglePeek()">peek intended ▾</button>
        </span>
      </div>
      <div class="peek" id="peek"><b>intended:</b> ${esc(c.gold||'?')} — <i>${esc(c.why_hard||'')}</i><br><span style="color:#6b7682">(your click is what counts; this is just for self-check)</span></div>
    </div>`;
}
function esc(s){ return (s||'').replace(/[&<>]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[m])); }
function pick(v){ labels[CASES[i].id]=v; setSaved(); i++; render(); flashSaved(); }
function back(){ if(i>0){ i--; render(); } }
function togglePeek(){ const p=document.getElementById('peek'); if(p) p.style.display = p.style.display==='block'?'none':'block'; }
function flashSaved(){ const s=document.getElementById('saved'); s.textContent='✓ saved'; setTimeout(()=>s.textContent='autosaved',600); }

function showDone(){
  document.getElementById('cardArea').style.display='none';
  document.getElementById('doneArea').style.display='block';
  const cnt={confirmed:0,partial:0,unsupported:0,uncertain:0};
  Object.values(labels).forEach(v=>cnt[v]=(cnt[v]||0)+1);
  document.getElementById('stats').innerHTML =
    `<span class="pill">✅ ${cnt.confirmed} confirmed</span><span class="pill">🟡 ${cnt.partial} partial</span>`+
    `<span class="pill">❌ ${cnt.unsupported} unsupported</span><span class="pill">🤔 ${cnt.uncertain} unsure</span>`;
}
function buildJSON(){
  return JSON.stringify({version:"calib_v1", created:new Date().toISOString(),
    labels: CASES.filter(c=>labels[c.id]).map(c=>({id:c.id, claim:c.claim, label:labels[c.id]}))}, null, 2);
}
function downloadLabels(){
  const blob=new Blob([buildJSON()],{type:"application/json"});
  const a=document.createElement('a'); a.href=URL.createObjectURL(blob); a.download="labels.json"; a.click();
}
async function copyLabels(){ try{ await navigator.clipboard.writeText(buildJSON()); alert("Copied labels JSON to clipboard."); }catch(e){ alert("Copy failed — use Download."); } }
function restart(){ if(confirm("Clear all your labels and start over?")){ labels={}; setSaved(); i=0;
  document.getElementById('doneArea').style.display='none'; document.getElementById('cardArea').style.display='block'; render(); } }

document.addEventListener('keydown', e=>{
  if(i>=CASES.length) return;
  if(e.key==='1') pick('confirmed'); else if(e.key==='2') pick('partial');
  else if(e.key==='3') pick('unsupported'); else if(e.key==='4') pick('uncertain');
  else if(e.key==='ArrowLeft'||e.key==='Backspace'){ e.preventDefault(); back(); }
});

i = firstUnlabeled();
render();
</script>
</body>
</html>
"""


def main() -> None:
    with open(CASES_PATH, encoding="utf-8") as f:
        data = json.load(f)
    cases = data["cases"]
    html = TEMPLATE.replace("__CASES_JSON__", json.dumps(cases, ensure_ascii=False))
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"wrote {OUT_PATH}  ({len(cases)} cases embedded)")


if __name__ == "__main__":
    main()
