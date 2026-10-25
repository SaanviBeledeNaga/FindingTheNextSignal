import json
from pathlib import Path

import pytest
from jsonschema import ValidationError, validate

from pharma_scope import schemas
from pharma_scope.agent import ResearchAgent
from pharma_scope.evidence import extract_facts
from pharma_scope.evidence import identity_matches
from pharma_scope.eligibility import check, SNAPSHOT
from pharma_scope.ingest import ingest, norm, read_pages
from pharma_scope.store import Store
from test_agent import fact, FakeModel, FakeWeb
from test_research_quality import TABLE, table_fact


def test_new_extraction_schema_requires_dedicated_column_header():
    row=fact('A sufficiently long qualitative source passage.')
    row.pop('column_header')
    with pytest.raises(ValidationError):
        validate(row,schemas.FACT)


def test_explicit_column_header_passes_and_swapped_value_fails():
    row=table_fact()
    row['column_header']={'page':1,'quote':'Year ended March 31, 2025     Year ended March 31, 2024'}
    row['context_evidence']=[c for c in row['context_evidence'] if 'Year ended' not in c['quote']]
    valid,errors=extract_facts({'id':'s','pages':[TABLE]},[row])
    assert not errors and valid[0]['column_header'] in valid[0]['context_evidence']
    row['fiscal_period']='FY2024'
    assert not extract_facts({'id':'s','pages':[TABLE]},[row])[0]


def test_report_title_cannot_replace_column_header():
    row=table_fact()
    row['column_header']={'page':1,'quote':'Year ended March 31, 2025'}
    assert not extract_facts({'id':'s','pages':[TABLE]},[row])[0]


def test_financial_statement_layout_survives_keyword_dense_pages(tmp_path):
    import pymupdf
    path=tmp_path/'report.pdf'
    with pymupdf.open() as doc:
        for _ in range(10):
            page=doc.new_page();page.insert_text((40,50),'geographic segment revenue from operations\n'*12)
        page=doc.new_page()
        page.insert_text((40,50),'Consolidated Statement of Profit and Loss')
        # Reverse PDF creation order to reproduce reordered native text blocks.
        page.insert_text((450,100),'2024');page.insert_text((350,100),'2025')
        page.insert_text((40,130),'Revenue');page.insert_text((350,130),'525');page.insert_text((450,130),'480')
        doc.save(path)
    pages=read_pages(path,fast=True)
    assert any('2025' in line and '2024' in line and line.index('2025')<line.index('2024') for line in pages[-1].splitlines())
    store=Store(tmp_path/'db')
    try:
        sid=ingest(store,path,'EXAMPLE','Report','Example','2025-06-01')
        store.db.execute('UPDATE sources SET pages=? WHERE id=?',(json.dumps(['old unusable text']),sid));store.db.commit()
        assert ingest(store,path,'EXAMPLE','Report','Example','2025-06-01',parse_timeout=12)==sid
        source=next(s for s in store.sources() if s['id']==sid)
        assert len(source['pages'])==11
        agent=ResearchAgent(store,model=object(),web=object())
        chosen=agent.selected_pages(source)
        assert next(p for p in chosen if p['page']==11)['column_header_candidates']
        assert store.metadata(sid)['text_parser']=='financial-layout-2'
    finally:store.close()


def test_official_snapshot_contains_fifty_unique_symbols():
    snapshot=json.loads(SNAPSHOT.read_text(encoding='utf-8'))
    assert len(snapshot['members'])==len({r['Symbol'] for r in snapshot['members']})==50
    assert snapshot['source_url'].startswith('https://nsearchives.nseindia.com/')


def test_eligibility_distinguishes_track_members_other_sectors_and_extended_universe():
    assert check({'name':'Cipla Limited','symbol':'CIPLA'})['track_d'] is True
    assert check({'name':'Apollo Hospitals Enterprise Limited','symbol':'APOLLOHOSP'})['track_d'] is True
    assert check({'name':'Tata Consultancy Services Limited','symbol':'TCS'})['track_d'] is False
    assert check({'name':'Lupin Limited','symbol':'LUPIN'})['member'] is False
    assert check({'name':'Cipla Limited','symbol':'TCS'})['symbol']=='CIPLA'
    assert 'Static' in check({'name':'Cipla Limited'})['membership_basis']


def test_distinctive_requested_words_prevent_apollo_entity_substitution():
    assert not identity_matches('Apollo Hospitals Enterprise',{'name':'Apollo Endosurgery Inc.','symbol':'APEN'})
    assert identity_matches('Apollo Hospitals Enterprise',{'name':'Apollo Hospitals Enterprise Limited','symbol':'APOLLOHOSP'})
    assert identity_matches("Dr. Reddy's Laboratories",{'name':"Dr. Reddy’s Laboratories Limited",'symbol':'DRREDDY'})


def test_resume_restarts_mismatched_identity_instead_of_researching_wrong_company(tmp_path):
    store=Store(tmp_path/'db')
    try:
        run=ResearchAgent(store,FakeModel(),FakeWeb()).run('EXAMPLE')
        state=store.agent_state(run['id'])
        state['profile']['name']='Different Pharma Limited'
        state['profile']['symbol']='OTHER'
        store.checkpoint(state)
        resumed=ResearchAgent(store,FakeModel(),FakeWeb()).run(resume=run['id'])
        assert resumed['profile']['name']=='Example Pharma Limited'
        assert any('restarted identity' in w for w in resumed['warnings'])
    finally:store.close()
