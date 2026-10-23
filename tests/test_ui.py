import asyncio

from textual.widgets import Button, Collapsible, DataTable, Input, Static

from pharma_scope.demo import seed_demo
from pharma_scope.presentation import alternatives, evidence_criteria, headline, significance
from pharma_scope.store import Store
from pharma_scope.tui import InformationScreen, Workbench


def test_plain_language_and_no_invented_test_results(tmp_path):
    store = Store(tmp_path / "data")
    try:
        run = seed_demo(store)
        india = next(f for f in run["findings"] if f["title"].startswith("India:"))
        assert "30% → 46%" in headline(india)
        assert len(significance(india)) >= 3
        assert len(evidence_criteria(run, india)) == 5
        assert all(status == "Untested" for _, status, _ in alternatives(india)[:4])
    finally:
        store.close()


def test_summary_help_rating_related_chips_and_rerun(tmp_path):
    store = Store(tmp_path / "data")
    try:
        run = seed_demo(store)

        async def scenario():
            app = Workbench(store.root, run["id"])
            async with app.run_test(size=(140, 48)) as pilot:
                await pilot.pause(0.1)
                assert isinstance(app.screen, InformationScreen)
                assert "unresolved" in str(app.screen.query_one("#dialog-body", Static).render())
                await pilot.press("enter")
                await pilot.pause()
                assert not isinstance(app.screen, InformationScreen)
                body = str(app.query_one("#detail", Static).render())
                for section in ["What We Found", "Why It Matters", "What Could Explain It", "What Would Change Our Mind", "What To Do Next"]:
                    assert section in body
                assert "Verify ○" in str(app.query_one("#pipeline", Static).render())
                assert "SYNTHETIC DEMO" in str(app.query_one("#banner", Static).render())
                app.action_help()
                await pilot.pause()
                assert "pp = percentage points" in str(app.screen.query_one("#dialog-body", Static).render())
                await pilot.press("escape")
                app.query_one("#evidence-badge", Button).focus()
                await pilot.press("enter")
                await pilot.pause()
                assert "Comparability" in str(app.screen.query_one("#dialog-body", Static).render())
                await pilot.press("escape")
                # Expand related findings and activate a real link to the other row.
                app.query_one("#related", Collapsible).collapsed = False
                await pilot.pause()
                related = app.query("#related-list Button").first(Button)
                index = int(related.id.split('-')[1])
                related.press()
                for _ in range(30):
                    await pilot.pause(0.02)
                    if app.selected == index:
                        break
                assert app.selected == index, (app.query_one("#findings", DataTable).cursor_row, related.display, type(app.screen).__name__)
                app.query_one("#currency", Button).press()
                for _ in range(30):
                    await pilot.pause(0.02)
                    if isinstance(app.focused, Input) and "Esc: Back" in str(app.query_one("#keyhint", Static).render()):
                        break
                assert isinstance(app.focused, Input)
                assert "currency" in app.query_one("#challenge", Input).value
                assert "Esc: Back" in str(app.query_one("#keyhint", Static).render())
                await pilot.press("enter")
                for _ in range(40):
                    await pilot.pause(0.02)
                    if app.last_challenge:
                        break
                assert app.last_challenge
                assert "Your Question" in str(app.query_one("#challenge-result", Static).render())
                before = len(store.challenges(run["id"]))
                await app.action_rerun_challenge()
                assert len(store.challenges(run["id"])) == before + 1
                await pilot.resize_terminal(85, 30)
                await pilot.pause()
                assert app.query_one("#challenge", Input).region.width > 0

        asyncio.run(scenario())
    finally:
        store.close()
