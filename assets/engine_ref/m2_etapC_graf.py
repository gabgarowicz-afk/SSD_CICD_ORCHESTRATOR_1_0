#!/usr/bin/env python3
"""M2 v0.3 etap C/0: prototyp grafu wykonywanego w turach.

Nie jest produkcyjnym silnikiem ani niezależną walidacją. Wspiera:
- jedną aktywną pozycję każdej postaci sterowanej;
- automatyczny jawny wariant oczekiwania dla pozycji terminalnej;
- atomowe zatwierdzanie R, K, statusów i pozycji po pełnej turze;
- warunki krawędzi oceniane NA STANIE PO fazie consequence;
- pętle i odrębne wystąpienia działań (base#nr), gdy wcześniejsze zakończono;
- limit tur z określonym zakończeniem.

Ograniczenie C/0: wszystkie aktywne postacie muszą wskazywać ten sam szablon
tury; nie obsługuje niesynchronizowanych, równoległych wątków ani jednocześnie
aktywnych wystąpień tego samego działania.
"""
from __future__ import annotations
from copy import deepcopy
import json
import m2_etapB as B

PhaseError=B.PhaseError

def err(code,detail):
    raise PhaseError(code,detail)

WAIT={'id':'wait','label':'Czekam — nie podejmuję nowego działania',
      'effect':{'kind':'inaction','category':'wait','ops':[],'consequence':'Pozostaję bez nowego zlecenia'},
      'grounds':['C-TERMINAL-WAIT'],'benefits':'Nie blokuje innych postaci.',
      'limits':'Nie tworzy nowego skutku.','risks':'Może opóźnić reakcję.'}


def validate_graph(s):
    issues=B.validate_definition(s)
    graph=s.get('graph')
    if not isinstance(graph,dict):return issues+['MISSING_GRAPH']
    nodes=graph.get('nodes',{}); start=graph.get('start',{}); cap=graph.get('max_turns')
    if not isinstance(cap,int) or cap<1:issues.append('INVALID_TURN_LIMIT')
    controlled={a for a,k in s['actors'].items() if k=='controlled'}
    if set(start)!=controlled:issues.append('INVALID_GRAPH_START_ACTORS')
    if not isinstance(nodes,dict) or not nodes:issues.append('EMPTY_GRAPH');return issues
    for a,node in start.items():
        if node not in nodes or nodes[node].get('actor')!=a:issues.append('INVALID_START_NODE:'+a)
    for nid,n in nodes.items():
        if n.get('actor') not in controlled:issues.append('INVALID_NODE_ACTOR:'+nid)
        if n.get('terminal'):
            if n.get('template_turn') is not None:issues.append('TERMINAL_HAS_TEMPLATE:'+nid)
            if n.get('edges'):issues.append('TERMINAL_HAS_EDGES:'+nid)
            continue
        t=n.get('template_turn')
        if not isinstance(t,int) or not 1<=t<=len(s['turns']):issues.append('INVALID_TEMPLATE:'+nid);continue
        opts=s['turns'][t-1]['choices'].get(n['actor'],[])
        if not opts:issues.append('NO_CHOICE_AT_NODE:'+nid)
        if not n.get('edges'):issues.append('NO_GRAPH_EDGES:'+nid)
        for e in n.get('edges',[]):
            if not isinstance(e,dict) or e.get('to') not in nodes:issues.append('INVALID_EDGE:'+nid);continue
            if nodes[e['to']].get('actor')!=n['actor']:issues.append('CROSS_ACTOR_EDGE:'+nid)
    if not any(n.get('terminal') for n in nodes.values()):issues.append('NO_TERMINAL_NODE')
    return issues


def new_state(s,cfg):
    errs=validate_graph(s)
    if errs:err('INVALID_GRAPH','; '.join(errs))
    st=B.initial(s,cfg)
    st['positions']=deepcopy(s['graph']['start'])
    st['graph_end']=None
    st['graph_turn']=0
    st['action_occurrences']={}
    st['action_counts']={}
    st['choice_history']=[]
    return st


def available(s,st,actor):
    node=s['graph']['nodes'][st['positions'][actor]]
    if node.get('terminal'):return [deepcopy(WAIT)]
    return B.visible_options(s,st,node['template_turn'],actor)


def view(s,st,actor):
    # Celowo NIE ujawniamy wewnętrznej pozycji grafu ani żadnej zmiennej R.
    visible=available(s,st,actor)
    return B.actor_view(st,s,actor,st['graph_turn']+1,visible)


def _node_destinations(s,st,chosen):
    """Funkcja czysta: ocena każdej krawędzi na tej samej, KOŃCOWEJ migawce."""
    nodes=s['graph']['nodes'];new={}
    for actor,old_node in st['positions'].items():
        node=nodes[old_node]
        if node.get('terminal'):
            new[actor]=old_node;continue
        matches=[e for e in node['edges'] if B.rule_pred(e.get('when'),st,chosen)]
        if len(matches)!=1:err('GRAPH_EDGE_AMBIGUOUS_OR_MISSING',f'{actor}:{old_node}, pasujących krawędzi: {len(matches)}')
        new[actor]=matches[0]['to']
    return new


def _finalize_occurrences(working):
    """Wersja C/0: ostatnie wystąpienie akcji jest związane z aliasem bazowym B.
    Stany wystąpień są utrwalane także po kolejnych fazach.
    """
    for base,record in working['action_occurrences'].items():
        # Aktualizujemy tylko aktualnie aktywny alias danego typu.
        newest=f'{base}#{working["action_counts"][base]}'
        record[newest]['status']=working['actions'].get(base,'BRAK')


def run_turn(st,s,picks):
    """Wykonuje TURĘ na kopii; zatwierdza całość (łącznie z P) albo nic."""
    if st['graph_end'] is not None:err('GRAPH_ALREADY_FINISHED',st['graph_end'])
    w=deepcopy(st); tno=w['graph_turn']+1
    active={actor:n for actor,n in w['positions'].items() if not s['graph']['nodes'][n].get('terminal')}
    templates={s['graph']['nodes'][node]['template_turn'] for node in active.values()}
    if len(templates)>1:err('UNSYNCHRONIZED_TEMPLATES',str(templates))
    template=next(iter(templates)) if templates else None
    if template is None:
        # Normalnie poprzednia tura kończy symulację, to defensywna kontrola.
        err('GRAPH_ALREADY_TERMINAL','Wszystkie postacie są terminalne')
    t=s['turns'][template-1]
    B.run_phase(w,s,tno,'opening',t.get('opening',[]),{})
    controls=sorted(w['positions'])
    bad=set(picks)-set(controls)
    if bad:err('UNKNOWN_PICK_ACTORS',str(bad))
    resolved={}
    for actor in controls:
        options={o['id']:o for o in available(s,w,actor)}
        item=picks.get(actor)
        if s['graph']['nodes'][w['positions'][actor]].get('terminal') and item is None:
            item='wait'
        if item not in options:err('GRAPH_CHOICE_NOT_VISIBLE',f'{actor}={item}; dostępne: {list(options)}')
        resolved[actor]=item
    synthetic=[]
    for actor,variant in sorted(resolved.items()):
        option=next(x for x in available(s,w,actor) if x['id']==variant)
        ef=option['effect']
        if ef['kind']=='action':
            base=ef['action_id'];counts=w['action_counts'];idx=counts.get(base,0)+1
            if idx>1 and w['actions'].get(base) not in ('WYKONANE','POTWIERDZONE','ODRZUCONE','NIESKUTECZNE'):
                err('REPEATED_ACTION_STILL_ACTIVE',base)
            counts[base]=idx;occ=f'{base}#{idx}'
            w['actions'][base]='WYBRANE'
            w['action_meta'][base]={'selected_by':actor,'selected_turn':tno}
            w['action_occurrences'].setdefault(base,{})[occ]={'actor':actor,'turn':tno,'choice':variant,'status':'WYBRANE'}
            w['trace'].append({'turn':tno,'phase':'choice','actor':actor,'choice':variant,'action':occ,'status':'WYBRANE'})
        else:
            w['trace'].append({'turn':tno,'phase':'choice','actor':actor,'choice':variant,
                               'inaction':ef['category'],'consequence':ef['consequence']})
        synthetic.append({'id':f'GRAPH-CHOICE-{tno}-{actor}-{variant}','when':None,
                          'ops':deepcopy(ef['ops']),'grounds':option['grounds']})
    w['choice_history'].append(deepcopy(resolved))
    B.run_phase(w,s,tno,'resolve',t.get('resolve',[])+synthetic,resolved)
    for phase in ('npc','consequence'):
        B.run_phase(w,s,tno,phase,t.get(phase,[]),resolved)
    # Wszystkie przejścia grafu oceniane PO wykonaniu faz (w tym obserwacji K),
    # na jednym stanie. Aktualizacja P jest częścią TEGO SAMEGO commit co R.
    new_positions=_node_destinations(s,w,resolved)
    previous=deepcopy(w['positions'])
    w['positions']=new_positions
    w['graph_turn']=tno
    _finalize_occurrences(w)
    w['trace'].append({'turn':tno,'phase':'graph_commit','before':previous,'after':deepcopy(new_positions)})
    if all(s['graph']['nodes'][n].get('terminal') for n in new_positions.values()):
        w['graph_end']='ZAKONCZENIE_GRAFU'
    elif tno>=s['graph']['max_turns']:
        w['graph_end']=s['graph'].get('limit_end','ZAKONCZENIE_LIMITEM_TUR')
    st.clear();st.update(w)
    return st


def execute_graph(s,cfg,choices_by_turn):
    st=new_state(s,cfg)
    for ch in choices_by_turn:
        if st['graph_end'] is not None:err('CHOICES_AFTER_END',st['graph_end'])
        run_turn(st,s,ch)
    return st
