# Maitreya — Streamlit Community Cloud Deployment

## Prerequisites
- GitHub repo `Maitreya` set to **Private** ✓
- `data/` and `reports/` committed to repo (see Step 1)
- GitHub Actions daily workflow active (`.github/workflows/daily.yml`)

---

## Step 1 — Commit existing data to repo

Run these once from your Mac to seed the repo with your current archive:

```bash
cd "/Users/yoncky/SCD engine/Ai stock"

# Remove old gitignore rules that blocked data/reports
# (already updated — just verify)
cat .gitignore

# Add all existing snapshots and reports
git add data/snapshots/ data/branches/ reports/
git add .gitignore requirements.txt .streamlit/ .github/
git commit -m "feat: add data archive + cloud pipeline setup"
git push
```

---

## Step 2 — Deploy on Streamlit Community Cloud

1. Go to **[share.streamlit.io](https://share.streamlit.io)**
2. Sign in with your GitHub account (`yonk2046`)
3. Click **"New app"**
4. Fill in:
   - **Repository:** `yonk2046/Maitreya`
   - **Branch:** `main`
   - **Main file path:** `Ai stock/viewer/cockpit.py`
5. Click **Deploy**

Streamlit will install `requirements.txt` and launch the app.
First deploy takes ~3–5 minutes.

---

## Step 3 — Verify it works

Once deployed, open the URL Streamlit gives you.

Check:
- [ ] Page loads (dark theme)
- [ ] Snapshot dates appear in sidebar
- [ ] 市場體制 tab shows regime data
- [ ] ★ 黃金名單 tab loads without errors
- [ ] 📡 今日情報 tab shows latest intelligence report

---

## How it stays updated

```
Every weekday 19:00 Taiwan time:

GitHub Actions runs →
  fetch_daily.py (pulls TWSE / Fubon / Sinotrade / TDCC)
  make daily (ingest + archive + verify + intelligence)
  git commit data/ reports/
  git push → repo updated

Streamlit Community Cloud →
  reads from repo on next page load
  dashboard shows latest data automatically
```

No server. No VPS. No Docker. Your Mac can be off.

---

## Manual trigger

If you want to re-run the pipeline outside the schedule
(e.g. after a missed trading day):

GitHub → your repo → **Actions** tab → **Maitreya Daily Pipeline** → **Run workflow**

---

## Monitoring

GitHub → Actions tab shows every run with logs.
Green checkmark = all good.
Red X = something failed — click to see which step.

---

## Costs

| Service | Cost |
|---------|------|
| GitHub private repo | Free |
| GitHub Actions (2000 min/month free) | Free — uses ~10 min/day |
| Streamlit Community Cloud | Free |
| **Total** | **$0** |
