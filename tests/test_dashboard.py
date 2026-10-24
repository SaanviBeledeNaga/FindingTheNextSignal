import asyncio

from textual.widgets import Button, Input, Static

from pharma_scope.dashboard import cards, chart
from pharma_scope.demo import seed_demo
from pharma_scope.store import Store
from pharma_scope.tui import Workbench, InformationScreen


def test_empty_financial_snapshot_has_no_invented_series():
    text = chart({'facts': []}, None).plain
    assert 'No comparable financial series' in text
    assert '█' not in text and 'bullish' not in text.casefold()


def test_conflicting_values_for_same_period_withhold_chart():
    def fact(period, value):
        return {'id': period + value, 'fiscal_period': period, 'value': value, 'metric': 'Revenue',
                'entity': 'Example', 'unit': 'million', 'currency': 'INR', 'basis': 'consolidated', 'definition': 'operations'}
    run = {'facts': [fact('FY2025', '100'), fact('FY2025', '200'), fact('FY2024', '80')]}
    assert 'Conflicting figures: chart withheld' in chart(run, None).plain


def test_demo_dashboard_counts_actual_inputs_without_claiming_support(tmp_path):
    store = Store(tmp_path / 'data')
    try:
        run = seed_demo(store)
        values = cards(run)
        assert values[0][1] == '5' and values[1][1] == '20'
        assert values[2][1] == '2' and '0 supported' in values[2][2]
        assert 'FY2021' in chart(run, run['findings'][0]).plain
        compact = chart(run, run['findings'][0], compact=True).plain
        assert 'FY2021' in compact and 'FY2025' in compact and 'FY2022' not in compact
    finally:
        store.close()


def test_reference_layout_pipeline_navigation_and_small_terminal(tmp_path):
    store = Store(tmp_path / 'data')
    try:
        run = seed_demo(store)
        async def scenario():
            app = Workbench(store.root, run['id'], show_summary=False)
            async with app.run_test(size=(140, 48)) as pilot:
                await pilot.pause()
                left, center, right = (app.query_one('#' + name) for name in ('left', 'right', 'intel'))
                assert left.region.right <= center.region.x and center.region.right <= right.region.x
                assert '20' in str(app.query_one('#metric-1', Static).render())
                await pilot.press('f4')
                await pilot.pause()
                assert isinstance(app.screen, InformationScreen)
                help_text = str(app.screen.query_one('#dialog-body', Static).render())
                assert 'BeautifulSoup' in help_text and 'PyMuPDF' in help_text and 'Search snippets are leads' in help_text
                await pilot.press('escape')
                await pilot.resize_terminal(85, 30)
                await pilot.pause()
                assert app.screen.has_class('compact')
                assert not app.query_one('#intel').display
                assert app.query_one('#challenge', Input).region.width > 0
        asyncio.run(scenario())
    finally:
        store.close()


def test_dashboard_refreshes_checkpoint_not_stale_run_export(tmp_path):
    store = Store(tmp_path / 'data')
    try:
        run = seed_demo(store)
        run.update(kind='research', facts=[], findings=[], status='running', usage={'model_calls': 0}, parameters={'model_calls': 20})
        store.save_run(run)
        state = {**run, 'source_ids': [s['id'] for s in run['sources']], 'limits': run['parameters'], 'profile': {}, 'plan': {}}
        store.checkpoint(state)
        async def scenario():
            app = Workbench(store.root, run['id'], show_summary=False)
            async with app.run_test(size=(140, 48)) as pilot:
                await pilot.pause()
                assert app.query_one('#challenge', Input).disabled
                assert 'No comparable financial series' in str(app.query_one('#snapshot', Static).render())
                state['usage'] = {'model_calls': 4}
                state['events'].append({'at': '2026-10-24T00:00:00+00:00', 'stage': 'extract', 'message': 'Testing current saved progress'})
                store.checkpoint(state)
                await pilot.pause(2.2)
                assert app.run_data['usage']['model_calls'] == 4
                assert '4 / 20' in str(app.query_one('#metric-3', Static).render())
                assert store.run(run['id'])['usage']['model_calls'] == 0
                await pilot.press('e')
                assert 'Collected Sources' in str(app.query_one('#detail', Static).render())
        asyncio.run(scenario())
    finally:
        store.close()
