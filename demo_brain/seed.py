"""Writes the public demo brain: fictional notes and a synthetic activity log.

The real brain holds client data, so the showcase runs on this stand-in. Same
format as the real one (frontmatter + body, one fact per note, JSONL events),
invented content. Deterministic: same output on every run.
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent
NOTES = ROOT / "notes"

# (slug, area, type, description, body, links, date)
DEMO = [
    ("working-style", "samarbete", "feedback",
     "How the operator wants agents to work: short answers, diff-table reports, ask before acting live",
     "Answer first, in one sentence where possible. Report every finished task as a diff table against the plan, never just 'done'. "
     "Anything that changes a live system (website, ads, email) needs an explicit yes in chat first. Several open decisions are asked as one clickable questionnaire.",
     ["never-overstate", "release-rules"], "2026-10-21"),
    ("never-overstate", "kvalitet", "feedback",
     "Never claim 'verified' or 'done' beyond what was actually checked; name what was not checked",
     "An agent may only write 'verified' about the exact thing it observed. Every report lists what was checked, how, and what was not. "
     "Unverified claims are marked as assumptions with a way to falsify them.",
     ["working-style", "whole-chain-checks"], "2026-10-16"),
    ("whole-chain-checks", "kvalitet", "feedback",
     "Every data flow is checked end to end: source, database, dashboard, plus dependencies",
     "A fix is not done when the code compiles. Follow the value from the source API through the ingest job and the database row to the number on screen, "
     "and check the jobs that depend on it.",
     ["never-overstate", "dashboard-data-sources"], "2026-10-21"),
    ("release-rules", "dashboard", "project",
     "How dashboard changes are released: preview build, cache-busting keys, operator approval, then deploy",
     "Changes go to a preview URL first. Static assets carry a version key (?v=) so browsers do not serve stale files. "
     "The operator approves in chat, then the deploy runs. Rollback is the previous preview.",
     ["working-style", "dashboard-data-sources"], "2026-10-21"),
    ("dashboard-data-sources", "dashboard", "reference",
     "Where the client dashboard gets its numbers: GA4, Search Console, LinkedIn Ads, CRM, nightly ingest jobs",
     "Five sources feed the dashboard. Nightly edge functions pull GA4, Search Console and LinkedIn Ads into Postgres; the CRM syncs hourly. "
     "Each table has a freshness check; a source older than 36 hours turns the health card amber.",
     ["release-rules", "whole-chain-checks", "data-health-check"], "2026-10-24"),
    ("data-health-check", "dashboard", "project",
     "The data health card: freshness per source, row counts vs. last week, and alerts on silent drops",
     "The card compares today's row count per source with the 7-day median. A drop over 40 % or a missing day raises an alert. "
     "Silent failures, not crashes, were the most common incident type.",
     ["dashboard-data-sources"], "2026-10-22"),
    ("seo-keyword-plan", "seo", "project",
     "Keyword plan for the company site: intent clusters, one page per cluster, no keyword stuffing",
     "Keywords are grouped by search intent, and each cluster gets one page. Titles answer the query; internal links follow the clusters. "
     "Success is measured in Search Console impressions per cluster over 90 days.",
     ["seo-ai-search", "website-changes"], "2026-10-27"),
    ("seo-ai-search", "seo", "reference",
     "How AI search engines pick sources: grounding, query fan-out, and why clear entity pages matter",
     "AI answers are grounded on a small set of retrieved pages. Query fan-out sends several sub-queries, so pages that answer one question clearly win. "
     "Structured data helps engines resolve the entity but does not guarantee a citation.",
     ["seo-keyword-plan"], "2026-10-22"),
    ("website-changes", "hemsida", "project",
     "Log of changes on the company website: meta descriptions, booking page, cookie banner",
     "Meta descriptions were rewritten for every service page. The booking page got a two-step form. The cookie banner defaults to 'necessary only'. "
     "Every change has a before/after screenshot.",
     ["release-rules", "seo-keyword-plan"], "2026-10-16"),
    ("growth-experiments", "growth", "reference",
     "Running growth experiments with small volumes: minimum detectable effect, power, and when not to test",
     "With under 1 000 visitors a month most A/B tests cannot detect realistic effects. Compute the minimum detectable effect first; "
     "if it is above 30 %, make the change on judgement and measure before/after instead.",
     ["growth-north-star"], "2026-10-21"),
    ("growth-north-star", "growth", "project",
     "North star metric: qualified meetings booked per month, with leading indicators per channel",
     "The single metric is qualified meetings booked. Leading indicators: booking-page visits, LinkedIn engaged companies, returning visitors from target accounts.",
     ["growth-experiments", "dashboard-data-sources"], "2026-10-21"),
    ("code-security-basics", "kod", "reference",
     "Security basics for the brain tooling: least privilege, no secrets in synced folders, hooks outside the sync",
     "Scripts that run in every session live outside the synced folder, so a synced file cannot inject code. "
     "Secrets never enter the brain; the health check scans notes for key-like strings.",
     ["brain-hooks"], "2026-10-21"),
    ("brain-hooks", "verktyg", "reference",
     "The hooks that feed the brain: SessionStart auto-load, PostToolUse event log, Stop reminder to save lessons",
     "SessionStart injects the working rules plus the notes for the folder's area. PostToolUse appends every brain read/write to activity.jsonl. "
     "Stop asks the session to save what it learned after a few turns.",
     ["code-security-basics", "scheduled-routines"], "2026-10-21"),
    ("scheduled-routines", "verktyg", "reference",
     "Scheduled agents: weekly inbox scan, weekly tidy, hourly project-lead check; all propose, none act live",
     "The inbox routine reads mail and chat and writes proposals. The tidy routine fixes mechanical issues and lists contradictions. "
     "Every proposal waits for the operator's yes or no.",
     ["brain-hooks", "working-style"], "2026-11-03"),
    ("client-restaurant-group", "sms", "project",
     "Fictional client: a restaurant group with four venues, a channel inventory and a board deck",
     "Scope: an analytics audit across four venues, a channel inventory and a board presentation. Access to every client account is read-only.",
     ["dashboard-data-sources", "deck-rules"], "2026-10-27"),
    ("deck-rules", "presentationer", "feedback",
     "Presentation rules: no invented numbers, one message per slide, uppercase headings, source on every chart",
     "Every number on a slide has a source in the speaker notes. One message per slide. Charts start at zero unless marked.",
     ["never-overstate", "client-restaurant-group"], "2026-10-23"),
    ("venue-research", "lokaler", "project",
     "Venue research for restaurant prospects: listings, brokers, size, rent, ventilation",
     "Each venue is scored on size, rent per square metre, kitchen ventilation and foot traffic. Brokers are emailed, never called.",
     ["prospect-questions"], "2026-10-22"),
    ("prospect-questions", "lokaler", "reference",
     "The fixed question template sent to a restaurant prospect: eight headings, same order every time",
     "Concept, capacity, opening hours, kitchen needs, budget, timeline, decision makers, deal breakers.",
     ["venue-research"], "2026-10-22"),
    ("future-openings", "projekt", "project",
     "Idea: a watch list of upcoming hotel and restaurant openings across the Nordics and UK",
     "Not active work. Sources would be planning permits, trade press RSS and operator announcements. Build only if a client asks.",
     ["venue-research"], "2026-10-22"),
    ("company-facts", "bolaget", "reference",
     "Company facts: what the consultancy does, team size, service lines, how it talks about itself",
     "A small consultancy that opens hotels and restaurants: concept, recruitment, training, launch marketing. Tone: warm, concrete, no buzzwords.",
     ["growth-north-star"], "2026-10-20"),
    ("ai-policy", "bolaget", "reference",
     "AI policy and risk matrix: which data may go to which AI tool, and who approves new tools",
     "Client personal data never goes to a tool without a data processing agreement. New tools are approved by the policy owner. "
     "The risk matrix scores likelihood and impact per use case.",
     ["company-facts", "code-security-basics"], "2026-10-22"),
    ("brain-lessons", "samarbete", "reference",
     "Shared lesson log: one line per thing that took an agent time to discover",
     "A file:// page cannot fetch() local files but can load <script src>. Full-screen transparent layers cost more than triangles on integrated GPUs. "
     "Scheduled browser runs stall silently on approval prompts.",
     ["brain-hooks", "working-style"], "2026-10-27"),
]

SESSIONS = ["dashboard", "seo", "growth", "brain-lead", "client-deck", "venues", "website", "routine:inbox"]
HOME = {"dashboard": "dashboard", "seo": "seo", "growth": "growth", "client-deck": "presentationer",
        "venues": "lokaler", "website": "hemsida", "brain-lead": "samarbete", "routine:inbox": "verktyg"}


def note_md(slug, area, typ, desc, body, links, date):
    rel = " ".join(f"[[{l}]]" for l in links)
    why = "**Why:** keeps agents consistent across sessions.\n**How to apply:** read before working in this area.\n" if typ in ("feedback", "project") else ""
    return (f"---\nname: {slug}\ndescription: \"{desc}\"\ntags: [område/{area}]\nmetadata:\n  type: {typ}\n  modified: {date}\n---\n\n"
            f"{body}\n\n{why}Related: {rel}\n")


def main():
    NOTES.mkdir(parents=True, exist_ok=True)
    for old in NOTES.glob("*.md"):
        old.unlink()
    for slug, area, typ, desc, body, links, date in DEMO:
        (NOTES / f"{slug}.md").write_text(note_md(slug, area, typ, desc, body, links, date), encoding="utf-8")

    rnd = random.Random(7)
    by_area = {}
    for d in DEMO:
        by_area.setdefault(d[1], []).append(d[0])
    t = datetime(2026, 10, 20, 8, 0, tzinfo=timezone(timedelta(hours=1)))
    events = []
    while t < datetime(2026, 10, 27, 18, 0, tzinfo=t.tzinfo):
        s = rnd.choice(SESSIONS)
        home = by_area.get(HOME[s], [])
        events.append({"ts": t.isoformat(), "session": s, "op": "collect", "note": "index"})
        for _ in range(rnd.randint(1, 4)):
            pool = home if home and rnd.random() < .7 else [d[0] for d in DEMO]
            events.append({"ts": t.isoformat(), "session": s, "op": "collect", "note": rnd.choice(pool)})
        if rnd.random() < .35:
            events.append({"ts": t.isoformat(), "session": s, "op": "push", "note": rnd.choice(home or ["brain-lessons"])})
        t += timedelta(minutes=rnd.randint(20, 140))
    (ROOT / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    print(f"{len(DEMO)} notes, {len(events)} events")


if __name__ == "__main__":
    main()
