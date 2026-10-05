#!/usr/bin/env python3
"""
Generates themed GitHub stats cards (royal blue / red / green / yellow / violet)
as self-hosted SVG files. No third-party services, no dependencies.

  GITHUB_TOKEN=... LOGIN=divyansh1502 python scripts/gh_stats.py   -> real data
  python scripts/gh_stats.py                                        -> placeholders
  python scripts/gh_stats.py --demo                                 -> fake data (preview only)

Outputs (into ./assets):
  gh-stats-mobile.svg   (420px wide, all cards stacked)
  gh-stats-wide.svg     (840px wide, streak on top, stats + languages side by side)
"""
import os, sys, json, math, datetime, urllib.request
from html import escape

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets")
FONT = "'Segoe UI',Helvetica,Arial,sans-serif"
MONO = "'SFMono-Regular',Consolas,'Liberation Mono',Menlo,monospace"
COL = {
    "blue":   dict(face="#4169E1", base="#1B3590", ink="#ffffff", acc="#4169E1"),
    "green":  dict(face="#2F8D46", base="#1E6B32", ink="#ffffff", acc="#2F8D46"),
    "red":    dict(face="#E5383B", base="#9E1B1E", ink="#ffffff", acc="#E5383B"),
    "yellow": dict(face="#FFC83D", base="#B8860B", ink="#2A2000", acc="#C98F00"),
    "violet": dict(face="#7C3AED", base="#4C1D95", ink="#ffffff", acc="#7C3AED"),
}
CYCLE = ["blue", "red", "green", "yellow", "violet", "blue"]

# ------------------------------------------------------------------ data
def gql(token, query, variables):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json", "User-Agent": "gh-stats"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.load(r)
    if "errors" in d:
        raise RuntimeError(d["errors"])
    return d["data"]

Q_USER = """query($login:String!){user(login:$login){createdAt followers{totalCount}
pullRequests{totalCount} issues{totalCount}
repositories(ownerAffiliations:OWNER,isFork:false,privacy:PUBLIC,first:100){totalCount
nodes{stargazerCount languages(first:8,orderBy:{field:SIZE,direction:DESC}){edges{size node{name}}}}}
contributionsCollection{contributionYears}}}"""
Q_YEAR = """query($login:String!,$from:DateTime!,$to:DateTime!){user(login:$login){
contributionsCollection(from:$from,to:$to){totalCommitContributions
contributionCalendar{totalContributions weeks{contributionDays{date contributionCount}}}}}}"""

def fmt_day(d):
    return d.strftime("%b ") + str(d.day)

def compute_streaks(days, today):
    """days: {'YYYY-MM-DD': count}. Returns (current, longest) as (length, start, end)."""
    streaks, run, start, prev = [], 0, None, None
    for ds in sorted(days):
        d = datetime.date.fromisoformat(ds)
        if d > today:
            continue
        if days[ds] > 0:
            if prev is not None and (d - prev).days == 1:
                run += 1
            else:
                run, start = 1, d
            prev = d
            streaks.append((run, start, d))
        else:
            run, prev = 0, None
    best = max(streaks, key=lambda t: t[0]) if streaks else (0, None, None)
    cur = (0, None, None)
    if streaks and (today - streaks[-1][2]).days <= 1:
        cur = streaks[-1]
    return cur, best

def fetch(token, login):
    u = gql(token, Q_USER, {"login": login})["user"]
    days, commits = {}, 0
    for y in u["contributionsCollection"]["contributionYears"]:
        try:
            c = gql(token, Q_YEAR, {"login": login, "from": "%d-01-01T00:00:00Z" % y, "to": "%d-12-31T23:59:59Z" % y})["user"]["contributionsCollection"]
        except Exception as e:
            print("skipping year", y, "->", e)
            continue
        commits += c["totalCommitContributions"]
        for w in c["contributionCalendar"]["weeks"]:
            for d in w["contributionDays"]:
                days[d["date"]] = d["contributionCount"]
    cur, best = compute_streaks(days, datetime.date.today())
    print("years fetched:", len(u["contributionsCollection"]["contributionYears"]), "| days:", len(days),
          "| total contributions:", sum(days.values()), "| current streak:", cur[0], "| longest:", best[0])
    langs = {}
    stars = 0
    for r in u["repositories"]["nodes"]:
        stars += r["stargazerCount"]
        for e in r["languages"]["edges"]:
            langs[e["node"]["name"]] = langs.get(e["node"]["name"], 0) + e["size"]
    tot = sum(langs.values()) or 1
    top = sorted(langs.items(), key=lambda kv: -kv[1])[:6]
    return dict(
        contrib_total=sum(days.values()), since=u["createdAt"][:4], commits=commits,
        prs=u["pullRequests"]["totalCount"], issues=u["issues"]["totalCount"], stars=stars,
        repos=u["repositories"]["totalCount"], followers=u["followers"]["totalCount"],
        cur_streak=cur[0], cur_range=(fmt_day(cur[1]) + " - " + fmt_day(cur[2])) if cur[1] else "No active streak",
        long_streak=best[0], long_range=(fmt_day(best[1]) + " - " + fmt_day(best[2])) if best[1] else "-",
        langs=[(k, round(v * 100.0 / tot, 1)) for k, v in top],
        updated=today.isoformat(),
    )

DEMO = dict(contrib_total=1234, since="2024", commits=812, prs=14, issues=6, stars=21, repos=18, followers=32,
            cur_streak=12, cur_range="Sep 24 - Oct 5", long_streak=41, long_range="Jun 2 - Jul 12",
            langs=[("Java", 46.2), ("JavaScript", 21.5), ("HTML", 13.8), ("CSS", 9.6), ("TypeScript", 5.9), ("Python", 3.0)],
            updated="demo")

# ------------------------------------------------------------------ drawing
PATTERNS = ('<pattern id="dots" width="6" height="6" patternUnits="userSpaceOnUse"><circle cx="1.5" cy="1.5" r=".8" fill="#fff" fill-opacity=".22"/></pattern>'
            '<pattern id="strp" width="9" height="9" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="3" height="9" fill="#fff" fill-opacity=".08"/></pattern>')
CSS = """
.sh{transform-box:fill-box;transform-origin:center;animation:sh 3.4s ease-in-out infinite}
@keyframes sh{0%{transform:translateX(0) skewX(-20deg)}55%,100%{transform:translateX(var(--t)) skewX(-20deg)}}
.pop{transform-box:fill-box;transform-origin:center;animation:pop .6s cubic-bezier(.2,.9,.3,1.3) both}
@keyframes pop{from{opacity:0;transform:scale(.8) translateY(8px)}to{opacity:1;transform:scale(1) translateY(0)}}
.rg{animation:rg 1.8s cubic-bezier(.22,.8,.3,1) .3s both}
@keyframes rg{from{stroke-dashoffset:var(--c)}to{stroke-dashoffset:var(--o)}}
.bar{transform-box:fill-box;transform-origin:left center;animation:grow 1.4s cubic-bezier(.22,.8,.3,1) both}
@keyframes grow{from{transform:scaleX(0)}to{transform:scaleX(1)}}
.fl{transform-box:fill-box;transform-origin:center bottom;animation:fl 1.6s ease-in-out infinite}
@keyframes fl{0%,100%{transform:scale(1)}50%{transform:scale(1.12) translateY(-1px)}}
.fade{animation:fade .8s ease-out both}
@keyframes fade{from{opacity:0}to{opacity:1}}
@media (prefers-color-scheme:dark){.bg{fill:#0F1530}.tx{fill:#E6EDF3}.mu{fill:#9DB4FF}.tr{fill:#243055}.dv{stroke:#243055}}
@media (prefers-reduced-motion:reduce){.sh,.pop,.rg,.bar,.fl,.fade{animation:none}}
"""
ICON = {
    "commit": '<circle cx="12" cy="12" r="4"/><path d="M2 12h6M16 12h6"/>',
    "pr": '<circle cx="6" cy="6" r="2.5"/><circle cx="6" cy="18" r="2.5"/><circle cx="18" cy="18" r="2.5"/><path d="M6 8.5v7M18 15.5V10a4 4 0 0 0-4-4h-3"/>',
    "issue": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="1.5" fill="currentColor"/>',
    "star": '<path d="M12 3l2.7 5.6 6.1.8-4.5 4.2 1.1 6.1L12 16.8 6.6 19.7l1.1-6.1L3.2 9.4l6.1-.8z"/>',
    "repo": '<path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2zM4 19V5"/>',
    "users": '<circle cx="9" cy="8" r="3.5"/><path d="M2 21a7 7 0 0 1 14 0"/><circle cx="17" cy="9" r="2.5"/><path d="M17 14a5 5 0 0 1 5 5"/>',
    "flame": '<path d="M12 3C13 7 18 9 18 14a6 6 0 0 1-12 0C6 11 8 10 9 8c1 2 2 2 3-5z"/>',
}
_id = [0]
def uid(p):
    _id[0] += 1
    return "%s%d" % (p, _id[0])

def n(v):
    return "—" if v is None else "{:,}".format(v)

def card_open(x, y, w, h, title, tag, col):
    c = COL[col]; cid = uid("c")
    s = '<g transform="translate(%d %d)">' % (x, y)
    s += '<clipPath id="%s"><rect x="0" y="0" width="%d" height="%d" rx="16"/></clipPath>' % (cid, w, h)
    s += '<rect x="0" y="4" width="%d" height="%d" rx="16" fill="%s"/>' % (w, h, c["base"])
    s += '<g clip-path="url(#%s)">' % cid
    s += '<rect class="bg" width="%d" height="%d" fill="#F6F8FF"/>' % (w, h)
    s += '<rect width="%d" height="40" fill="%s"/><rect width="%d" height="40" fill="url(#strp)"/><rect width="%d" height="40" fill="url(#dots)"/>' % (w, c["face"], w, w)
    s += '<rect class="sh" x="-30" y="-4" width="24" height="48" fill="#fff" fill-opacity=".26" style="--t:%dpx"/>' % (w + 80)
    s += '<text x="20" y="26" font-family="%s" font-size="15" font-weight="800" fill="%s">%s</text>' % (FONT, c["ink"], escape(title))
    s += '<text x="%d" y="25" text-anchor="end" font-family="%s" font-size="11" font-weight="700" fill="%s" fill-opacity=".75">%s</text>' % (w - 18, MONO, c["ink"], escape(tag))
    return s

def card_close(w, h, col):
    c = COL[col]
    return '</g><rect width="%d" height="%d" rx="16" fill="none" stroke="%s" stroke-width="1.6"/></g>' % (w, h, c["face"] if col != "yellow" else "#E0A800")

def streak_card(x, y, w, d):
    h = 176
    s = card_open(x, y, w, h, "Contribution Streak", "// since %s" % (d["since"] if d else "—"), "red")
    cw = w / 3.0; top = 40
    cols = [
        (n(d["contrib_total"]) if d else "—", "Total Contributions", ("since " + d["since"]) if d else "updates every 6 hours", "#4169E1"),
        (None, "Current Streak", d["cur_range"] if d else "—", "#E5383B"),
        ((str(d["long_streak"]) if d else "—"), "Longest Streak", d["long_range"] if d else "—", "#2F8D46"),
    ]
    for i, (val, lab, sub, color) in enumerate(cols):
        cx = cw * i + cw / 2
        if i > 0:
            s += '<line class="dv" x1="%s" y1="%d" x2="%s" y2="%d" stroke="#E3E8F5" stroke-width="1.2"/>' % (cw * i, top + 20, cw * i, h - 20)
        if val is None:
            r = 34; cy = top + 56; C = 2 * math.pi * r
            p = 0
            if d and d["long_streak"]:
                p = min(1.0, float(d["cur_streak"]) / d["long_streak"])
            off = C * (1 - p)
            s += '<circle class="tr" cx="%s" cy="%d" r="%d" fill="none" stroke="#E3E8F5" stroke-width="8"/>' % (fmt(cx), cy, r)
            s += '<circle class="rg" cx="%s" cy="%d" r="%d" fill="none" stroke="%s" stroke-width="8" stroke-linecap="round" transform="rotate(-90 %s %d)" stroke-dasharray="%s" stroke-dashoffset="%s" style="--c:%s;--o:%s"/>' % (fmt(cx), cy, r, color, fmt(cx), cy, fmt(C), fmt(off), fmt(C), fmt(off))
            s += '<text class="tx" x="%s" y="%d" text-anchor="middle" font-family="%s" font-size="26" font-weight="800" fill="#1B2A5C">%s</text>' % (fmt(cx), cy + 9, FONT, str(d["cur_streak"]) if d else "—")
            s += '<g class="fl" transform="translate(%s %d)"><circle r="11" fill="#FFC83D"/><g transform="translate(-7 -7) scale(.58)" fill="#9E1B1E" stroke="none">%s</g></g>' % (fmt(cx), cy - r, ICON["flame"])
            s += '<text class="tx" x="%s" y="%d" text-anchor="middle" font-family="%s" font-size="12" font-weight="700" fill="#1B2A5C">%s</text>' % (fmt(cx), h - 36, FONT, lab)
            s += '<text class="mu" x="%s" y="%d" text-anchor="middle" font-family="%s" font-size="10.5" fill="#5A6BA8">%s</text>' % (fmt(cx), h - 20, FONT, escape(sub))
        else:
            s += '<text x="%s" y="%d" text-anchor="middle" font-family="%s" font-size="32" font-weight="800" fill="%s">%s</text>' % (fmt(cx), top + 66, FONT, color, escape(val))
            s += '<text class="tx" x="%s" y="%d" text-anchor="middle" font-family="%s" font-size="12" font-weight="700" fill="#1B2A5C">%s</text>' % (fmt(cx), h - 36, FONT, lab)
            s += '<text class="mu" x="%s" y="%d" text-anchor="middle" font-family="%s" font-size="10.5" fill="#5A6BA8">%s</text>' % (fmt(cx), h - 20, FONT, escape(sub))
    s += card_close(w, h, "red")
    return s, h

def fmt(v):
    return ("%.1f" % v).rstrip("0").rstrip(".")

def stats_card(x, y, w, d):
    h = 246
    s = card_open(x, y, w, h, "GitHub Stats", "// @" + (os.environ.get("LOGIN") or "divyansh1502"), "blue")
    items = [
        ("Total Commits", d and d["commits"], "commit", "blue"),
        ("Pull Requests", d and d["prs"], "pr", "green"),
        ("Issues", d and d["issues"], "issue", "yellow"),
        ("Stars Earned", d and d["stars"], "star", "violet"),
        ("Public Repos", d and d["repos"], "repo", "red"),
        ("Followers", d and d["followers"], "users", "blue"),
    ]
    tw = (w - 36) / 2.0; th = 54
    for i, (lab, val, ic, col) in enumerate(items):
        c = COL[col]; r_, k = divmod(i, 2)
        tx = 12 + k * (tw + 12); ty = 54 + r_ * (th + 10); cid = uid("t")
        s += '<g class="pop" style="animation-delay:%ss">' % fmt(i * .08)
        s += '<clipPath id="%s"><rect x="%s" y="%d" width="%s" height="%d" rx="13"/></clipPath>' % (cid, fmt(tx), ty, fmt(tw), th)
        s += '<rect x="%s" y="%d" width="%s" height="%d" rx="13" fill="%s"/>' % (fmt(tx), ty + 3, fmt(tw), th, c["base"])
        s += '<rect x="%s" y="%d" width="%s" height="%d" rx="13" fill="%s"/><rect x="%s" y="%d" width="%s" height="%d" rx="13" fill="url(#strp)"/><rect x="%s" y="%d" width="%s" height="%d" rx="13" fill="url(#dots)"/>' % (fmt(tx), ty, fmt(tw), th, c["face"], fmt(tx), ty, fmt(tw), th, fmt(tx), ty, fmt(tw), th)
        s += '<g clip-path="url(#%s)"><rect class="sh" x="%s" y="%d" width="14" height="%d" fill="#fff" fill-opacity=".34" style="--t:%dpx;animation-delay:-%ss"/></g>' % (cid, fmt(tx - 30), ty - 4, th + 8, int(tw + 60), fmt(i * .5))
        s += '<circle cx="%s" cy="%s" r="17" fill="#fff"/><g transform="translate(%s %s) scale(.78)" fill="none" stroke="%s" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" color="%s">%s</g>' % (fmt(tx + 26), fmt(ty + th / 2), fmt(tx + 26 - 9.4), fmt(ty + th / 2 - 9.4), c["acc"], c["acc"], ICON[ic])
        s += '<text x="%s" y="%d" font-family="%s" font-size="19" font-weight="800" fill="%s">%s</text>' % (fmt(tx + 52), ty + 28, FONT, c["ink"], n(val) if d else "—")
        s += '<text x="%s" y="%d" font-family="%s" font-size="10.5" fill="%s" fill-opacity=".92">%s</text></g>' % (fmt(tx + 52), ty + 43, FONT, c["ink"], lab)
    s += card_close(w, h, "blue")
    return s, h

def langs_card(x, y, w, h, d):
    s = card_open(x, y, w, h, "Top Languages", "// by code size", "green")
    if not d or not d["langs"]:
        s += '<text class="mu" x="%s" y="%d" text-anchor="middle" font-family="%s" font-size="12" fill="#5A6BA8">Waiting for the first automatic update</text>' % (fmt(w / 2), 120, FONT)
        s += '<text class="mu" x="%s" y="%d" text-anchor="middle" font-family="%s" font-size="11" fill="#5A6BA8">(runs every 6 hours via GitHub Actions)</text>' % (fmt(w / 2), 140, MONO)
    else:
        trk_x = 112; trk_w = w - trk_x - 62
        for i, (name, pct) in enumerate(d["langs"][:6]):
            yy = 62 + i * 29; c = COL[CYCLE[i]]; bw = max(6.0, trk_w * pct / (d["langs"][0][1] or 1) * 0.98)
            s += '<text class="tx" x="20" y="%d" font-family="%s" font-size="12" font-weight="600" fill="#1B2A5C">%s</text>' % (yy + 9, FONT, escape(name))
            s += '<rect class="tr" x="%d" y="%d" width="%d" height="10" rx="5" fill="#E3E8F5"/>' % (trk_x, yy, trk_w)
            s += '<rect class="bar" x="%d" y="%d" width="%s" height="10" rx="5" fill="%s" style="animation-delay:%ss"/>' % (trk_x, yy, fmt(bw), c["face"], fmt(i * .12))
            s += '<text class="mu" x="%d" y="%d" font-family="%s" font-size="11" font-weight="700" fill="#5A6BA8">%s%%</text>' % (trk_x + trk_w + 10, yy + 9, MONO, fmt(pct))
    s += card_close(w, h, "green")
    return s

def wrap(W, H, body):
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" role="img" aria-label="GitHub statistics: contribution streak, totals and top languages">\n<title>GitHub stats</title>\n<style>%s</style>\n<defs>%s</defs>\n%s\n</svg>\n' % (W, H, W, H, CSS, PATTERNS, body))

def stamp(x, y, d):
    t = ("updated " + d["updated"]) if d else "pending first update"
    return '<text class="mu" x="%d" y="%d" text-anchor="end" font-family="%s" font-size="9.5" fill="#5A6BA8">%s</text>' % (x, y, MONO, t)

def render(d):
    _id[0] = 0
    sc, sh_ = streak_card(4, 4, 412, d); st, th_ = stats_card(4, 4 + sh_ + 14, 412, d)
    lc = langs_card(4, 4 + sh_ + 14 + th_ + 14, 412, th_, d)
    Hm = 4 + sh_ + 14 + th_ + 14 + th_ + 26
    open(os.path.join(OUT, "gh-stats-mobile.svg"), "w", encoding="utf-8").write(wrap(420, Hm, sc + st + lc + stamp(414, Hm - 8, d)))
    _id[0] = 0
    sc, sh_ = streak_card(4, 4, 832, d); st, th_ = stats_card(4, 4 + sh_ + 14, 412, d)
    lc = langs_card(424, 4 + sh_ + 14, 412, th_, d)
    Hw = 4 + sh_ + 14 + th_ + 26
    open(os.path.join(OUT, "gh-stats-wide.svg"), "w", encoding="utf-8").write(wrap(840, Hw, sc + st + lc + stamp(834, Hw - 8, d)))

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    tok, login = os.environ.get("GITHUB_TOKEN"), os.environ.get("LOGIN")
    if "--demo" in sys.argv:
        render(DEMO)
    elif tok and login:
        render(fetch(tok, login))
    else:
        render(None)
    print("stats SVGs written")
