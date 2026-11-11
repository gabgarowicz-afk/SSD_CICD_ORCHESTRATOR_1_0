#!/usr/bin/env python3
"""M2 v0.3 -- korekta etapu A przed B: wersja konstrukcyjna, nie produkcyjna.

Fazy korzystają z jednej migawki. Zmienna jest aktualizowana atomowo.
Mapowanie wyborów -> nazwanych działań przechowuje odrębny adapter v0.2;
oryginalnych pięciu plików scenariusza nie modyfikujemy.
"""
import json, random
from pathlib import Path
from copy import deepcopy
from collections import Counter, defaultdict, deque
from itertools import combinations
import m2_fazowy_etapA as old

ROOT=Path(__file__).resolve().parent
PHASES=old.PHASES
ERR=old.PhaseError


RESULT_STATES = {'POTWIERDZONE', 'NIESKUTECZNE'}


def status_path(a, b, via=None):
    """Legalna ścieżka bez niejawnych skrótów do wyniku.

    Przejścia wieloetapowe o więcej niż jednej ścieżce wymagają jawnego `via`.
    Stany wynikowe nie mogą być pośrednim krokiem ścieżki.
    Odrębne dowody wyników są weryfikowane przez do_phase.
    """
    if a not in old.STATUSES: raise ERR('STATUS_UNINITIALIZED',f'{a} nie jest zdefiniowany')
    if b not in old.STATUSES: raise ERR('ILLEGAL_STATUS_TRANSITION',f'{b}: nieznany status')
    if a == b: raise ERR('NO_STATUS_CHANGE',f'{a} -> {b}')
    if b in RESULT_STATES and a not in ({'WYKONANE'} if b=='POTWIERDZONE' else {'WYKONANE','W TRAKCIE'}):
        raise ERR('RESULT_REQUIRES_PRIOR_ACTION',f'{a} -> {b}')
    if via is not None:
        if not isinstance(via,list) or any(not isinstance(x,str) for x in via):
            raise ERR('INVALID_STATUS_PATH','pole via musi być listą statusów pośrednich')
        chain=via+[b]
        last=a
        for pos,nxt in enumerate(chain):
            if nxt not in old.STATUSES[last]:
                raise ERR('ILLEGAL_STATUS_TRANSITION',f'{last} -> {nxt}')
            if pos < len(chain)-1 and nxt in RESULT_STATES:
                raise ERR('INVALID_STATUS_PATH','wynik działania nie może być stanem pośrednim')
            last=nxt
        return chain
    if b in old.STATUSES[a]: return [b]  # jawnie wybrane pojedyncze przejście
    paths=[]
    def walk(curr,path):
        if len(paths)>1:return
        for nxt in sorted(old.STATUSES[curr]):
            if nxt in path or nxt in RESULT_STATES and nxt!=b:continue
            if nxt==b: paths.append(path+[nxt])
            else: walk(nxt,path+[nxt])
    walk(a,[a])
    if not paths: raise ERR('ILLEGAL_STATUS_TRANSITION',f'{a} -> {b}: brak dozwolonej ścieżki')
    if len(paths)>1: raise ERR('AMBIGUOUS_STATUS_PATH',f'{a} -> {b}: wskaż listę via')
    return paths[0][1:]


def refs_in_pred(c):
    if not isinstance(c,dict): return set()
    out={c['var']} if 'var' in c else set()
    for k in ('all','any'):
        for q in c.get(k,[]): out|=refs_in_pred(q)
    if 'not' in c: out|=refs_in_pred(c['not'])
    return out


def static_warnings(s):
    """Ostrzeżenia nie przerywają testów. Każda para reguł liczona raz."""
    findings=[]
    for n,t in enumerate(s['turns'],1):
        for phase in PHASES:
            rules=t.get(phase,[])
            for src in rules:
                writes={op['var'] for op in src['ops'] if op['op'] in ('inc','set')}
                for dst in rules:
                    if src['id']==dst['id']: continue
                    shared=sorted(writes & refs_in_pred(dst.get('when')))
                    if shared:
                        findings.append({'kind':'DEPENDENCY_SAME_PHASE','scenario':s['id'],
                             'turn':n,'phase':phase,'source_rule':src['id'],
                             'dependent_rule':dst['id'],'variables':shared,
                             'severity':'warning (not a runtime error)'})
    return sorted(findings,key=lambda f:(f['scenario'],f['turn'],f['phase'],f['source_rule'],f['dependent_rule']))


def actor_actions(choice_map,sid,turn,choices):
    maps=choice_map.get(sid,{}).get(str(turn),{})
    new={}
    for actor,selected in choices.items():
        act=maps.get(actor,{}).get(selected)
        if act: new[actor]=act
    return new


def do_phase(st,rules,choices,scenario,turn,phase,order=None):
    """Wszystkie predykaty oceniane na tym samym snapshot; status jest pojedynczą wartością."""
    snap=deepcopy(st)
    if order is not None:
        rules=list(rules);order.shuffle(rules)
    triggered=[r for r in rules if old.eval_pred(r.get('when'),snap,choices)]
    resolutions=[]
    for policy in scenario.get('conflict_rules',[]):
        if policy.get('phase')!=phase: continue
        between=policy['between']; selected={r['id'] for r in triggered}
        if not set(between).issubset(selected) or not old.eval_pred(policy.get('when'),snap,choices):continue
        if policy.get('winner_rule') not in between or not policy.get('grounds'):
            raise ERR('INVALID_CONFLICT_POLICY',policy.get('id','?'),phase,between)
        losers=set(between)-{policy['winner_rule']}
        triggered=[r for r in triggered if r['id'] not in losers]
        resolutions.append({'policy':policy['id'],'winner':policy['winner_rule'],'losers':sorted(losers)})
    proposals=defaultdict(list); info=[]
    for rule in triggered:
        for op in rule['ops']:
            kind=op['op']
            if kind in ('inc','set'):
                proposals[('world',op['var'])].append((kind,op['value'],rule['id']))
            elif kind=='status':
                proposals[('actions',op['action'])].append(('status',op['value'],rule['id'],op,rule))
            elif kind=='position':
                proposals[('positions',op['actor'])].append(('position',op['value'],rule['id']))
            elif kind=='info': info.append((op['actor'],op['text'],rule['id']))
            else: raise ERR('UNKNOWN_OP',kind,phase,[rule['id']])
    candidate=deepcopy(st); transitions=[]
    for (domain,name),arr in sorted(proposals.items()):
        types={a[0] for a in arr}
        ids=sorted(a[2] for a in arr)
        if types=={'inc'}:
            start=snap['world'][name]
            if type(start)!=int or any(type(a[1])!=int for a in arr):
                raise ERR('INVALID_INC_TYPE',name,phase,ids)
            val=start+sum(a[1] for a in arr)
        else:
            if len(arr)>1: raise ERR('WRITE_CONFLICT',f'{domain}.{name}: {arr}',phase,ids)
            kind,val,_=arr[0][:3]
            if kind=='status':
                op,rule=arr[0][3],arr[0][4]
                prev=snap['actions'].get(name)
                if prev is None: raise ERR('STATUS_UNINITIALIZED',f'{name}: brak powiązanego wyboru',phase,ids)
                # Status wynikowy nie może powstać w tej samej fazie co wykonanie.
                # Pochodzi wyłącznie z osobnej reguły, z niezależnym źródłem.
                if val in RESULT_STATES:
                    if prev not in ({'WYKONANE'} if val=='POTWIERDZONE' else {'WYKONANE','W TRAKCIE'}):
                        raise ERR('RESULT_REQUIRES_PRIOR_ACTION',f'{name}: {prev} -> {val}; wymagany wcześniejszy etap wykonania',phase,ids)
                    source=op.get('evidence_source',rule.get('evidence_source'))
                    owner=snap.get('action_meta',{}).get(name,{}).get('selected_by')
                    actor=rule.get('actor')
                    if snap.get('action_meta',{}).get(name,{}).get('executed_at')=={'turn':turn+1,'phase':phase}:
                        raise ERR('RESULT_SAME_PHASE_AS_EXECUTION',f'{name}: wynik nie może powstać w tej samej fazie',phase,ids)
                    if not source or not actor or source!=actor:
                        raise ERR('RESULT_REQUIRES_EVIDENCE',f'{name}: podaj evidence_source tożsame z niezależnym aktorem reguły',phase,ids)
                    if owner is None or source==owner:
                        raise ERR('RESULT_SOURCE_NOT_INDEPENDENT',f'{name}: źródło {source} jest wybierającym lub brak właściciela',phase,ids)
                    if not rule.get('grounds'):
                        raise ERR('RESULT_REQUIRES_GROUND',f'{name}: brak jawnej podstawy potwierdzenia',phase,ids)
                try: chain=status_path(prev,val,op.get('via'))
                except ERR as e: raise ERR(e.code,f'{name}: {e.detail}',phase,ids) from e
                # Żadna ścieżka wieloetapowa nie może doprowadzić do wyniku.
                if val in RESULT_STATES and len(chain)!=1:
                    raise ERR('RESULT_TRANSITION_NOT_SKIPPABLE',f'{name}: {prev} -> {val}',phase,ids)
                before=prev
                for after in chain:
                    transitions.append({'action':name,'from':before,'to':after,'trigger_rule':ids[0],
                                        'intermediate':after!=val})
                    before=after
            elif kind=='position' and name not in scenario['actors']:
                raise ERR('UNKNOWN_POSITION_ACTOR',name,phase,ids)
        candidate[domain][name]=val
    for name,decl in scenario['variables'].items():
        val=candidate['world'][name]
        if decl['type']=='int' and (type(val)!=int or val<decl.get('min',-10**12) or val>decl.get('max',10**12)):
            raise ERR('RESOURCE_CONSTRAINT',f'{name}={val}',phase)
        if decl['type']=='bool' and type(val)!=bool:raise ERR('INVALID_TYPE',name,phase)
        if decl['type']=='enum' and val not in decl['enum']:raise ERR('INVALID_ENUM',name,phase)
    for actor,txt,rid in info:
        candidate['knowledge'][actor].append({'turn':turn+1,'info':txt,'source':rid})
    for policy in resolutions:
        candidate['trace'].append({'turn':turn+1,'phase':phase,'resolution':policy})
    for r in sorted(triggered,key=lambda x:x['id']):
        candidate['trace'].append({'turn':turn+1,'phase':phase,'rule':r['id'],'grounds':r['grounds']})
    for tr in transitions:
        candidate['trace'].append({'turn':turn+1,'phase':phase,'status_step':tr})
        if tr['to']=='WYKONANE':
            candidate.setdefault('action_meta',{}).setdefault(tr['action'],{})['executed_at']={'turn':turn+1,'phase':phase}
        if tr['to'] in RESULT_STATES:
            candidate.setdefault('action_meta',{}).setdefault(tr['action'],{})['result_at']={'turn':turn+1,'phase':phase}
    st.clear();st.update(candidate)
    return [r['id'] for r in triggered]


def execute(s,cfg,choices_by_turn,choice_map,shuffle=None):
    st=old.initial(cfg,s['actors']); st['choices']=[]; st['action_meta']={}
    for i,t in enumerate(s['turns'],1):
        do_phase(st,t.get('opening',[]),{},s,i-1,'opening',shuffle)
        choices=choices_by_turn[i-1]
        for actor,opt in choices.items():
            if opt not in [v['id'] for v in t['choices'][actor]]:
                raise ERR('INVALID_CHOICE',f'{actor}:{opt}')
        # Status WYBRANE nadawany w chwili wyboru. W v0.2 brak pola OPT.action_id,
        # dlatego używamy osobnej, jawnej i kompletnej mapy kompatybilności.
        m=actor_actions(choice_map,s['id'],i,choices)
        for actor,act in sorted(m.items()):
            if act in st['actions']:
                raise ERR('ACTION_ALREADY_INITIALIZED',f'{act}: {st["actions"][act]}')
            st['actions'][act]='WYBRANE'
            st['action_meta'][act]={'selected_by':actor,'selected_turn':i}
            st['trace'].append({'turn':i,'phase':'choice','actor':actor,'variant':choices[actor],
                                'action':act,'status_step':{'action':act,'from':None,'to':'WYBRANE'}})
        st['choices'].append(deepcopy(choices))
        for phase in ('resolve','npc','consequence'):
            do_phase(st,t.get(phase,[]),choices,s,i-1,phase,shuffle)
    return st


def build_report():
    sdata=json.loads((ROOT/'M2_scenariusze_referencyjne_v02_BEZ_ZMIAN.json').read_text(encoding='utf-8'))
    choice_map=json.loads((ROOT/'M2_adapter_dzialan_v02.json').read_text(encoding='utf-8'))
    rows=[]; static=[]; allerrors=Counter(); stale=Counter()
    for s in sdata:
        static.extend(static_warnings(s))
        counts=Counter(); rejected=[]; accepted=0; total=0; selected_still=[]
        for cfg,seq in old.iter_paths(s):
            total+=1
            try:
                st=execute(s,cfg,seq,choice_map)
                accepted+=1
                lingering=[a for a,x in st['actions'].items() if x=='WYBRANE']
                for a in lingering:stale[(s['id'],a)]+=1
                if lingering and len(selected_still)<2:
                    selected_still.append({'cfg':cfg['id'],'choices':seq,'actions':lingering})
            except ERR as e:
                counts[e.code]+=1;allerrors[e.code]+=1
                if len(rejected)<3:rejected.append({'cfg':cfg['id'],'choices':seq,'error':e.asdict()})
        rows.append({'scenario':s['id'],'paths':total,'accepted':accepted,
                     'rejected':total-accepted,'runtime_errors':dict(counts),
                     'examples_runtime_errors':rejected,
                     'examples_selected_without_completion':selected_still})
    shuffled=0; totals=0
    for s in sdata:
        for cfg,seq in old.iter_paths(s):
            totals+=1
            def outcome(seed):
                try:
                    v=execute(s,cfg,seq,choice_map,random.Random(seed) if seed is not None else None)
                    return json.dumps({'world':v['world'],'actions':v['actions'],'knowledge':v['knowledge']},sort_keys=True)
                except ERR as e:return 'ERR:'+e.code
            b=outcome(None)
            if any(outcome(i)!=b for i in range(20)):shuffled+=1
    report={'version':'M2 v0.3 przed etapem B - prototyp przejściowy',
       'source_json_unchanged':True,'runs':rows,'total_paths':sum(r['paths'] for r in rows),
       'accepted':sum(r['accepted'] for r in rows),
       'rejected':sum(r['rejected'] for r in rows),
       'runtime_errors':dict(allerrors),'static_findings':static,
       'static_pairs':len(static),'selected_without_completion':[
          {'scenario':s,'action':a,'occurrences':n} for (s,a),n in sorted(stale.items())],
       'permutation_changes':shuffled,'permutation_tested_paths':totals,'permutations_per_path':20,
       'limitations':['Nadal brak grafu i dynamicznej bramki wiedzy',
          'W starym JSON nie ma powiązania OPT->ACT: dołączono osobny adapter',
          'Błędne przejścia wieloetapowe są dopuszczone wyłącznie przy istnieniu legalnej ścieżki w automacie',
          'Nie oznacza formalnej niezależnej walidacji ani zakończenia M2 v0.3',
          'Analiza statyczna wykazuje zależności składniowe; nie każda jest błędem',
          'Runtime zatrzymuje się na pierwszym błędzie w danym przebiegu; statyczne ostrzeżenia podawane osobno']}
    (ROOT/'M2_przedB_raport.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PRZED B',report['accepted'],'/',report['total_paths'],'accepted',report['rejected'],'rejected',report['runtime_errors'])
    print('statyczne zależności (pary)',len(static),'przemieszane przebiegi',shuffled)
    print('wybrane bez zakończenia',report['selected_without_completion'])
    return report


def selftests():
    try: status_path('ZLECONE','POTWIERDZONE')
    except ERR as e: assert e.code=='RESULT_REQUIRES_PRIOR_ACTION'
    else: raise AssertionError('Niejawny skrót przyjęty')
    assert status_path('WYBRANE','WYKONANE')==['WYKONANE']
    try:status_path('ODRZUCONE','POTWIERDZONE')
    except ERR as e:assert e.code=='RESULT_REQUIRES_PRIOR_ACTION'
    else:raise AssertionError('Niedozwolone przejście zaakceptowane')
    s={'actors':{'x':'controlled'},'variables':{'stock':{'type':'int','min':0}},'conflict_rules':[]}
    def rule(i,op):return {'id':i,'ops':[op],'grounds':['ASM-X']}
    st={'world':{'stock':3},'actions':{},'knowledge':{'x':[]},'positions':{'x':'start'},'trace':[]}
    do_phase(st,[rule('a',{'op':'inc','var':'stock','value':-1}),rule('b',{'op':'inc','var':'stock','value':-1})],{},s,0,'resolve')
    assert st['world']['stock']==1
    st={'world':{'stock':1},'actions':{},'knowledge':{'x':[]},'positions':{'x':'start'},'trace':[]}
    b=deepcopy(st)
    try:do_phase(st,[rule('a',{'op':'inc','var':'stock','value':-1}),rule('b',{'op':'inc','var':'stock','value':-1})],{},s,0,'resolve')
    except ERR as e:assert e.code=='RESOURCE_CONSTRAINT' and st==b
    else:raise AssertionError('Naruszenie zasobu przyjęte')
    print('testy mechanizmu przejść i atomowości: 5/5')

if __name__=='__main__':
    selftests()
    build_report()
