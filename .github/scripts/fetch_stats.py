#!/usr/bin/env python3
"""
fetch_stats.py - fetch GitHub (and optional LeetCode) stats and render the
profile stats cards as SVG.

Outputs
  assets/gh-stats-wide.svg    (desktop card, used in <picture> min-width: 760px)
  assets/gh-stats-mobile.svg  (mobile card, fallback <img>)
  data/stats.json             (raw numbers, handy for other cards)

Usage
  export GITHUB_TOKEN=ghp_xxx          # or set it as a GitHub Action secret
  python scripts/fetch_stats.py --user divyansh1502
  python scripts/fetch_stats.py --user divyansh1502 --leetcode divyansh_5ingh
  python scripts/fetch_stats.py --demo  # no network, fake numbers, to preview the design

Only the Python standard library is used.
"""
import argparse
import json
import os
import random
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape

GITHUB_API = "https://api.github.com/graphql"
LEETCODE_API = "https://leetcode.com/graphql"

# Theme: royal blue + yellow
LANG_COLORS = ["#4169e1", "#ffd60a", "#5ea8ff", "#ffb800", "#b9ccff"]
HEAT_COLORS = ["#101c4a", "#1a2f8a", "#4169e1", "#5ea8ff", "#ffd60a"]

# --------------------------------------------------------------------------
# Fetching
# --------------------------------------------------------------------------

Q_PROFILE = """
query($login: String!, $cursor: String) {
  user(login: $login) {
    name
    createdAt
    followers { totalCount }
    pullRequests { totalCount }
    issues { totalCount }
    repositories(first: 100, after: $cursor, ownerAffiliations: OWNER, isFork: false) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes {
        stargazerCount
        languages(first: 8, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name } }
        }
      }
    }
  }
}
"""

Q_YEAR = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      totalCommitContributions
      restrictedContributionsCount
      contributionCalendar {
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""


def post_json(url, payload, headers):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "profile-stats", **headers},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code} from {url}: {e.read().decode(errors='replace')[:300]}")
    except urllib.error.URLError as e:
        sys.exit(f"Network error talking to {url}: {e.reason}")


def gh(query, variables, token):
    data = post_json(GITHUB_API, {"query": query, "variables": variables},
                     {"Authorization": f"bearer {token}"})
    if "errors" in data:
        sys.exit(f"GitHub API error: {data['errors']}")
    return data["data"]


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_github(login, token):
    # 1) profile + repositories (paginated)
    stars, repo_count, langs = 0, 0, {}
    cursor, profile = None, None
    while True:
        u = gh(Q_PROFILE, {"login": login, "cursor": cursor}, token)["user"]
        if u is None:
            sys.exit(f"GitHub user '{login}' not found")
        profile = profile or u
        repos = u["repositories"]
        repo_count = repos["totalCount"]
        for r in repos["nodes"]:
            stars += r["stargazerCount"]
            for edge in r["languages"]["edges"]:
                langs[edge["node"]["name"]] = langs.get(edge["node"]["name"], 0) + edge["size"]
        if not repos["pageInfo"]["hasNextPage"]:
            break
        cursor = repos["pageInfo"]["endCursor"]

    # 2) contributions, one request per calendar year (API limit is 1 year)
    created = datetime.fromisoformat(profile["createdAt"].replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    commits, days = 0, {}
    for year in range(created.year, now.year + 1):
        start = max(created, datetime(year, 1, 1, tzinfo=timezone.utc))
        end = min(now, datetime(year, 12, 31, 23, 59, 59, tzinfo=timezone.utc))
        cc = gh(Q_YEAR, {"login": login, "from": iso(start), "to": iso(end)}, token)[
            "user"]["contributionsCollection"]
        commits += cc["totalCommitContributions"] + cc["restrictedContributionsCount"]
        for w in cc["contributionCalendar"]["weeks"]:
            for d in w["contributionDays"]:
                days[d["date"]] = d["contributionCount"]

    current, longest = streaks(days)
    return {
        "login": login,
        "name": profile["name"] or login,
        "stars": stars,
        "commits": commits,
        "prs": profile["pullRequests"]["totalCount"],
        "issues": profile["issues"]["totalCount"],
        "repos": repo_count,
        "followers": profile["followers"]["totalCount"],
        "current_streak": current,
        "longest_streak": longest,
        "week_active": active_last_7(days),
        "langs": top_languages(langs),
        "days": days,
    }


def fetch_leetcode(username):
    """Optional: solved counts from LeetCode's public GraphQL endpoint."""
    q = """query($u: String!) { matchedUser(username: $u) {
             submitStatsGlobal { acSubmissionNum { difficulty count } } } }"""
    try:
        data = post_json(LEETCODE_API, {"query": q, "variables": {"u": username}},
                         {"Referer": "https://leetcode.com"})
        rows = data["data"]["matchedUser"]["submitStatsGlobal"]["acSubmissionNum"]
        return {r["difficulty"].lower(): r["count"] for r in rows}
    except (SystemExit, KeyError, TypeError):
        print("warning: could not fetch LeetCode stats, skipping", file=sys.stderr)
        return None


# --------------------------------------------------------------------------
# Derived numbers
# --------------------------------------------------------------------------

def streaks(days):
    """Return (current_streak, longest_streak) from {iso_date: count}."""
    if not days:
        return 0, 0
    ordered = sorted(days)
    longest = run = 0
    prev = None
    for d in ordered:
        if days[d] > 0:
            ok = prev is not None and (date.fromisoformat(d) - prev).days == 1 and run > 0
            run = run + 1 if ok else 1
            longest = max(longest, run)
            prev = date.fromisoformat(d)
        else:
            run = 0
            prev = date.fromisoformat(d)
    # current streak: walk back from today (today may still be empty)
    today = date.today()
    cursor = today if days.get(today.isoformat(), 0) > 0 else today - timedelta(days=1)
    current = 0
    while days.get(cursor.isoformat(), 0) > 0:
        current += 1
        cursor -= timedelta(days=1)
    return current, longest


def active_last_7(days):
    today = date.today()
    return sum(1 for i in range(7) if days.get((today - timedelta(days=i)).isoformat(), 0) > 0)


def top_languages(langs, n=5):
    total = sum(langs.values()) or 1
    ranked = sorted(langs.items(), key=lambda kv: kv[1], reverse=True)[:n]
    out = [[name, round(size * 100 / total)] for name, size in ranked]
    if out:  # make the percentages add up to the shown total
        shown = round(sum(s for _, s in ranked) * 100 / total)
        out[0][1] += shown - sum(p for _, p in out)
    return [(n_, max(p, 1)) for n_, p in out]


def heat_level(count):
    if count <= 0:
        return 0
    if count < 3:
        return 1
    if count < 6:
        return 2
    if count < 10:
        return 3
    return 4


def heat_columns(days, cols):
    """Last `cols` weeks as columns of 7 levels (Sun..Sat). None = no such day yet."""
    today = date.today()
    last_sunday = today - timedelta(days=(today.weekday() + 1) % 7)
    out = []
    for c in range(cols - 1, -1, -1):
        start = last_sunday - timedelta(weeks=c)
        col = []
        for r in range(7):
            d = start + timedelta(days=r)
            col.append(None if d > today else heat_level(days.get(d.isoformat(), 0)))
        out.append(col)
    return out


def demo_data():
    rnd = random.Random(7)
    days = {}
    for i in range(400):
        d = date.today() - timedelta(days=i)
        days[d.isoformat()] = 0 if rnd.random() < 0.25 else rnd.choice([1, 2, 3, 4, 6, 8, 12])
    cur, lng = streaks(days)
    return {
        "login": "divyansh1502", "name": "Divyansh Singh", "stars": 1284, "commits": 3912,
        "prs": 247, "issues": 138, "repos": 56, "followers": 42,
        "current_streak": cur, "longest_streak": lng, "week_active": active_last_7(days),
        "langs": [("Java", 41), ("TypeScript", 24), ("Python", 16), ("JavaScript", 12), ("CSS", 7)],
        "days": days,
    }


# --------------------------------------------------------------------------
# SVG rendering
# --------------------------------------------------------------------------

STYLE = """
text{font-family:'Segoe UI',Ubuntu,'Helvetica Neue',Arial,sans-serif}
.num{font-size:26px;font-weight:800;fill:#f2f6ff}
.lbl{font-size:12.5px;fill:#9db3ec}
.sub{font-size:12px;fill:#7089d0;letter-spacing:.3px}
.h{font-size:13px;font-weight:600;fill:#c9d8ff}
.tile{animation:rise .6s ease-out both}
.c{animation:cell .5s ease-out both}
.hot{animation:cell .5s ease-out both,glint 3.5s ease-in-out infinite}
.fire{transform-box:fill-box;transform-origin:50% 100%;animation:flick 1.1s ease-in-out infinite}
.ember{animation:up 3s ease-out infinite;opacity:0}
.dot{animation:blink 2.4s ease-in-out infinite}
.sweep{animation:sweep 7s ease-in-out infinite}
.langs{transform-box:fill-box;transform-origin:left;animation:wipe 1.2s .3s cubic-bezier(.2,.8,.2,1) both}
@keyframes rise{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
@keyframes cell{from{opacity:0}to{opacity:1}}
@keyframes glint{0%,100%{filter:none}50%{filter:brightness(1.5)}}
@keyframes flick{0%,100%{transform:scale(1,1) rotate(0)}30%{transform:scale(.95,1.07) rotate(-1.5deg)}60%{transform:scale(1.03,.96) rotate(1.5deg)}}
@keyframes up{0%{transform:translateY(0);opacity:0}15%{opacity:1}100%{transform:translateY(-60px);opacity:0}}
@keyframes blink{0%,100%{opacity:.5}50%{opacity:1}}
@keyframes sweep{0%{transform:translateX(-300px)}60%,100%{transform:translateX(1100px)}}
@keyframes wipe{from{transform:scaleX(0)}to{transform:scaleX(1)}}
"""


def defs(w, h):
    return f"""<defs>
<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#060e30"/><stop offset="1" stop-color="#02040f"/></linearGradient>
<linearGradient id="edge" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#4169e1"/><stop offset="0.55" stop-color="#16256b" stop-opacity="0.5"/><stop offset="1" stop-color="#ffd60a"/></linearGradient>
<linearGradient id="hd" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#8db4ff"/><stop offset="1" stop-color="#ffd60a"/></linearGradient>
<linearGradient id="panel" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#14267a" stop-opacity="0.85"/><stop offset="1" stop-color="#0a1448" stop-opacity="0.85"/></linearGradient>
<linearGradient id="tile" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#0f1d58"/><stop offset="1" stop-color="#08123a"/></linearGradient>
<linearGradient id="flame" x1="0" y1="1" x2="0" y2="0"><stop offset="0" stop-color="#ffd60a"/><stop offset="0.5" stop-color="#ffa500"/><stop offset="1" stop-color="#ff5a00"/></linearGradient>
<linearGradient id="sweepg" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset="0.5" stop-color="#8db4ff" stop-opacity="0.12"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>
<radialGradient id="fglow" cx="0.5" cy="0.5" r="0.5"><stop offset="0" stop-color="#ffb800" stop-opacity="0.35"/><stop offset="1" stop-color="#ffb800" stop-opacity="0"/></radialGradient>
<filter id="glow" x="-60%" y="-60%" width="220%" height="220%"><feGaussianBlur stdDeviation="3" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
<clipPath id="card"><rect x="1" y="1" width="{w-2}" height="{h-2}" rx="22"/></clipPath>
</defs>
<style>{STYLE}</style>
<rect x="1" y="1" width="{w-2}" height="{h-2}" rx="22" fill="url(#bg)"/>
<g clip-path="url(#card)"><rect class="sweep" x="0" y="0" width="220" height="{h}" fill="url(#sweepg)" transform="skewX(-18)"/></g>
<rect x="1" y="1" width="{w-2}" height="{h-2}" rx="22" stroke="url(#edge)" stroke-width="1.5"/>"""


def flame(cx, cy, scale):
    return f"""<g transform="translate({cx} {cy}) scale({scale})" filter="url(#glow)"><g class="fire">
<path d="M0,-16 C4,-8 11,-5 11,4 C11,11 6,16 0,16 C-6,16 -11,11 -11,4 C-11,-1 -8,-4 -6,-7 C-5,-3 -3,-2 -2,-2 C-2,-8 -1,-12 0,-16 Z" fill="url(#flame)"/>
<path d="M0,3 C3,7 6,9 6,12 C6,15 3,16 0,16 C-3,16 -6,15 -6,12 C-6,9 -2,7 0,3 Z" fill="#fff1a8"/></g></g>"""


def embers(cx, base_y):
    spec = [(-12, 0, 1.8), (8, 0.8, 1.5), (-3, 1.5, 2), (14, 2.1, 1.3), (-16, 2.7, 1.4)]
    return "".join(
        f'<circle class="ember" style="animation-delay:{d}s" cx="{cx + dx}" cy="{base_y}" r="{r}" fill="#ffd60a"/>'
        for dx, d, r in spec)


ICONS = {
    "star": '<polygon points="0,-8 2.4,-2.6 8,-2.4 3.6,1.4 5,7 0,4 -5,7 -3.6,1.4 -8,-2.4 -2.4,-2.6" fill="{c}"/>',
    "commit": '<circle r="4" stroke="{c}" stroke-width="2"/><path d="M-10 0H-4M4 0H10" stroke="{c}" stroke-width="2" stroke-linecap="round"/>',
    "pr": '<circle cx="-5" cy="-6" r="2.5" stroke="{c}" stroke-width="2"/><circle cx="-5" cy="6" r="2.5" stroke="{c}" stroke-width="2"/><circle cx="6" cy="6" r="2.5" stroke="{c}" stroke-width="2"/><path d="M-5 -3.5V3.5M6 3.5V-3H2" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
    "issue": '<circle r="7" stroke="{c}" stroke-width="2"/><circle r="1.8" fill="{c}"/>',
}


def tiles(d):
    return [
        ("Stars", f"{d['stars']:,}", "star", "#ffd60a"),
        ("Commits", f"{d['commits']:,}", "commit", "#5ea8ff"),
        ("Pull requests", f"{d['prs']:,}", "pr", "#ffd60a"),
        ("Issues", f"{d['issues']:,}", "issue", "#5ea8ff"),
    ]


def tile_svg(x, y, w, h, item, i, horizontal):
    label, value, icon, color = item
    head = (f'<g class="tile" style="animation-delay:{0.15 * i:.2f}s">'
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="url(#tile)" stroke="#223a9a" stroke-opacity="0.7"/>'
            f'<rect x="{x + 14}" y="{y}" width="40" height="3" rx="1.5" fill="{color}"/>')
    if horizontal:
        body = (f'<g transform="translate({x + 30} {y + h / 2 + 2})">{ICONS[icon].format(c=color)}</g>'
                f'<text x="{x + 56}" y="{y + h / 2 + 2}" class="num">{value}</text>'
                f'<text x="{x + 56}" y="{y + h / 2 + 20}" class="lbl">{label}</text></g>')
    else:
        body = (f'<g transform="translate({x + 22} {y + 28})">{ICONS[icon].format(c=color)}</g>'
                f'<text x="{x + 14}" y="{y + 68}" class="num">{value}</text>'
                f'<text x="{x + 14}" y="{y + 84}" class="lbl">{label}</text></g>')
    return head + body


def lang_bar(x, y, width, langs, height=12):
    gap = 4
    total = width - gap * (len(langs) - 1)
    pct_sum = sum(p for _, p in langs) or 1
    cx, out = x, ""
    for i, (_, p) in enumerate(langs):
        w = total * p / pct_sum
        out += f'<rect x="{cx:.1f}" y="{y}" width="{w:.1f}" height="{height}" rx="{height / 2}" fill="{LANG_COLORS[i % 5]}"/>'
        cx += w + gap
    return f'<g class="langs">{out}</g>'


def legend_item(x, y, i, name, pct):
    c = LANG_COLORS[i % 5]
    return (f'<circle cx="{x + 4}" cy="{y - 4}" r="4" fill="{c}"/>'
            f'<text x="{x + 14}" y="{y}" class="lbl">{escape(name)} <tspan fill="{c}" font-weight="700">{pct}%</tspan></text>')


def heatmap(x0, y0, columns):
    rnd = random.Random(3)  # deterministic glint delays
    out = []
    for c, col in enumerate(columns):
        for r, lv in enumerate(col):
            if lv is None:
                continue
            hot = lv == 4
            delay = f"{c * 0.03:.2f}s" + (f",{rnd.uniform(0, 4):.1f}s" if hot else "")
            out.append(f'<rect class="{"c hot" if hot else "c"}" style="animation-delay:{delay}" '
                       f'x="{x0 + c * 14}" y="{y0 + r * 14}" width="10" height="10" rx="2.5" fill="{HEAT_COLORS[lv]}"/>')
    return "".join(out)


def streak_block(d, cx, flame_y, num_y, scale):
    return (f'<circle cx="{cx}" cy="{flame_y + 2}" r="64" fill="url(#fglow)"/>'
            + flame(cx, flame_y, scale) + embers(cx, flame_y + 26))


def render_wide(d):
    w, h = 900, 420
    login = escape(d["login"])
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" fill="none" '
             f'role="img" aria-label="GitHub stats for {login}"><title>GitHub stats for {login}</title>', defs(w, h)]
    parts.append(f'<rect x="28" y="28" width="274" height="{h - 56}" rx="18" fill="url(#panel)" stroke="#2a44ad" stroke-opacity="0.6"/>')
    parts.append(f'<text x="165" y="64" text-anchor="middle" font-size="18" font-weight="700" fill="url(#hd)">{login}</text>')
    parts.append('<text x="165" y="82" text-anchor="middle" class="sub">GitHub stats</text>')
    parts.append(streak_block(d, 165, 170, 266, 2.5))
    parts.append(f'<text x="165" y="266" text-anchor="middle" font-size="56" font-weight="800" fill="#f2f6ff">{d["current_streak"]}</text>')
    parts.append('<text x="165" y="288" text-anchor="middle" class="sub">day streak</text>')
    parts.append('<rect x="95" y="302" width="140" height="26" rx="13" fill="#2a2400" stroke="#ffd60a" stroke-opacity="0.7"/>')
    parts.append(f'<text x="165" y="320" text-anchor="middle" font-size="12.5" font-weight="600" fill="#ffd60a">best {d["longest_streak"]} days</text>')
    for i in range(7):
        on = i < d["week_active"]
        parts.append(f'<circle cx="{165 - 48 + i * 16}" cy="352" r="4" fill="{"#ffd60a" if on else "#1a2f8a"}"'
                     + (f' class="dot" style="animation-delay:{i * 0.2:.1f}s"' if on else "") + "/>")
    parts.append(f'<text x="165" y="376" text-anchor="middle" class="sub">{d["week_active"]} of 7 days this week</text>')

    parts.append('<text x="330" y="60" font-size="20" font-weight="700" fill="#f2f6ff">Overview</text>')
    parts.append(f'<text x="870" y="60" text-anchor="end" class="sub">{date.today().year}</text>')
    for i, item in enumerate(tiles(d)):
        parts.append(tile_svg(330 + i * 138, 84, 126, 94, item, i, horizontal=False))
    parts.append('<text x="330" y="212" class="h">Top languages</text>')
    parts.append(lang_bar(330, 226, 540, d["langs"], 12))
    for i, (n, p) in enumerate(d["langs"]):
        parts.append(legend_item(330 + i * 108, 262, i, n, p))
    parts.append('<text x="330" y="284" class="h">Contributions</text>')
    parts.append('<text x="870" y="284" text-anchor="end" class="sub">last 38 weeks</text>')
    parts.append(heatmap(332, 292, heat_columns(d["days"], 38)))
    parts.append("</svg>")
    return "\n".join(parts)


def render_mobile(d):
    w, h = 480, 640
    login = escape(d["login"])
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" fill="none" '
             f'role="img" aria-label="GitHub stats for {login}"><title>GitHub stats for {login}</title>', defs(w, h)]
    parts.append('<rect x="16" y="16" width="448" height="170" rx="18" fill="url(#panel)" stroke="#2a44ad" stroke-opacity="0.6"/>')
    parts.append(f'<text x="34" y="46" font-size="17" font-weight="700" fill="url(#hd)">{login}</text>')
    parts.append('<text x="34" y="63" class="sub">GitHub stats</text>')
    parts.append(streak_block(d, 76, 122, 0, 1.9))
    parts.append(f'<text x="124" y="136" font-size="50" font-weight="800" fill="#f2f6ff">{d["current_streak"]}</text>')
    parts.append('<text x="126" y="158" class="sub">day streak</text>')
    parts.append('<rect x="300" y="84" width="140" height="26" rx="13" fill="#2a2400" stroke="#ffd60a" stroke-opacity="0.7"/>')
    parts.append(f'<text x="370" y="102" text-anchor="middle" font-size="12.5" font-weight="600" fill="#ffd60a">best {d["longest_streak"]} days</text>')
    for i in range(7):
        on = i < d["week_active"]
        parts.append(f'<circle cx="{306 + i * 18}" cy="134" r="4" fill="{"#ffd60a" if on else "#1a2f8a"}"'
                     + (f' class="dot" style="animation-delay:{i * 0.2:.1f}s"' if on else "") + "/>")
    parts.append(f'<text x="370" y="158" text-anchor="middle" class="sub">{d["week_active"]} of 7 days this week</text>')

    for i, item in enumerate(tiles(d)):
        x = 16 + (i % 2) * 232
        y = 202 + (i // 2) * 92
        parts.append(tile_svg(x, y, 216, 80, item, i, horizontal=True))

    parts.append('<text x="16" y="408" class="h">Top languages</text>')
    parts.append(lang_bar(16, 420, 448, d["langs"], 12))
    for i, (n, p) in enumerate(d["langs"]):
        parts.append(legend_item(16 + (i % 3) * 150, 456 + (i // 3) * 22, i, n, p))
    parts.append('<text x="16" y="512" class="h">Contributions</text>')
    parts.append('<text x="464" y="512" text-anchor="end" class="sub">last 32 weeks</text>')
    parts.append(heatmap(18, 524, heat_columns(d["days"], 32)))
    parts.append("</svg>")
    return "\n".join(parts)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Generate GitHub stats SVG cards")
    ap.add_argument("--user", default=os.getenv("GH_USER", "divyansh1502"))
    ap.add_argument("--leetcode", default=os.getenv("LEETCODE_USER"), help="optional LeetCode username")
    ap.add_argument("--out", default="assets", help="folder for the SVG files")
    ap.add_argument("--data", default="data/stats.json", help="where to write the raw JSON")
    ap.add_argument("--demo", action="store_true", help="use fake data, no network")
    args = ap.parse_args()

    if args.demo:
        stats = demo_data()
    else:
        token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
        if not token:
            sys.exit("Set GITHUB_TOKEN (or GH_TOKEN) first.")
        stats = fetch_github(args.user, token)
        if args.leetcode:
            stats["leetcode"] = fetch_leetcode(args.leetcode)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "gh-stats-wide.svg").write_text(render_wide(stats), encoding="utf-8")
    (out / "gh-stats-mobile.svg").write_text(render_mobile(stats), encoding="utf-8")

    data_path = Path(args.data)
    data_path.parent.mkdir(parents=True, exist_ok=True)
    slim = {k: v for k, v in stats.items() if k != "days"}
    slim["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    data_path.write_text(json.dumps(slim, indent=2), encoding="utf-8")
    print(f"Wrote {out / 'gh-stats-wide.svg'}, {out / 'gh-stats-mobile.svg'} and {data_path}")


if __name__ == "__main__":
    main()
