#!/usr/bin/env python3
"""Builds assets/live-stats.svg: a terminal-style card with live LeetCode + GitHub numbers."""
import json, os, sys, urllib.request
from datetime import datetime, timezone

LC_USER = "divyansh_5ingh"
GH_USER = "divyansh1502"
OUT = "assets/live-stats.svg"
BG, GREEN, GOLD, IND, TXT, GREY = "#0D1117", "#3FB950", "#FFD700", "#A5B4FC", "#E6EDF3", "#8B949E"


def post_json(url, payload):
    req = urllib.request.Request(url, json.dumps(payload).encode(), {
        "Content-Type": "application/json", "User-Agent": "profile-readme-stats",
        "Referer": "https://leetcode.com"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def get_json(url):
    h = {"User-Agent": "profile-readme-stats"}
    if os.getenv("GITHUB_TOKEN"):
        h["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=20) as r:
        return json.load(r)


def fetch_leetcode():
    q = """query($u:String!){allQuestionsCount{difficulty count}
      matchedUser(username:$u){submitStats{acSubmissionNum{difficulty count}}}}"""
    d = post_json("https://leetcode.com/graphql", {"query": q, "variables": {"u": LC_USER}})["data"]
    solved = {x["difficulty"]: x["count"] for x in d["matchedUser"]["submitStats"]["acSubmissionNum"]}
    total = {x["difficulty"]: x["count"] for x in d["allQuestionsCount"]}
    return {k: (solved.get(k, 0), total.get(k, 1)) for k in ("Easy", "Medium", "Hard")} | {"All": solved.get("All", 0)}


def fetch_github():
    u = get_json(f"https://api.github.com/users/{GH_USER}")
    repos = get_json(f"https://api.github.com/users/{GH_USER}/repos?per_page=100&type=owner")
    return {"repos": u["public_repos"], "followers": u["followers"],
            "stars": sum(r.get("stargazers_count", 0) for r in repos)}


def render(lc, gh):
    W, X, CW = 860, 34, 9.6
    live = lc is not None
    css, body = [], []
    css.append(".m{font-family:'SFMono-Regular',Consolas,'Liberation Mono',Menlo,monospace;font-size:16px}")
    css.append("@keyframes grow{from{transform:scaleX(0)}to{transform:scaleX(1)}}")
    css.append("@keyframes blink{0%,49%{opacity:1}50%,100%{opacity:0}}")
    css.append(".bar{transform-box:fill-box;transform-origin:left;animation:grow 1.4s cubic-bezier(.2,.8,.2,1) both}")
    css.append(".bk{animation:blink 1s step-end infinite}")

    def txt(x, y, s, fill, extra=""):
        s = s.replace("&", "&amp;").replace("<", "&lt;")
        return f'<text class="m" x="{x}" y="{y}" fill="{fill}" {extra}>{s}</text>'

    y = 96
    body.append(txt(X, y, "$", GREEN) + txt(X + 2 * CW, y, "./stats --live --user " + LC_USER, TXT))
    y += 34
    total = lc["All"] if live else "--"
    body.append(txt(X, y, f"leetcode  solved {total}", GOLD))
    y += 30
    bar_x, bar_w = X + 11 * CW, 380
    for i, (name, col) in enumerate((("Easy", GREEN), ("Medium", GOLD), ("Hard", "#F85149"))):
        s, t = lc[name] if live else (0, 1)
        label = f"{name.lower():<7}"
        body.append(txt(X, y, label, IND))
        body.append(f'<rect x="{bar_x}" y="{y-13}" width="{bar_w}" height="14" rx="4" fill="#21262D"/>')
        if s:
            body.append(f'<rect class="bar" style="animation-delay:{i*0.2}s" x="{bar_x}" y="{y-13}" width="{max(8, bar_w*s/t):.1f}" height="14" rx="4" fill="{col}"/>')
        body.append(txt(bar_x + bar_w + 18, y, f"{s}/{t}" if live else "--", TXT))
        y += 28
    y += 14
    body.append(txt(X, y, "github    ", GOLD) + txt(X + 10 * CW, y,
        f"repos {gh['repos']}   stars {gh['stars']}   followers {gh['followers']}" if gh else "repos --   stars --   followers --", TXT))
    y += 34
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if live else "waiting for first sync"
    body.append(txt(X, y, "# last sync: " + stamp, GREY))
    y += 34
    body.append(txt(X, y, "$", GREEN) + f'<rect class="bk" x="{X+2*CW}" y="{y-15}" width="{CW}" height="19" fill="{GOLD}"/>')
    H = y + 34

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="Live LeetCode and GitHub stats">
<style>{" ".join(css)}</style>
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#4F46E5"/><stop offset="0.5" stop-color="#FFD700"/><stop offset="1" stop-color="#2F8D46"/></linearGradient></defs>
<rect x="1" y="1" width="{W-2}" height="{H-2}" rx="12" fill="{BG}" stroke="#30363D" stroke-width="2"/>
<path d="M1 13a12 12 0 0 1 12-12h{W-26}a12 12 0 0 1 12 12v32H1z" fill="#161B22"/>
<rect x="1" y="45" width="{W-2}" height="2" fill="url(#g)"/>
<circle cx="28" cy="24" r="6.5" fill="#FF5F56"/><circle cx="50" cy="24" r="6.5" fill="#FFBD2E"/><circle cx="72" cy="24" r="6.5" fill="#27C93F"/>
<text x="{W/2}" y="29" text-anchor="middle" class="m" fill="{GREY}" style="font-size:13px">divyansh@dev: ~/live-stats</text>
{chr(10).join(body)}
</svg>'''


if __name__ == "__main__":
    os.makedirs("assets", exist_ok=True)
    if "--placeholder" in sys.argv:
        lc = gh = None
    elif "--mock" in sys.argv:
        lc = {"Easy": (120, 880), "Medium": (95, 1850), "Hard": (12, 830), "All": 227}
        gh = {"repos": 18, "stars": 7, "followers": 21}
    else:
        try:
            lc, gh = fetch_leetcode(), fetch_github()
        except Exception as e:  # keep the previous SVG if any API is down
            print("fetch failed, keeping existing card:", e)
            sys.exit(0)
    open(OUT, "w", encoding="utf-8").write(render(lc, gh))
    print("wrote", OUT)
