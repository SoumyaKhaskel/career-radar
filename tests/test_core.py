import json
from app.experience import classify_experience
from app.collectors import parse_ats_url, adzuna_search_url, adzuna_params, adzuna_credentials, parse_adzuna_payload
from app.db import init, upsert_job, connect
from app.matching import score_job

def test_experience_examples():
    for text in ['Fresh graduate','Graduate programme','Entry level','Junior','0–1 years','1–2 years','1–3 years','2–3 years','Up to three years','No experience required']:
        assert classify_experience(text)[0]=='confirmed'
    assert classify_experience('3+ years')[0]=='needs_review'
    assert classify_experience('4+ years')[0]=='excluded'
    assert classify_experience('4–6 years')[0]=='excluded'
    assert classify_experience('')[0]=='needs_review'

def test_dedupe_and_update(tmp_path):
    path=tmp_path/'db.sqlite3';init(path)
    a={'source':'Greenhouse','source_id':'1','title':'SOC Analyst','company':'Acme','location':'India','url':'https://jobs.example/1'}
    b={**a,'source':'Lever','source_id':'2','url':'https://jobs.other/duplicate'}
    assert upsert_job(a,path) is True
    assert upsert_job(b,path) is False
    with connect(path) as c:
        row=c.execute('select * from jobs').fetchone();assert len(json.loads(row['sources']))==2

def test_invalid_fields_and_scoring():
    assert parse_ats_url('https://boards.greenhouse.io/example')[0]=='Greenhouse'
    job={'title':'Junior Security Analyst','description':'Python, SIEM; 0–2 years experience','location':'India'}
    result=score_job(job,{'preferred_titles':['Security Analyst'],'skills':['Python','Splunk'],'max_experience':3,'target_locations':['India']})
    assert 0<=result['score']<=100 and 'Python' in result['matching_skills'] and 'Splunk' in result['uncertain_skills']

def test_default_india_locations(tmp_path):
    from app.db import setting
    path=tmp_path/'locations.sqlite3';init(path)
    profile=json.loads(setting('profile','{}',path))
    assert profile['target_locations']==['India','Kolkata','Hyderabad','Bengaluru','Bangalore']

def test_adzuna_mocked_india_response():
    assert adzuna_search_url()=='https://api.adzuna.com/v1/api/jobs/in/search/1'
    params=adzuna_params('SOC Analyst','test-id','test-secret')
    assert params['what']=='SOC Analyst' and params['app_key']=='test-secret' and params['results_per_page']==20
    payload={'results':[{'id':'42','title':'SOC Analyst','company':{'display_name':'Example Co'},'location':{'display_name':'Kolkata, India'},'description':'Entry level security role','redirect_url':'https://www.adzuna.in/details/42','created':'2026-10-01T09:00:00Z'}]}
    jobs=parse_adzuna_payload(payload)
    assert jobs[0]['source']=='Adzuna' and jobs[0]['country']=='India' and jobs[0]['company']=='Example Co'

def test_adzuna_missing_credentials_is_clear():
    import pytest
    with pytest.raises(RuntimeError,match='ADZUNA_APP_ID'):
        adzuna_credentials('','')
