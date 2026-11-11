#!/usr/bin/env python3
"""M2 v0.3 — etap A: prototyp fazowego, atomowego wykonywania reguł.

Ograniczony prototyp / próba konstrukcyjna. Nie jest silnikiem produkcyjnym.
Nie modyfikuje oryginalnych scenariuszy M2 v0.2.
"""
from __future__ import annotations
from collections import defaultdict, Counter
from copy import deepcopy
from itertools import product
from pathlib import Path
import json
import hashlib

HERE=Path(__file__).resolve().parent
SOURCE=HERE/'M2_scenariusze_referencyjne_v02_BEZ_ZMIAN.json'
PHASES=('opening','resolve','npc','consequence')
STATUSES={
 'WYBRANE':{'WYKONANE','ODROCZONE','ZLECONE','ODRZUCONE','ZANIECHANE'},
 'ODROCZONE':{'ZLECONE','W TRAKCIE','WYKONANE','ZANIECHANE'},
 'ZLECONE':{'PRZYJĘTE','ODRZUCONE','BRAK REALIZACJI'},
 'PRZYJĘTE':{'W TRAKCIE','ODRZUCONE','BRAK REALIZACJI'},
 'W TRAKCIE':{'WYKONANE','NIESKUTECZNE','PRZERWANE'},
 'WYKONANE':{'POTWIERDZONE','NIESKUTECZNE','BRAK POTWIERDZENIA'},
 'BRAK POTWIERDZENIA':set(), 'BRAK REALIZACJI':set(),
 'ODRZUCONE':set(), 'ZANIECHANE':set(), 'NIESKUTECZNE':set(),
 'PRZERWANE':set(), 'POTWIERDZONE':set()
}

class PhaseError(Exception):
 def __init__(self, code, detail, phase=None, rule_ids=None):
  super().__init__(f'{code}: {detail}')
  self.code=code;self.detail=str(detail);self.phase=phase;self.rules=list(rule_ids or [])
 def asdict(self):return {'code':self.code,'detail':self.detail,'phase':self.phase,'rules':self.rules}

def eval_pred(c, snap, choices):
 if c is None:return True
 if 'all' in c:return all(eval_pred(q,snap,choices) for q in c['all'])
 if 'any' in c:return any(eval_pred(q,snap,choices) for q in c['any'])
 if 'not' in c:return not eval_pred(c['not'],snap,choices)
 if 'choice' in c:return choices.get(c['choice'])==c['is']
 if 'var' in c:
  a=snap['world'][c['var']]; b=c['value']
  return {'eq':lambda:a==b,'ne':lambda:a!=b,'gt':lambda:a>b,'ge':lambda:a>=b,'lt':lambda:a<b,'le':lambda:a<=b}[c['op']]()
 raise PhaseError('INVALID_PREDICATE',c)

def initial(cfg,actors):
 return {'world':deepcopy(cfg['world']), 'knowledge':{a:[{'source':'CFG','info':txt,'turn':0}] for a,txt in cfg['knowledge'].items()},'positions':{a:'start' for a in actors},'actions':{},'trace':[]}

def isolated_world(before,rule):
 """Wynik jednej propozycji wyłącznie do diagnostyki zależności warunków.
 Nie jest wykonywaniem fazy ani sposobem rozstrzygania konfliktów.
 """
 tmp=deepcopy(before)
 for op in rule['ops']:
  if op['op']=='set':tmp['world'][op['var']]=op['value']
  if op['op']=='inc':tmp['world'][op['var']]+=op['value']
 return tmp

def phase_execute(st, rules, choices, scenario, turn, phase, detect_hidden_dependency=True):
 """Snapshot -> zbieranie propozycji -> kontrola -> atomowy commit.

 Błędy nie zmieniają 'st'; wszystkie operacje są zastosowane tylko do kopii.
 Jawne polityki rozstrzygające nie występują w starych JSON: brak = zgłoszenie błędu.
 """
 snap=deepcopy(st)
 triggered=[r for r in rules if eval_pred(r.get('when'),snap,choices)]

 # Jawne reguły rozstrzygnięcia: wskazują całe działania-reguły, a nie kolejność
 # na podstawie numerów priorytetu. Nie zmieniają niezmiennego scenariusza.
 resolutions=[]
 for policy in scenario.get('conflict_rules',[]):
  if policy.get('phase')!=phase:continue
  between=policy['between']
  selected={r['id'] for r in triggered}
  if not set(between).issubset(selected):continue
  if not eval_pred(policy.get('when'),snap,choices):continue
  if policy.get('winner_rule') not in between or not policy.get('grounds'):
   raise PhaseError('INVALID_CONFLICT_POLICY',policy.get('id','?'),phase,between)
  losers=set(between)-{policy['winner_rule']}
  triggered=[r for r in triggered if r['id'] not in losers]
  resolutions.append({'policy':policy['id'],'winner':policy['winner_rule'],'losers':sorted(losers)})

 # Walidacja semantyczna: czy autor ukrył zależność reguł w obrębie fazy?
 if detect_hidden_dependency:
  for src in triggered:
   proposed=isolated_world(snap,src)
   for dst in rules:
    if dst['id']==src['id']:continue
    b=eval_pred(dst.get('when'),snap,choices)
    a=eval_pred(dst.get('when'),proposed,choices)
    if b!=a:
     raise PhaseError('SAME_PHASE_DEPENDENCY',
      f'{src["id"]} zmienia warunek {dst["id"]}: {b} -> {a}; przenieś zależne działania do kolejnych faz albo opisz jawnie pojedyncze działanie złożone.',
      phase,[src['id'],dst['id']])

 proposals=defaultdict(list)
 info=[]
 for rule in triggered:
  for op in rule['ops']:
   typ=op['op']
   if typ in ('set','inc'):
    key=('world',op['var']); proposals[key].append((typ,op['value'],rule['id']))
   elif typ=='status':
    key=('actions',op['action']); proposals[key].append(('status',op['value'],rule['id']))
   elif typ=='position':
    key=('positions',op['actor']); proposals[key].append(('position',op['value'],rule['id']))
   elif typ=='info': info.append((op['actor'],op['text'],rule['id']))
   else: raise PhaseError('UNKNOWN_OP',typ,phase,[rule['id']])

 candidate=deepcopy(st)
 for key,arr in proposals.items():
  domain,name=key; ids=[v[2] for v in arr]; types={a[0] for a in arr}
  if types=={'inc'}:
   if domain!='world':raise PhaseError('INVALID_INC',key,phase,ids)
   start=snap['world'][name]
   if type(start)!=int or any(type(v[1])!=int for v in arr):
    raise PhaseError('INVALID_INC_TYPE',name,phase,ids)
   val=start+sum(v[1] for v in arr)
  else:
   if len(arr)>1:
    raise PhaseError('WRITE_CONFLICT',f'{key}: {arr}; brak jawnego rozstrzygnięcia konfliktu',phase,ids)
   typ,val,_=arr[0]
   if typ=='status':
    old=snap['actions'].get(name)
    if old not in STATUSES:
     raise PhaseError('STATUS_UNINITIALIZED',f'{name}: pierwszy status {val}, brak jawnego powiązania działania z wariantem WYBRANE',phase,ids)
    if val not in STATUSES[old]:
     raise PhaseError('ILLEGAL_STATUS_TRANSITION',f'{name}: {old} -> {val}',phase,ids)
   elif typ=='position':
    if name not in scenario['actors']:raise PhaseError('UNKNOWN_POSITION_ACTOR',name,phase,ids)
  candidate[domain][name]=val

 for name,decl in scenario['variables'].items():
  val=candidate['world'][name]
  if decl['type']=='int' and (type(val)!=int or val<decl.get('min',-(10**12)) or val>decl.get('max',10**12)):
   raise PhaseError('RESOURCE_CONSTRAINT',f'{name}={val} poza zakresem',phase)
  if decl['type']=='bool' and type(val)!=bool:raise PhaseError('INVALID_TYPE',name,phase)
  if decl['type']=='enum' and val not in decl['enum']:raise PhaseError('INVALID_ENUM',name,phase)

 for actor,txt,rid in info:
  candidate['knowledge'][actor].append({'turn':turn+1,'info':txt,'source':rid})
 for policy in resolutions:
  candidate['trace'].append({'turn':turn+1,'phase':phase,'resolution':policy})
 for rule in triggered:
  candidate['trace'].append({'turn':turn+1,'phase':phase,'rule':rule['id'],'grounds':rule['grounds']})
 st.clear();st.update(candidate)
 return [r['id'] for r in triggered]

def iter_paths(s):
 tparts=[]
 for t in s['turns']:
  aa=sorted(t['choices'])
  tparts.append([dict(zip(aa,choices)) for choices in product(*[[v['id'] for v in t['choices'][a]] for a in aa])])
 for c in s['configurations']:
  for paths in product(*tparts):yield c,list(paths)

def single_run(s,cfg,picks):
 st=initial(cfg,s['actors'])
 for i,t in enumerate(s['turns']):
  phase_execute(st,t.get('opening',[]),{},s,i,'opening')
  for actor,choice in picks[i].items():
   if choice not in [o['id'] for o in t['choices'].get(actor,[])]:
    raise PhaseError('INVALID_CHOICE',f'{actor}={choice}')
  # Wybory nie zmieniają świata; nie zakładamy mapowania na nazwane działania w starym JSON.
  st['last_choices']=deepcopy(picks[i])
  for ph in ('resolve','npc','consequence'):
   phase_execute(st,t.get(ph,[]),picks[i],s,i,ph)
 return st

def verify_old_scenarios():
 models=json.loads(SOURCE.read_text(encoding='utf-8'))
 rows=[]; allerrs=Counter(); examples={}
 for s in models:
  errors=Counter(); tested=0;accepted=0;names=[]
  for cfg,seq in iter_paths(s):
   tested+=1
   try:
    result=single_run(s,cfg,seq)
    accepted+=1
   except PhaseError as e:
    errors[e.code]+=1;allerrs[e.code]+=1
    if e.code not in examples:
     examples[e.code]={'scenario':s['id'],'configuration':cfg['id'],'choices':seq,'diagnostic':e.asdict()}
    if len(names)<5:names.append({'configuration':cfg['id'],'choices':seq,'error':e.asdict()})
  rows.append({'scenario':s['id'],'paths':tested,'accepted':accepted,'rejected':tested-accepted,'reasons':dict(errors),'examples':names})
 return {'scope':'Konstrukcyjny test fazowego wykonania bez zmian pięciu JSON v0.2; pierwsza zgłoszona niezgodność w przebiegu',
         'sha256_original_json':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
         'scenarios':rows,'total':sum(z['paths'] for z in rows),'accepted':sum(z['accepted'] for z in rows),
         'rejected':sum(z['rejected'] for z in rows),'reasons':dict(allerrs),'first_examples':examples}

def fixture(world,rules,var_defs=None,actions=None,picks=None):
 sc={'actors':{'a':'controlled'},'variables':var_defs or {k:{'type':'int','min':0} for k in world}}
 st={'world':dict(world),'knowledge':{'a':[]},'positions':{'a':'start'},'actions':dict(actions or {}),'trace':[]}
 return sc,st, lambda:phase_execute(st,rules,picks or {},sc,0,'resolve')

def rule(rid,when,ops):return {'id':rid,'when':when,'ops':ops,'grounds':['ASM-TEST']}

def verify_synthetic():
 results=[]
 def testcase(name, fn):
  try:fn();results.append({'case':name,'passed':True})
  except AssertionError as e:results.append({'case':name,'passed':False,'failure':str(e)})
  except Exception as e:results.append({'case':name,'passed':False,'failure':repr(e)})
 def expect(code,fn,st):
  before=deepcopy(st)
  try:fn()
  except PhaseError as e:
   assert e.code==code,(e.code,code)
   assert st==before,'Błąd częściowego zatwierdzenia stanu'
  else:raise AssertionError('Nie wykryto '+code)

 def inc_sum():
  r=[rule('A',None,[{'op':'inc','var':'stock','value':-1}]),rule('B',None,[{'op':'inc','var':'stock','value':-1}])]
  sc,st,fn=fixture({'stock':3},r);fn();assert st['world']['stock']==1
  sc2,st2,fn2=fixture({'stock':3},list(reversed(r)));fn2();assert st2['world']=={'stock':1}
 testcase('A01_dwa_ubytki_agregowane_i_kolejnosc_nieistotna',inc_sum)
 def excessive():
  sc,st,fn=fixture({'stock':1},[rule('A',None,[{'op':'inc','var':'stock','value':-1}]),rule('B',None,[{'op':'inc','var':'stock','value':-1}])]);expect('RESOURCE_CONSTRAINT',fn,st)
 testcase('A02_wspolny_ubytk_narusza_ograniczenie_i_rollback',excessive)
 def set_collision():
  sc,st,fn=fixture({'x':0},[rule('A',None,[{'op':'set','var':'x','value':1}]),rule('B',None,[{'op':'set','var':'x','value':2}])]);expect('WRITE_CONFLICT',fn,st)
 testcase('A03_konflikt_nadpisan_odrzucony_i_rollback',set_collision)
 def status_illegal():
  sc,st,fn=fixture({'x':0},[rule('A',None,[{'op':'status','action':'repair','value':'POTWIERDZONE'}])],actions={'repair':'WYBRANE'});expect('ILLEGAL_STATUS_TRANSITION',fn,st)
 testcase('A04_niedozwolony_przeskok_statusu_i_rollback',status_illegal)
 def status_valid():
  sc,st,fn=fixture({'x':0},[rule('A',None,[{'op':'status','action':'repair','value':'ZLECONE'}])],actions={'repair':'WYBRANE'});fn();assert st['actions']['repair']=='ZLECONE'
 testcase('A05_dozwolone_przejscie_statusu',status_valid)
 def hidden_dependency():
  sc,st,fn=fixture({'x':0,'y':0},[
   rule('A',None,[{'op':'set','var':'x','value':1}]),
   rule('B',{'var':'x','op':'eq','value':1},[{'op':'set','var':'y','value':1}])]);expect('SAME_PHASE_DEPENDENCY',fn,st)
 testcase('A06_zalezna_regula_w_jednej_fazie_odrzucona',hidden_dependency)
 def after_phase():
  sc,st,fn=fixture({'x':0,'y':0},[rule('A',None,[{'op':'set','var':'x','value':1}])]);fn()
  phase_execute(st,[rule('B',{'var':'x','op':'eq','value':1},[{'op':'set','var':'y','value':1}])],{},sc,0,'npc')
  assert st['world']=={'x':1,'y':1}
 testcase('A07_zaleznosc_miedzy_fazami_jest_jawna_i_wykonywalna',after_phase)
 def position_atomic():
  r=[rule('P',None,[{'op':'position','actor':'a','value':'node-2'},{'op':'set','var':'x','value':1}])]
  sc,st,fn=fixture({'x':0},r);fn();assert st['positions']['a']=='node-2' and st['world']['x']==1
 testcase('A08_pozycja_i_swiat_zatwierdzane_atomowo',position_atomic)
 def position_conflict():
  r=[rule('P',None,[{'op':'position','actor':'a','value':'node-2'}]),rule('Q',None,[{'op':'position','actor':'a','value':'node-3'}])]
  sc,st,fn=fixture({'x':0},r);expect('WRITE_CONFLICT',fn,st)
 testcase('A09_konflikt_pozycji_odrzucony',position_conflict)
 def uninitialized():
  sc,st,fn=fixture({'x':0},[rule('A',None,[{'op':'status','action':'repair','value':'WYKONANE'}])]);expect('STATUS_UNINITIALIZED',fn,st)
 testcase('A10_niepowiazany_status_odrzucony',uninitialized)
 def double_status():
  sc,st,fn=fixture({'x':0},[rule('A',None,[{'op':'status','action':'repair','value':'ODRZUCONE'}]),rule('B',None,[{'op':'status','action':'repair','value':'WYKONANE'}])],actions={'repair':'WYBRANE'});expect('WRITE_CONFLICT',fn,st)
 testcase('A11_podwojny_status_tego_samego_dzialania',double_status)
 def declared_override():
  r=[rule('A',None,[{'op':'set','var':'x','value':1}]),rule('B',None,[{'op':'set','var':'x','value':2}])]
  sc,st,fn=fixture({'x':0},r)
  sc['conflict_rules']=[{'id':'CP-1','phase':'resolve','between':['A','B'],'winner_rule':'A','grounds':['ASM-TEST']}]
  fn();assert st['world']['x']==1
  assert st['trace'][0]['resolution']['policy']=='CP-1'
 testcase('A12_jawna_regula_rozstrzygniecia_zamiast_numerycznego_priorytetu',declared_override)
 def declared_resource():
  r=[rule('A',None,[{'op':'inc','var':'stock','value':-1}]),rule('B',None,[{'op':'inc','var':'stock','value':-1}])]
  sc,st,fn=fixture({'stock':1},r)
  sc['conflict_rules']=[{'id':'CP-LOW','phase':'resolve','between':['A','B'],'winner_rule':'A','when':{'var':'stock','op':'lt','value':2},'grounds':['ASM-TEST']}]
  fn();assert st['world']['stock']==0
  sc2,st2,fn2=fixture({'stock':2},r);sc2['conflict_rules']=sc['conflict_rules']
  fn2();assert st2['world']['stock']==0
 testcase('A13_warunkowy_przydzial_ograniczonego_zasobu',declared_resource)
 return {'tests':results,'passed':sum(x['passed'] for x in results),'total':len(results)}

if __name__=='__main__':
 d=verify_old_scenarios();p=verify_synthetic()
 (HERE/'M2_EtapA_raport_maszynowy.json').write_text(json.dumps({'regression':d,'synthetic':p},ensure_ascii=False,indent=2),encoding='utf-8')
 print('OLD JSON SHA256',d['sha256_original_json'])
 print('REGRESSION accepted / rejected',d['accepted'],'/',d['rejected'])
 for v in d['scenarios']:print(v['scenario'],v['accepted'],'/',v['paths'],'REASONS',v['reasons'])
 print('SYNTHETIC',p['passed'],'/',p['total'])
 if p['passed']!=p['total']:raise SystemExit(1)
