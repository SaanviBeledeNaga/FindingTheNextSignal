from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Collapsible, DataTable, Header, Input, Label, Static

from .engine import challenge
from .presentation import alternatives, evidence_criteria, headline, plain_log, plain_status, series, significance
from .report import export
from .store import Store
from . import dashboard

COLORS = {"green": "#70c99c", "amber": "#efc56e", "red": "#ed8c8c", "grey": "#9aabb8"}


class InformationScreen(ModalScreen):
    AUTO_FOCUS = "#dialog-close"
    BINDINGS = [("escape", "dismiss", "Close"), ("question_mark", "dismiss", "Close")]
    CSS = """
    InformationScreen { align: center middle; background: #000000 65%; }
    #dialog { width: 88; max-width: 95%; height: auto; max-height: 90%; background: #0d1828; border: solid #29445c; padding: 1 3; }
    #dialog-scroll { height: auto; max-height: 28; }
    #dialog-title { text-style: bold; margin-bottom: 1; color: #25d9e8; }
    #dialog-body { height: auto; }
    #dialog-close { margin-top: 1; }
    """

    def __init__(self, title, content, button="Back To Findings"):
        super().__init__()
        self.heading, self.content, self.button_label = title, content, button

    def compose(self):
        with Vertical(id="dialog"):
            yield Label(Text(self.heading), id="dialog-title")
            with VerticalScroll(id="dialog-scroll"):
                yield Static(Text(self.content), id="dialog-body")
            yield Button(self.button_label, id="dialog-close")

    def on_button_pressed(self, event):
        self.dismiss()


class Workbench(App):
    TITLE = "PHARMA-SCOPE"
    SUB_TITLE = "Company research, with evidence you can inspect"
    CSS = """
    Screen { background: #080e19; color: #dce6f3; }
    Header { background: #0c1424; color: #25d9e8; }
    #banner { height: 2; padding: 0 2; background: #0a1220; }
    #metrics { height: 5; margin: 0 1; }
    .metric { width: 1fr; height: 5; margin-right: 1; padding: 0 1; border: round #26334a; background: #0d1627; }
    #pipeline { height: 3; padding: 0 2; color: #8a9bb4; }
    #body { height: 1fr; margin: 0 1; }
    #left { width: 23%; min-width: 24; border: round #26334a; background: #0b1322; margin-right: 1; }
    #right { width: 1fr; border: round #26334a; background: #0b1322; margin-right: 1; }
    #intel { width: 27%; min-width: 26; }
    .label { height: 2; padding: 0 1; text-style: bold; color: #25d9e8; }
    #nav { height: auto; padding: 0 1; }
    #nav Button { width: 1fr; height: 3; margin-bottom: 0; text-align: left; background: #0c1829; color: #a8c0d8; border: solid #20354a; }
    #nav Button:focus { color: #25d9e8; border: solid #25d9e8; }
    #findings { height: 1fr; min-height: 4; background: #0b1322; }
    #left-note { height: 4; padding: 0 1; color: #8a9bb4; }
    DataTable > .datatable--header { background: #121f32; color: #8a9bb4; }
    DataTable > .datatable--cursor { background: #103041; color: #25d9e8; }
    DataTable, VerticalScroll { scrollbar-color: #31445e; scrollbar-background: #0b1322; }
    Button:focus { border: solid #25d9e8; background: #143044; }
    Input:focus { border: solid #25d9e8; }
    #snapshot { height: 11; padding: 0 1; border-bottom: solid #26334a; }
    #activity { height: auto; padding: 0 1; }
    #source-summary { height: auto; padding: 0 1; color: #a8b7cc; }
    #source-scroll { height: 1fr; min-height: 4; border: round #26334a; background: #0b1322; margin-bottom: 1; }
    #stream-scroll { height: 13; border: round #26334a; background: #0b1322; }
    #review-panel { height: 9; border: round #26334a; background: #0b1322; margin-bottom: 1; }
    #evidence-review { height: 1fr; padding: 0 1; color: #8a9bb4; }
    #detail { padding: 0 2; height: auto; max-width: 84; }
    #scroll { height: 1fr; }
    #evidence-badge { margin: 0 1; height: 3; width: 1fr; min-width: 0; border: solid #294055; background: #102235; }
    #evidence-box { margin: 0 2; max-width: 84; }
    #evidence-preview { height: auto; }
    #related { height: auto; margin: 0 2; }
    #related-list { height: auto; }
    #related-list Button { width: 1fr; height: 3; }
    #challenge-result { height: auto; max-width: 84; margin: 1 2; }
    #examples, #quick-actions { height: 3; margin: 0 1; }
    #examples Button, #quick-actions Button { min-width: 8; width: 1fr; height: 3; margin-right: 1; border: solid #254159; background: #0e2031; color: #25d9e8; }
    #commandbar { height: 3; margin: 0 1; }
    #challenge { width: 1fr; border: solid #254159; background: #0b1726; }
    #send { width: 16; min-width: 12; border: solid #254159; background: #103041; color: #25d9e8; }
    #status { height: 1; padding: 0 2; color: #8a9bb4; }
    #keyhint { height: 1; padding: 0 2; background: #0d1828; color: #9db3c9; }
    .compact #intel { display: none; }
    .compact #left { width: 29%; }
    .compact #nav, .compact #left-note { display: none; }
    .compact #nav-label, .compact #metric-2, .compact #metric-3 { display: none; }
    .compact #metrics { height: 4; }
    .compact .metric { height: 4; }
    .compact #snapshot { height: 7; }
    .compact #examples { display: none; }
    .compact #banner { height: 1; }
    """
    BINDINGS = [Binding(k, a, d, show=False) for k, a, d in [
        ("q", "quit", "Quit"), ("e", "evidence", "Evidence"), ("s", "skeptic", "Explanations"),
        ("t", "timeline", "Timeline"), ("c", "focus_challenge", "Ask a question"), ("x", "export", "Export"),
        ("r", "rerun_challenge", "Re-run question"), ("l", "logs", "Detailed activity"),
        ("question_mark", "help", "Help"), ("escape", "back", "Back"), ("b", "summary", "Summary"),
        ("f1", "overview", "Dashboard"), ("f2", "evidence", "Evidence"), ("f3", "timeline", "Timeline"),
        ("f4", "pipeline", "Pipeline"), ("f5", "refresh", "Refresh")]]

    def __init__(self, root, run_id="latest", show_summary=True):
        super().__init__()
        self.root_path, self.requested_run = root, run_id
        self.run_data, self.selected = None, 0
        self.view = "overview"
        self.last_challenge = None
        self.show_startup_summary = show_summary
        self.challenge_busy = False
        self.exported = False
        self.related_revision = 0
        self.snapshot_marker = None
        self.loading = False
        self.finding_signature = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("Loading investigation…", id="banner")
        with Horizontal(id="metrics"):
            for index in range(4):
                yield Static('', id=f'metric-{index}', classes='metric')
        yield Static("", id="pipeline")
        with Horizontal(id="body"):
            with Vertical(id="left"):
                yield Label("Command Navigation", classes="label", id='nav-label')
                with Vertical(id='nav'):
                    yield Button('F1  Dashboard', id='nav-overview')
                    yield Button('F2  Evidence', id='nav-evidence')
                    yield Button('F3  Timeline', id='nav-timeline')
                    yield Button('F4  Research Pipeline', id='nav-pipeline')
                yield Label("Research Findings", classes="label")
                yield DataTable(id="findings", cursor_type="row")
                yield Static('↑↓ Select · Enter Inspect\nEvidence ratings are not probabilities.\nF5 Refresh · B Summary', id='left-note')
            with Vertical(id="right"):
                yield Static('', id='snapshot')
                with VerticalScroll(id="scroll"):
                    yield Static("", id="detail")
                    with Collapsible(title="Related Findings — Same Revenue Mix", collapsed=True, id="related"):
                        with Vertical(id="related-list"):
                            yield Static("No related finding.")
                    with Collapsible(title="Evidence — Source Names And Dates", collapsed=False, id="evidence-box"):
                        yield Static("", id="evidence-preview")
                    yield Static("", id="challenge-result")
                with Horizontal(id="examples"):
                    yield Button("Currency?", id="currency")
                    yield Button("Acquisition?", id="acquisition")
                    yield Button("Restatement?", id="restatement")
                with Horizontal(id='quick-actions'):
                    yield Button('Overview', id='quick-overview')
                    yield Button('Evidence', id='quick-evidence')
                    yield Button('Pipeline', id='quick-pipeline')
                    yield Button('Export', id='quick-export')
            with Vertical(id='intel'):
                with Vertical(id='review-panel'):
                    yield Label('Evidence Review', classes='label')
                    yield Button("Evidence Rating · Enter For Details", id="evidence-badge")
                    yield Static('', id='evidence-review')
                with VerticalScroll(id='source-scroll'):
                    yield Static('', id='source-summary')
                with VerticalScroll(id='stream-scroll'):
                    yield Static('', id='activity')
        with Horizontal(id='commandbar'):
            yield Input(placeholder="Archive question › Could currency explain this change?", id="challenge")
            yield Button('Search [Enter]', id='send')
        yield Static("Select a finding to inspect its evidence and limitations.", id="status")
        yield Static("", id="keyhint")

    async def on_mount(self):
        self.screen.set_class(self.size.width < 115 or self.size.height < 38, 'compact')
        self.query_one("#findings", DataTable).add_columns("What Changed", "Evidence")
        self.load_run()
        self.query_one("#findings", DataTable).focus()
        self.call_after_refresh(self.update_hint)
        self.set_interval(2, self.refresh_snapshot)
        if self.show_startup_summary:
            await self.action_summary()

    def load_run(self):
        store = Store(self.root_path)
        try:
            run = store.run(self.requested_run)
            if run.get('kind') == 'research':
                state = store.agent_state(run['id'])
                for key in ('status', 'facts', 'findings', 'usage', 'events', 'warnings', 'profile', 'plan'):
                    run[key] = state.get(key, run.get(key))
                run['sources'] = [{**s, **store.metadata(s['id'])} for s in store.sources(run['company']) if s['id'] in state['source_ids']]
                run['parameters'] = state['limits']
            marker = json.dumps([run['status'], len(run.get('facts', [])), len(run['findings']), len(run['sources']),
                                 len(run['events']), run.get('usage', {}).get('model_calls'), run.get('usage', {}).get('sources')])
            if marker == self.snapshot_marker:
                return
            self.snapshot_marker = marker
            self.run_data = run
            self.requested_run = run['id']
        finally:
            store.close()
        self.loading = True
        self.exported = (Path(self.root_path) / "exports" / (self.run_data["id"] + ".html")).exists()
        table = self.query_one("#findings", DataTable)
        self.selected = min(self.selected, max(0, len(self.run_data['findings']) - 1))
        signature = [(f['id'], f['title'], f['strength']) for f in self.run_data['findings']]
        if signature != self.finding_signature:
            self.finding_signature = signature
            table.clear()
            for f in self.run_data["findings"]:
                points = series(f)
                label = (f["title"].split(":", 1)[0] + f" {points[-1]['share_pct'] - points[0]['share_pct']:+.2f} pp") if points else f.get("angle", "Data Comparison").replace("_", " ").title()
                table.add_row(Text(label), Text(f["strength"], style=self.finding_color(f)))
            if self.run_data['findings']:
                table.move_cursor(row=self.selected)
        banner = Text('PHARMA-SCOPE  /  ', style='bold #25d9e8')
        banner.append(self.run_data["company"] + "  ", style='bold #dce6f3')
        if self.run_data["demo"]:
            banner.append(" SYNTHETIC DEMO — NOT REAL COMPANY DATA ", style="bold black on #efc56e")
        else:
            banner.append(self.run_data['status'].replace('_', ' ').title() + ' · ' + self.run_data['id'], style=COLORS["grey"])
        self.query_one("#banner", Static).update(banner)
        self.render_pipeline()
        self.render_detail()
        self.loading = False

    def refresh_snapshot(self):
        if not self.screen_stack or len(self.screen_stack) > 1 or self.challenge_busy:
            return
        try:
            self.load_run()
        except (ValueError, OSError, sqlite3.Error):
            self.query_one('#status', Static).update('Could not refresh saved research. Press F5 to retry.')

    def action_refresh(self):
        self.snapshot_marker = None
        self.refresh_snapshot()

    def render_dashboard(self):
        if not self.run_data:
            return
        for index, card in enumerate(dashboard.cards(self.run_data)):
            self.query_one(f'#metric-{index}', Static).update(dashboard.card_text(card, self.screen_stack[0].has_class('compact')))
        self.query_one('#snapshot', Static).update(dashboard.chart(self.run_data, self.current(), self.screen_stack[0].has_class('compact')))
        self.query_one('#source-summary', Static).update(dashboard.source_ledger(self.run_data))
        self.query_one('#activity', Static).update(dashboard.activity_stream(self.run_data))
        current = self.current()
        status = ('Cause unresolved' if current and current['status'].startswith('observed') else
                  current['status'].replace('_', ' ').title() if current else 'No supported discovery')
        text = Text(status + '\n', style=self.finding_color(current) if current else COLORS['amber'])
        text.append('Categories, not probabilities.', style=COLORS['grey'])
        self.query_one('#evidence-review', Static).update(text)

    def finding_color(self, finding):
        return COLORS["green"] if finding["status"] == "supported" else COLORS["red"] if finding["status"] == "rejected" else COLORS["amber"]

    def render_pipeline(self):
        if not self.run_data:
            return
        research = self.run_data.get("kind") == "research"
        stages = {e["stage"] for e in self.run_data["events"] if not research or e["message"].startswith("Completed ")}
        supported = any(f["status"] == "supported" for f in self.run_data["findings"])
        steps = [("Profile", "resolve" in stages if research else "profile" in stages),
                 ("Validate", bool(self.run_data.get("facts")) if research else "validate" in stages),
                 ("Discover", "hypothesize" in stages if research else "discover" in stages),
                 ("Challenge", "skeptic" in stages), ("Verify", supported),
                 ("Report" if self.run_data['status'] == 'completed' else 'Partial Report', self.exported)]
        pipeline = Text(" → ".join(label + (" ✓" if done else " ○") for label, done in steps))
        pipeline.append("\n" + ("Verification needs independent sources and resolved alternatives." if not supported else "Evidence checks passed; inspect limitations before using the finding."), style=COLORS["amber"] if not supported else COLORS["green"])
        self.query_one("#pipeline", Static).update(pipeline)
        self.query_one("#activity", Static).update(dashboard.activity_stream(self.run_data))

    def on_descendant_focus(self, event):
        if self.is_mounted and self.screen_stack and event.widget is self.focused:
            self.update_hint(event.widget)

    def on_resize(self, event):
        if self.screen_stack:
            compact = event.size.width < 115 or event.size.height < 38
            changed = compact != self.screen_stack[0].has_class('compact')
            self.screen_stack[0].set_class(compact, 'compact')
            if changed and len(self.screen_stack) == 1 and self.run_data:
                self.render_dashboard()

    def update_hint(self, target=None):
        if not self.screen_stack:
            return
        target = target or self.focused
        if isinstance(target, Input):
            hint = "Enter: Search evidence · Esc: Back to findings"
        elif isinstance(target, Button):
            hint = "Enter: Activate · Tab: Next action · Esc: Findings · ?: Help"
        elif isinstance(target, DataTable):
            hint = ("↑↓: Pick · Enter: Open · E: Evidence · C: Ask · X: Export · ?: Help · Q: Quit" if self.current() else
                    "E: Sources · F4: Pipeline · F5: Refresh · X: Partial Export · ?: Help · Q: Quit")
        else:
            hint = "↑↓: Scroll · E: Evidence · T: Timeline · C: Ask · Esc: Findings · ?: Help"
        self.query_one("#keyhint", Static).update(Text(hint))

    def current(self):
        if not self.run_data or not self.run_data["findings"]:
            return None
        return self.run_data["findings"][min(self.selected, len(self.run_data["findings"]) - 1)]

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted):
        if self.loading:
            return
        if self.selected == event.cursor_row:
            return
        if self.selected != event.cursor_row:
            self.last_challenge = None
        self.selected = event.cursor_row
        self.render_detail()

    def on_data_table_row_selected(self, event):
        self.query_one("#scroll", VerticalScroll).focus()
        self.update_hint()

    def evidence_text(self, finding, full=False):
        facts = {r["id"]: r for r in self.run_data.get("facts", self.run_data["observations"])}
        sources = {s["id"]: s for s in self.run_data["sources"]}
        out, seen_publishers, seen_sources = [], set(), set()
        for fid in list(dict.fromkeys(finding["evidence"] + finding.get("opposing_evidence", []))):
            row = facts.get(fid)
            if not row:
                continue
            source = sources[row["source_id"]]
            if not full and source["id"] in seen_sources:
                continue
            origin = "Repeated Issuer Origin" if source["publisher"] in seen_publishers else "Original Document; Independence Unverified"
            if self.run_data["demo"]:
                origin = "Synthetic; Repeated Fictional Issuer"
            seen_publishers.add(source["publisher"])
            seen_sources.add(source["id"])
            text = f"{source['title']}\nDate: {source['published'] or 'Unknown'} · Page {row['page']}\n{origin}\n"
            if full:
                text += f"{fid}\n{row['quote']}\nSHA256 {source['sha256']}\n{source['url'] or 'Local archived source'}\n"
            out.append(text)
        return "\n".join(out) or "No source evidence available."

    def render_detail(self):
        f = self.current()
        self.render_dashboard()
        self.query_one('#evidence-badge', Button).disabled = not bool(f)
        self.query_one('#challenge', Input).disabled = not bool(f)
        self.query_one('#send', Button).disabled = not bool(f)
        for name in ('currency', 'acquisition', 'restatement'):
            self.query_one('#' + name, Button).disabled = not bool(f)
        if not f:
            run = self.run_data or {}
            detail = Text('No supported discovery yet.\n\n', style='bold #efc56e')
            detail.append('Status: ' + run.get('status', 'loading').replace('_', ' ').title() + '\n\n')
            if self.view == 'evidence':
                detail.append('Collected Sources — Not Yet Proven Evidence\n\n', style='bold #25d9e8')
                for source in run.get('sources', []):
                    detail.append(source['title'] + '\n' + source['publisher'] + ' · ' + (source.get('published') or 'Date unknown') + '\n' + source['url'] + '\n\n')
                    source_facts = [fact for fact in run.get('facts', []) if fact['source_id'] == source['id']]
                    detail.append(f'{len(source_facts)} anchored fact(s)\n', style=COLORS['grey'])
                    for fact in source_facts[:2]:
                        detail.append(f"Physical page {fact['page']}: {fact['quote']}\n\n", style=COLORS['grey'])
            else:
                detail.append('Follow the research stream for progress. F4 explains how documents become evidence.\n\n', style=COLORS['grey'])
                detail.append('\n\n'.join(plain_log(w) for w in run.get('warnings', [])[-4:]), style=COLORS['grey'])
            self.query_one("#detail", Static).update(detail)
            self.query_one('#evidence-preview', Static).update(Text('Open Evidence to inspect the collected source inventory.'))
            self.query_one('#evidence-badge', Button).label = 'No Rated Finding'
            self.query_one('#challenge', Input).placeholder = 'No finding yet · open Evidence or Research Pipeline'
            return
        self.query_one('#challenge', Input).placeholder = 'Archive question › Could currency explain this change?'
        text = Text()
        def section(title):
            text.append("\n" + title + "\n", style="bold")
        section("What We Found")
        text.append(headline(f) + "\n", style="bold")
        text.append("Status: " + plain_status(f) + "\n", style=self.finding_color(f))
        text.append("Evidence: ● " + f["strength"] + "\n", style=self.finding_color(f))
        points = series(f)
        section("Why It Matters")
        for bullet in significance(f):
            text.append("• " + bullet + "\n\n")
        section("What Could Explain It")
        for explanation, status, color in alternatives(f):
            marker = "○" if color == "grey" else "✓" if color == "green" else "◐"
            text.append(f"{marker} {explanation}\n  {status}\n\n", style=COLORS[color])
        section("What Would Change Our Mind")
        text.append(f["falsification"] + "\n")
        section("What To Do Next")
        for index, action in enumerate(f["next_steps"] or ["Inspect source passages and collect independent evidence."], 1):
            text.append(f"{index}. {action}\n\n")
        if self.view == "evidence":
            section("Source Passages")
            text.append(self.evidence_text(f, full=True))
        if self.view == "timeline":
            section("Timeline")
            for point in points:
                text.append(f"FY{point['period']}  {point['share_pct']:.2f}%\n")
            for point in f.get("timeline", []):
                text.append(f"{point['date']}  {point['description']}\n")
        self.query_one("#detail", Static).update(text)
        self.query_one("#evidence-preview", Static).update(Text(self.evidence_text(f)))
        self.query_one("#evidence-badge", Button).label = Text("● " + f["strength"] + " · Rating Criteria", style=self.finding_color(f))
        self.query_one("#challenge-result", Static).update(Text(self.challenge_text()))
        self.related_revision += 1
        self.call_after_refresh(self.update_related, self.related_revision)

    async def update_related(self, revision):
        if revision != self.related_revision:
            return
        container = self.query_one("#related-list", Vertical)
        await container.remove_children()
        if revision != self.related_revision:
            return
        current = self.current()
        points = series(current) if current else []
        related = []
        for index, other in enumerate(self.run_data["findings"]):
            other_points = series(other)
            if current and other["id"] != current["id"] and points and other_points and [p["period"] for p in points] == [p["period"] for p in other_points]:
                related.append(Button(Text(other["title"] + " · Same Revenue Mix"), id=f"related-{index}"))
        await container.mount(*(related or [Static("No related revenue-mix finding.")]))

    def challenge_text(self):
        if not self.last_challenge:
            return "Ask a question below, or choose an example. Matching passages will appear here."
        result = self.last_challenge
        text = "Your Question\n" + result["question"] + "\n\nUnresolved — matching text is evidence to review, not a verified answer.\n"
        for m in result["matches"][:4]:
            text += f"\n{m['title']} · Page {m['page']}\n{m['passage']}\n"
        if not result["matches"]:
            text += "\nNo matching passages in the local archive. Collect more evidence.\n"
        return text + "\nPress R to re-run this search after adding sources."

    def action_help(self):
        self.push_screen(InformationScreen("Help And Glossary", "Findings: ↑↓ selects; Enter opens the detail pane.\nE: full source passages · T: timeline · C: ask a question\nX: export report · L: detailed activity · B: summary · Q: quit\n\n"
            "F1: dashboard · F2: evidence · F3: timeline · F4: how research works · F5: refresh saved progress\n\n"
            "pp = percentage points. A rise from 30% to 46% is 16 pp.\nObserved = calculated change; its cause may still be unknown.\n"
            "Supported = collected evidence supports the interpretation.\nUnresolved = missing evidence or plausible alternatives remain.\nRejected = hypothesis failed the evidence review.\n\n"
            "Weak = important gaps. Moderate = some consistent evidence, with limits.\nStrong = independent support and tested alternatives, subject to stated limits.\n"
            "Select the evidence badge and press Enter for the five criteria.\n\nGrey ○ = untested; amber ◐ = unresolved; green ✓ = supported/test passed; red = rejected.\n"
            "Synthetic demo figures illustrate the software and are not real financial evidence."))

    def action_summary(self):
        run, findings = self.run_data, self.run_data["findings"]
        supported = sum(f["status"] == "supported" for f in findings)
        rejected = sum(f["status"] == "rejected" for f in findings)
        usage = run.get("usage", {})
        budget = (f"{usage.get('searches', 0)} searches; {usage.get('model_calls', 0)} model calls; {usage.get('sources', 0)} source requests"
                  if usage else "Local calculations only; no model or search budget used")
        limitation = run["warnings"][0] if run["warnings"] else ((findings[0].get("limitations") or findings[0]["counterarguments"])[0] if findings else "No evidence-backed finding established.")
        return self.push_screen(InformationScreen("Investigation Summary", f"Company: {run['company']}\n"
            + ("SYNTHETIC DEMO — NOT REAL COMPANY DATA\n\n" if run["demo"] else "Public-source research\n\n")
            + f"{len(findings)} findings · {supported} supported · {len(findings)-supported-rejected} unresolved · {rejected} rejected\n\n"
            + "Budget Used\n" + budget + "\n\nTop Limitation\n" + limitation + "\n\n↑↓ pick a finding · Enter to open · ? for help", "Open Findings"))

    def action_logs(self):
        self.push_screen(InformationScreen("Detailed Activity", "\n\n".join(e["stage"].replace('_', ' ').title() + ": " + plain_log(e["message"]) for e in self.run_data["events"])))

    def action_overview(self):
        self.view = 'overview'
        self.render_detail()

    def action_pipeline(self):
        self.push_screen(InformationScreen('How Research Works', dashboard.PIPELINE_HELP))

    def action_evidence(self):
        self.view = "evidence"
        self.render_detail()

    def action_skeptic(self):
        self.view = "skeptic"
        self.render_detail()

    def action_timeline(self):
        self.view = "timeline"
        self.render_detail()

    def action_back(self):
        table = self.query_one("#findings", DataTable)
        table.focus()
        self.update_hint(table)

    def action_focus_challenge(self):
        field = self.query_one("#challenge", Input)
        field.focus()
        self.update_hint(field)

    async def on_button_pressed(self, event: Button.Pressed):
        button_id = event.button.id or ""
        actions = {'nav-overview': self.action_overview, 'nav-evidence': self.action_evidence, 'nav-timeline': self.action_timeline,
                   'nav-pipeline': self.action_pipeline, 'quick-overview': self.action_overview, 'quick-evidence': self.action_evidence,
                   'quick-pipeline': self.action_pipeline, 'quick-export': self.action_export}
        if button_id in actions:
            actions[button_id]()
        elif button_id == 'send':
            await self.submit_challenge(self.query_one('#challenge', Input).value)
        elif button_id == "evidence-badge" and self.current():
            text = "\n\n".join(label + "\n" + reason for label, reason in evidence_criteria(self.run_data, self.current()))
            self.push_screen(InformationScreen("How The Evidence Rating Was Assigned", text))
        elif button_id in {"currency", "acquisition", "restatement"}:
            question = {"currency": "Could currency translation explain this change?", "acquisition": "Could an acquisition explain this change?",
                        "restatement": "Were these figures restated or reporting definitions changed?"}[button_id]
            self.query_one("#challenge", Input).value = question
            self.action_focus_challenge()
        elif button_id.startswith("related-"):
            self.selected = int(button_id.split('-')[1])
            self.query_one("#findings", DataTable).move_cursor(row=self.selected)
            self.last_challenge = None
            self.render_detail()
            self.action_back()

    async def on_input_submitted(self, event: Input.Submitted):
        await self.submit_challenge(event.value)

    async def action_rerun_challenge(self):
        if self.last_challenge:
            await self.submit_challenge(self.last_challenge["question"])
        else:
            self.query_one("#status", Static).update("Ask a question first; R repeats the last evidence search.")

    async def submit_challenge(self, question):
        finding = self.current()
        if not finding or not question.strip() or self.challenge_busy:
            return
        self.challenge_busy = True
        fid, rid = finding["id"], self.run_data["id"]
        field = self.query_one("#challenge", Input)
        field.disabled = True
        self.query_one("#status", Static).update("Searching the archived sources…")
        def retrieve():
            store = Store(self.root_path)
            try:
                return challenge(store, rid, fid, question)
            finally:
                store.close()
        try:
            result = await asyncio.to_thread(retrieve)
            if self.current() and self.current()["id"] == fid:
                self.last_challenge = result
                self.render_detail()
            self.query_one("#status", Static).update(f"Found {len(result['matches'])} passage(s). The explanation remains unverified.")
            self.query_one("#challenge-result", Static).scroll_visible()
        except Exception as exc:
            self.query_one("#status", Static).update(Text(f"Search failed: {exc}"))
        finally:
            self.challenge_busy = False
            field.disabled, field.value = False, ""
            self.action_back()

    def action_export(self):
        store = Store(self.root_path)
        try:
            path = export(store, self.run_data, Path(self.root_path) / "exports" / f"{self.run_data['id']}.html")
            self.exported = True
            self.render_pipeline()
            self.query_one("#status", Static).update(Text(f"Report saved: {path}"))
        finally:
            store.close()


def launch(root, run_id):
    Workbench(root, run_id).run()
