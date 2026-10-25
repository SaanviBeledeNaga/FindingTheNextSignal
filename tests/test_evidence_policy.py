from copy import deepcopy
import pytest
from pharma_scope.agent import ResearchAgent, Limits
from pharma_scope.evidence import anchored_identity, calculation, extract_facts, origin
from pharma_scope.research_policy import publication_view, period_allowed, source_issue
from pharma_scope.store import Store
from pharma_scope.webtools import WebTools,disclosure_score
from test_agent import FakeModel,FakeWeb
from test_research_quality import table_fact,TABLE


def test_swapped_year_columns_do_not_pass_quote_matching():
    row = table_fact()
    row['fiscal_period'] = 'FY2024'
    accepted, errors = extract_facts({'id':'source','pages':[TABLE]},[row])
    assert not accepted and any('year-column' in error for error in errors)


def test_report_title_and_one_year_do_not_assign_two_table_values():
    row=table_fact()
    row['context_evidence']=[c for c in row['context_evidence'] if 'Year ended' not in c['quote']]
    row['context_evidence'].append({'page':1,'quote':'Year ended March 31, 2025'})
    valid, errors=extract_facts({'id':'s','pages':[TABLE]},[row])
    assert not valid and any('unambiguous year-column' in e for e in errors)


def test_directory_is_never_the_official_issuer_domain():
    text = 'Example Pharma Limited develops medicines. EXAMPLE'
    profile = {'name':'Example Pharma Limited','symbol':'EXAMPLE','official_domain':'annualreports.com',
               'uncertainty':[],'identity_evidence':[{'url':'https://www.annualreports.com/Company/example','quote':text}]}
    assert anchored_identity(profile,'Example',[{'url':profile['identity_evidence'][0]['url'],'pages':[text]}])['official_domain'] == ''


def test_underscored_report_year_is_used_for_recency():
    old = {'title':'View Annual Report','url':'https://www.annualreports.com/HostedData/NYSE_EXAMPLE_2016.pdf'}
    new = {**old,'url':old['url'].replace('2016','2025')}
    assert disclosure_score(new)>disclosure_score(old)


def test_directory_links_discover_full_pdf_and_actual_issuer_site(tmp_path):
    page = tmp_path/'index.html'
    page.write_text('<a href="https://issuer.example">Visit website</a><a href="https://exchange.example/2025.pdf">View PDF</a>')
    class Archive:
        def metadata(self,sid):return {'original_archive':str(page)}
    sources = [{'id':'s','url':'https://www.annualreports.com/Company/example','title':'Example annual reports'}]
    tools=WebTools()
    assert tools.issuer_links(Archive(),sources)[0]['url']=='https://issuer.example'
    assert tools.report_links(Archive(),sources,'')[0]['url']=='https://exchange.example/2025.pdf'


def test_stale_financial_periods_are_not_current_evidence():
    assert not period_allowed({'kind':'financial','value':'20','fiscal_period':'FY2016'},'2026-10-24',5)
    assert period_allowed({'kind':'financial','value':'20','fiscal_period':'FY2021'},'2026-10-24',5)


def test_document_preview_is_not_a_full_source():
    assert source_issue({'url':'https://www.scribd.com/document/1','pages':['Example Pharma Limited annual report'],'archived':'preview.txt'}, {'name':'Example Pharma Limited'})


def test_two_fda_subdomains_do_not_become_two_independent_agencies():
    a={'url':'https://www.fda.gov/report','publisher':'FDA','source_kind':'regulator'}
    b={**a,'url':'https://www.accessdata.fda.gov/inspection'}
    assert origin(a,{}) == origin(b,{})


def test_duplicate_fact_calculation_and_legacy_claim_are_withheld(tmp_path):
    store=Store(tmp_path/'data')
    try:
        run=ResearchAgent(store,FakeModel(),FakeWeb(),Limits(seconds=120)).run('EXAMPLE')
        assert run['findings']
        calc=run['findings'][0]['calculations'][0]
        calc['inputs']=[calc['inputs'][0]]*2
        with pytest.raises(ValueError):calculation(calc,{f['id']:f for f in run['facts']})
        clean=publication_view(run)
        assert not clean['findings'] and clean['withheld_findings']
        assert run['findings']  # Read-time policy does not erase historical records.
    finally:store.close()


def test_margin_can_compare_profit_and_revenue_definitions():
    a={'entity':'Example','value':'10','currency':'INR','basis':'consolidated','definition':'net profit','metric':'net profit','unit':'crore','fiscal_period':'FY2025'}
    b={**a,'value':'100','metric':'revenue','definition':'revenue from operations'}
    assert calculation({'inputs':['a','b'],'operation':'margin_pct','years':0},{'a':a,'b':b})['result']=='10.000000'
