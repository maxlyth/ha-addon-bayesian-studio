# Post-Deploy Verification (Playwright MCP)

Run this checklist after each `deploy.sh` or add-on rebuild to catch UI regressions
that AppTest smoke tests cannot detect (CSS, layout, rendering, dark mode).

## Setup

1. Ensure the add-on is running (check HA → Settings → Add-ons → Bayesian Studio)
2. Open the add-on ingress URL in a browser
3. If using Playwright MCP in Claude Code: navigate to the ingress URL

---

## Checks

### 1. Top bar
- [ ] "Bayesian Studio" text visible at the top of the page
- [ ] Top bar spans both the sidebar and the main pane (full width)
- [ ] Top bar does not overlap page content

### 2. Sidebar
- [ ] Radio list of sensor names is visible (not empty, not blank)
- [ ] Auto / Light / Dark theme toggle is visible in the sidebar
- [ ] "📊 Overview" button is present above the sensor list

### 3. Overview page (click "📊 Overview")
- [ ] Table of sensor rows renders (health badge, entity name, obs count, coverage, issues, fire freq, prior, threshold, source)
- [ ] "Tune →" button present on each row
- [ ] No error banners (no red `st.error` blocks)

### 4. Studio page (click a sensor in the sidebar)
- [ ] Sensor selectbox shows the selected sensor
- [ ] Time period radio present: 1 hour / 1 day / 1 week / 1 month / Custom
- [ ] Prior slider present (0.01 – 0.99)
- [ ] Threshold slider present (0.01 – 0.99)
- [ ] Probability chart renders (not stuck on "⏳ Computing probability trace…")
- [ ] Observations section shows summary captions (one line per observation)
- [ ] "Details" expander present (collapsed by default)
- [ ] "Reset to original" button present (disabled when config is unchanged)

### 5. Details expander (open the "Details" expander)
- [ ] All observations are listed flat (no nested expanders)
- [ ] Each observation shows: label, chart placeholder / chart, condition inputs, prob sliders
- [ ] `prob_given_true` and `prob_given_false` sliders present for every observation
- [ ] Dividers between observations

### 6. Dark mode
- [ ] Toggle theme to "Dark" → page background becomes dark, text becomes light
- [ ] Probability chart background matches the page (transparent / dark)
- [ ] Toggle back to "Auto" → reverts to system theme

### 7. Custom time period
- [ ] Select "Custom" in the time period radio
- [ ] "From" and "To" date pickers appear
- [ ] Selecting a valid date range re-renders the probability chart

### 8. Screenshot baseline
- [ ] Take a screenshot of the Studio page (Overview + sidebar visible)
- [ ] Compare to the previous baseline; note any layout regressions

---

## Sprint-end release process

```bash
# 1. Run all tests locally
pytest tests/ -q

# 2. Deploy and verify manually
./deploy.sh
# Follow checklist above

# 3. Update version in config.yaml AND pyproject.toml
# 4. Update CHANGELOG.md with new version section
# 5. Commit, tag, and push
git commit -m "Release vX.Y.Z"
git tag vX.Y.Z
git push origin main --tags
# GitHub Actions runs tests + creates GitHub release automatically
```
