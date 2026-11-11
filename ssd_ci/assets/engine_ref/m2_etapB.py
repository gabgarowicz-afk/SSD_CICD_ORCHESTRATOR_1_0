#!/usr/bin/env python3
"""M2 v0.3, etap B/1 — konstrukcyjny model K, obserwacji i wariantów.

Integracja z silnikiem fazowym etapu A: do_phase z niezmienioną semantyką
migawki i atomowości. Bez AI podczas wykonania. Nie jest silnikiem produkcyjnym.
"""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
import json
import m2_przedB_poprawka_statusow as A

PhaseError = A.ERR
MODES = {'factual', 'deliberate_false', 'mistake', 'unverified', 'report'}
PHASES = ('opening', 'resolve', 'npc', 'consequence')
OPS = {'eq', 'ne', 'gt', 'ge', 'lt', 'le'}
EVIDENCE_KINDS = {'system_log', 'npc_observation', 'independent_event'}
ENGINE_EVIDENCE_KIND = 'world_conditions'


def error(code, message):
    raise PhaseError(code, message)


def evaluate_claim(claim, world):
    if not isinstance(claim, dict) or set(claim) != {'var', 'op', 'value'}:
        error('BAD_CLAIM', 'Twierdzenie musi zawierać dokładnie var/op/value')
    key, relation, val = claim['var'], claim['op'], claim['value']
    if key not in world or relation not in OPS:
        error('BAD_CLAIM', f'Nieznana zmienna lub relacja: {key} / {relation}')
    actual = world[key]
    ops = {'eq': lambda: actual == val, 'ne': lambda: actual != val,
           'gt': lambda: actual > val, 'ge': lambda: actual >= val,
           'lt': lambda: actual < val, 'le': lambda: actual <= val}
    try:
        return bool(ops[relation]())
    except (ValueError, TypeError) as ex:
        error('BAD_CLAIM', str(ex))


def visible_observations(st, actor):
    """Prezentacja uczestnikowi nie ujawnia audytu prawdziwości ani ukrytego R."""
    return [{k: deepcopy(obs[k]) for k in ('id', 'text', 'source', 'claim', 'reference', 'received')}
            for obs in st['knowledge'][actor]]


def actor_view(st, scenario, actor, turn, visible_choices=None):
    if actor not in scenario['actors']:
        error('UNKNOWN_ACTOR', actor)
    out = {'actor': actor, 'turn': turn, 'observations': visible_observations(st, actor)}
    if visible_choices is not None:
        out['choices'] = [{'id': c['id'], 'label': c['label']} for c in visible_choices]
    return out


def _received(st, actor, obs_id):
    return any(x['id'] == obs_id for x in st['knowledge'][actor])


def _reported(st, actor, assertion):
    return any(x['claim'] == assertion for x in st['knowledge'][actor])


def gate_check(gate, st, actor):
    """Bramka może czytać WYŁĄCZNIE K wskazanej postaci. Nie ma dostępu do R."""
    if gate is None:
        return True
    if isinstance(gate, dict) and 'var' in gate:
        error('FORBIDDEN_GATE_REFERENCE', 'Bramka nie może czytać stanu R')
    if not isinstance(gate, dict) or len(gate) != 1:
        error('INVALID_GATE', str(gate))
    if 'all' in gate:
        return all(gate_check(g, st, actor) for g in gate['all'])
    if 'any' in gate:
        return any(gate_check(g, st, actor) for g in gate['any'])
    if 'not' in gate:
        return not gate_check(gate['not'], st, actor)
    if 'observed' in gate:
        if not isinstance(gate['observed'], str):
            error('INVALID_GATE', 'observed to identyfikator obserwacji, nie odczyt cudzego K')
        return _received(st, actor, gate['observed'])
    if 'reported' in gate:
        return _reported(st, actor, gate['reported'])
    error('FORBIDDEN_GATE_REFERENCE', 'Bramka nie może odczytywać R, cudzej wiedzy ani statusu działania')


def rule_pred(cond, st, choices):
    """Reguły świata mają prawo czytać R i K; dostępność opcji — tylko K."""
    if cond is None:
        return True
    if 'all' in cond:
        return all(rule_pred(x, st, choices) for x in cond['all'])
    if 'any' in cond:
        return any(rule_pred(x, st, choices) for x in cond['any'])
    if 'not' in cond:
        return not rule_pred(cond['not'], st, choices)
    if 'observed' in cond:
        obj = cond['observed']
        if not isinstance(obj, dict) or set(obj) != {'actor', 'id'}:
            error('INVALID_PREDICATE', str(obj))
        if obj['actor'] not in st['knowledge']:
            error('UNKNOWN_ACTOR', obj['actor'])
        return _received(st, obj['actor'], obj['id'])
    if 'reported' in cond:
        obj = cond['reported']
        if not isinstance(obj, dict) or set(obj) != {'actor', 'claim'}:
            error('INVALID_PREDICATE', str(obj))
        return _reported(st, obj['actor'], obj['claim'])
    return A.old.eval_pred(cond, st, choices)


def visible_options(s, st, turn, actor):
    options = s['turns'][turn - 1]['choices'][actor]
    visible = [x for x in options if gate_check(x.get('availability'), st, actor)]
    if not visible:
        error('NO_VISIBLE_CHOICE', f'{s["id"]}: {actor}, tura {turn}')
    return visible


def protected_registry(s):
    """Jawna deklaracja własności skutków; bez heurystyk po nazwach."""
    protected = {}
    for var, meta in s.get('variables', {}).items():
        if meta.get('effect_role') not in ('ordinary', 'protected'):
            error('UNCLASSIFIED_EFFECT', f'{var}: wymagany effect_role')
        if meta['effect_role'] == 'protected':
            owner = meta.get('effect_owner')
            if not isinstance(owner, dict) or not owner.get('actions') or owner.get('stage') not in ('execution','confirmation'):
                error('INVALID_EFFECT_OWNER', f'{var}: wymagane actions + stage')
            if not all(isinstance(a,str) and a for a in owner['actions']):
                error('INVALID_EFFECT_OWNER', var)
            protected[var] = owner
    return protected


def _effect_rule_authorization(s, phase, r, owner, protected_var):
    """Jedno źródło zasad statycznych i wykonawczych dla skutków chronionych.

    Postać sterowana może zlecać działanie. Późniejsza reguła silnika
    może obliczyć rzeczywisty skutek z warunków świata (nie z samego wyboru).
    """
    act = r.get('effect_of')
    if act not in owner['actions']:
        return 'UNAUTHORIZED_EFFECT_OWNER'
    if phase not in ('npc', 'consequence'):
        return 'PROTECTED_EFFECT_IN_SELECTION_PHASE'
    actor = r.get('actor')
    proof = r.get('evidence', {})
    if not isinstance(proof, dict) or not proof.get('basis'):
        return 'PROTECTED_EFFECT_WITHOUT_EVIDENCE'
    if actor == 'engine':
        if owner['stage'] == 'confirmation':
            return 'ENGINE_CANNOT_SELF_CONFIRM_RESULT'
        if 'engine' in s.get('actors', {}):
            return 'RESERVED_EXECUTOR_NAME'
        if proof.get('source') != 'engine' or proof.get('kind') != ENGINE_EVIDENCE_KIND:
            return 'INVALID_ENGINE_PROOF'
        pre = r.get('preconditions')
        if not isinstance(pre, list) or not pre:
            return 'ENGINE_PRECONDITIONS_REQUIRED'
        for cond in pre:
            if (not isinstance(cond,dict) or set(cond) != {'var','op','value'}
                    or cond['var'] not in s['variables'] or cond['op'] not in OPS):
                return 'INVALID_ENGINE_PRECONDITION'
    elif s.get('actors', {}).get(actor) == 'npc':
        if proof.get('source') != actor or proof.get('kind') not in EVIDENCE_KINDS:
            return 'INVALID_NPC_PROOF'
    else:
        return 'INVALID_EFFECT_EXECUTOR'
    if not r.get('grounds'):
        return 'MISSING_RULE_GROUNDS'
    desired='WYKONANE' if owner['stage']=='execution' else 'POTWIERDZONE'
    if not any(op.get('op')=='status' and op.get('action')==act and op.get('value')==desired
               for op in r.get('ops', [])):
        return 'PROTECTED_EFFECT_WITHOUT_STATUS'
    return None


def _engine_prerequisites_met(r, st, choices):
    # Każdy warunek odnosi się bezpośrednio do R z POCZĄTKU fazy.
    # Samo wybranie wariantu nie wystarcza do wykonania skutku.
    if r.get('actor') != 'engine':
        return True
    return all(rule_pred(cond, st, choices) for cond in r.get('preconditions', []))

def effect_static_findings(s):
    """Wykrywanie naruszeń w definicji bez konieczności uruchamiania ścieżek."""
    protected = protected_registry(s)
    findings = []
    all_actions = {opt.get('effect',{}).get('action_id')
                   for t in s.get('turns', []) for oo in t.get('choices',{}).values()
                   for opt in oo if opt.get('effect',{}).get('kind') == 'action'}
    for var,owner in protected.items():
        for a in owner['actions']:
            if a not in all_actions:
                findings.append({'code':'UNKNOWN_EFFECT_OWNER','location':var,'detail':a})
    for turn,t in enumerate(s.get('turns',[]),1):
        for actor,opts in t.get('choices',{}).items():
            for opt in opts:
                for op in opt.get('effect',{}).get('ops',[]):
                    if op.get('op') in ('set','inc') and op.get('var') in protected:
                        findings.append({'code':'PROTECTED_EFFECT_AT_SELECTION','location':f'T{turn}.{actor}.{opt["id"]}',
                                         'detail':op['var']})
        for phase in PHASES:
            for r in t.get(phase,[]):
                writes={op['var'] for op in r.get('ops',[]) if op['op'] in ('set','inc') and op.get('var') in protected}
                for var in writes:
                    owner=protected[var]
                    act=r.get('effect_of')
                    actor=r.get('actor')
                    proof=r.get('evidence',{})
                    violation=_effect_rule_authorization(s, phase, r, owner, var)
                    if violation:
                        findings.append({'code':violation,'location':f'T{turn}.{phase}.{r["id"]}',
                                         'detail':var})
    return findings


def check_effect_execution(s, snap, phase, triggered):
    """Obrona w czasie wykonania nawet przy pominiętej walidacji statycznej."""
    protected=protected_registry(s)
    for r in triggered:
        vars_={o['var'] for o in r.get('ops',[]) if o.get('op') in ('set','inc') and o.get('var') in protected}
        for var in vars_:
            owner=protected[var]
            act=r.get('effect_of')
            if r['id'].startswith('CHOICE-') or not act or act not in owner['actions']:
                error('PROTECTED_EFFECT_WITHOUT_EXECUTION', f'{r["id"]}: {var} nie może wynikać z wyboru')
            violation=_effect_rule_authorization(s, phase, r, owner, var)
            if violation:
                error(violation, f'{r["id"]}: {var}')
            if r.get('actor') == 'engine' and not _engine_prerequisites_met(r, snap, {}):
                error('ENGINE_PRECONDITIONS_NOT_MET', f'{r["id"]}: {var}')
            if act not in snap['actions']:
                error('EFFECT_ACTION_NOT_SELECTED',f'{r["id"]}: {act}')


def validate_definition(s):
    """Kontrola konstrukcji; nie jest niezależną walidacją merytoryczną."""
    errors = []
    if 'engine' in s.get('actors', {}):
        errors.append('RESERVED_EXECUTOR_NAME: engine to znacznik silnika, nie postać')
    try:
        errors.extend(f"{item['code']} {item['location']}: {item['detail']}" for item in effect_static_findings(s))
    except PhaseError as ex:
        errors.append(f'{ex.code}: {ex.detail}')
    for ix, t in enumerate(s.get('turns', []), 1):
        for actor, choices in t.get('choices', {}).items():
            if actor not in s['actors'] or s['actors'][actor] != 'controlled':
                errors.append(f'T{ix}.{actor}: niedozwolona postać sterowana')
            ids = set()
            for o in choices:
                loc = f'T{ix}.{actor}.{o.get("id", "?")}'
                if not o.get('id') or o['id'] in ids:
                    errors.append(loc + ': brak/duplikat id')
                ids.add(o.get('id'))
                if not o.get('label'):
                    errors.append(loc + ': brak etykiety')
                if not o.get('grounds'):
                    errors.append(loc + ': brak uzasadnienia')
                for attr in ('benefits', 'limits', 'risks'):
                    if not o.get(attr):
                        errors.append(loc + f': brak {attr}')
                ef = o.get('effect')
                if not isinstance(ef, dict) or ef.get('kind') not in ('action', 'inaction'):
                    errors.append(loc + ': brak jawnego effect.kind')
                else:
                    if ef['kind'] == 'action' and not ef.get('action_id'):
                        errors.append(loc + ': brak identyfikatora działania')
                    if ef['kind'] == 'inaction' and ef.get('category') not in ('defer','omit','wait'):
                        errors.append(loc + ': brak kategorii zaniechania')
                    if 'ops' not in ef or not isinstance(ef['ops'], list) or not ef.get('consequence'):
                        errors.append(loc + ': konsekwencja musi być jawna (również przy braku zmiany R)')
                if o.get('availability') is not None:
                    # Własna deklaracja autora: bramka tylko dla wariantu, którego
                    # treść zawiera konkretną, uprzednio poznaną informację.
                    if not o.get('discloses_observation'):
                        errors.append(loc + ': BRAMKA_BEZ_UZASADNIENIA_INFORMACYJNEGO')
                    if o.get('availability') != {'observed':o.get('discloses_observation')}:
                        errors.append(loc + ': NIESPOJNA_BRAMKA_INFORMACYJNA')
                try:
                    # Bramka na pustym K wykrywa niedozwolone odwołania do R.
                    dummy = {'knowledge': {a: [] for a in s['actors']}}
                    gate_check(o.get('availability'), dummy, actor)
                except PhaseError as ex:
                    errors.append(loc + ': ' + ex.code)
    for cfg in s.get('configurations', []):
        for actor, obs in cfg.get('knowledge', {}).items():
            if actor not in s['actors']:
                errors.append(f'{cfg["id"]}: nieznany odbiorca {actor}')
            if not isinstance(obs, list):
                errors.append(f'{cfg["id"]}: K musi być listą strukturalnych obserwacji')
    return errors


def deliver(st, obs, actor, turn, phase, start_world, end_world):
    """Wewnętrzny audyt twierdzenia jest poza K; do K trafia tylko wypowiedź."""
    if actor not in st['knowledge']:
        error('UNKNOWN_ACTOR', actor)
    required = {'id', 'source', 'text', 'mode', 'claim'}
    if not required.issubset(obs) or obs['mode'] not in MODES:
        error('INVALID_OBSERVATION', f'{obs}: wymagane {sorted(required)} i prawidłowy mode')
    if not obs['id'] or not obs['source'] or not obs['text']:
        error('INVALID_OBSERVATION', 'Puste id / source / text')
    if obs['id'] in st['observation_audit']:
        error('DUPLICATE_OBSERVATION', obs['id'])
    ref = obs.get('reference', 'phase_result')
    key = f'T{turn}.{phase}'
    if ref == 'phase_start':
        referenced = start_world
        ref_key = key + '.start'
    elif ref == 'phase_result':
        referenced = end_world
        ref_key = key + '.end'
    elif ref in st['world_history']:
        referenced = st['world_history'][ref]
        ref_key = ref
    else:
        error('UNKNOWN_REFERENCE_TIME', str(ref))
    truth_at_ref = evaluate_claim(obs['claim'], referenced)
    if obs['mode'] == 'factual' and not truth_at_ref:
        error('UNDECLARED_FALSE_INFORMATION', obs['id'])
    if obs['mode'] in ('mistake', 'deliberate_false') and truth_at_ref:
        error('MISCLASSIFIED_FALSE_INFORMATION', obs['id'])
    public = {'id': obs['id'], 'text': obs['text'], 'source': obs['source'],
              'claim': deepcopy(obs['claim']), 'reference': ref_key,
              'received': {'turn': turn, 'phase': phase}}
    st['knowledge'][actor].append(public)
    # Autor/wykonawca może zobaczyć audyt; uczestnik nigdy nie otrzymuje tych pól.
    st['observation_audit'][obs['id']] = {'recipient': actor, 'mode': obs['mode'],
        'truth_at_reference': truth_at_ref, 'truth_now': evaluate_claim(obs['claim'], end_world),
        'stale_now': truth_at_ref and not evaluate_claim(obs['claim'], end_world),
        'reference': ref_key}
    st['trace'].append({'turn': turn, 'phase': phase, 'observation_delivered': obs['id'],
        'actor': actor, 'reference': ref_key})


def refresh_truth_audit(st):
    # Nieaktualność jest wyliczana automatycznie z czasu odniesienia; nigdy nie zmienia K.
    for actor, items in st['knowledge'].items():
        for obs in items:
            record = st['observation_audit'][obs['id']]
            truth_now = evaluate_claim(obs['claim'], st['world'])
            record['truth_now'] = truth_now
            record['stale_now'] = record['truth_at_reference'] and not truth_now


def initial(s, cfg):
    base = {'world': deepcopy(cfg['world']), 'knowledge': {a: [] for a in s['actors']},
            'positions': {a:'start' for a in s['actors']}, 'actions': {}, 'action_meta':{},
            'trace': [], 'choices': [], 'world_history': {'INIT': deepcopy(cfg['world'])},
            'observation_audit': {}, 'world_time': 0}
    # Te obserwacje mogą być prawdziwe, błędne, niepewne; samo otrzymanie nie oznacza wiary.
    for actor in sorted(s['actors']):
        for obs in cfg['knowledge'].get(actor, []):
            obs2 = deepcopy(obs)
            obs2['reference'] = 'INIT'
            deliver(base, obs2, actor, 0, 'configuration', base['world'], base['world'])
    return base


def run_phase(st, s, turn, phase, rules, choices):
    """Atomowa integracja zmian R/statusów z K, wraz z kontrolą czasu odniesienia."""
    snap = deepcopy(st)
    working = deepcopy(st)
    key = f'T{turn}.{phase}'
    working['world_history'][key + '.start'] = deepcopy(snap['world'])
    triggered = [r for r in rules if rule_pred(r.get('when'), snap, choices)
                 and _engine_prerequisites_met(r, snap, choices)]
    # Kontrola skutku ochronnego zanim etap A zatwierdzi jakąkolwiek zmianę.
    check_effect_execution(s, snap, phase, triggered)
    observations = []
    selected_rules = []
    for r in triggered:
        ops = []
        for op in r.get('ops', []):
            if op['op'] == 'observe':
                observations.append((op['actor'], op['message']))
            else:
                ops.append(deepcopy(op))
        selected_rules.append({**r, 'when': None, 'ops': ops})
    # Metoda A ocenia wszystkie propozycje na wspólnej migawce i zatwierdza atomowo.
    A.do_phase(working, selected_rules, choices, s, turn-1, phase)
    working['world_history'][key + '.end'] = deepcopy(working['world'])
    for actor, ob in sorted(observations, key=lambda x: (x[0], x[1]['id'])):
        deliver(working, ob, actor, turn, phase, snap['world'], working['world'])
    for r in sorted(triggered, key=lambda rr: rr['id']):
        if r.get('effect_of'):
            working['trace'].append({'turn':turn, 'phase':phase, 'effect_execution':r['effect_of'],
                'executor':r.get('actor'), 'proof_kind':r.get('evidence',{}).get('kind'),
                'preconditions':deepcopy(r.get('preconditions', [])), 'rule':r['id']})
    refresh_truth_audit(working)
    working['world_time'] += 1
    # Do prawdziwego stanu przekładamy całą fazę dopiero po kompletnych kontrolach.
    st.clear(); st.update(working)


def execute(s, cfg, choices_by_turn, return_views=False):
    errs = validate_definition(s)
    if errs:
        error('INVALID_DEFINITION', '; '.join(errs))
    st = initial(s, cfg)
    views = []
    for turn, t in enumerate(s['turns'], 1):
        run_phase(st, s, turn, 'opening', t.get('opening', []), {})
        picks = choices_by_turn[turn-1]
        menu = {}
        for actor in sorted(t['choices']):
            available = visible_options(s, st, turn, actor)
            menu[actor] = {v['id']: v for v in available}
            views.append(actor_view(st, s, actor, turn, available))
            if actor not in picks or picks[actor] not in menu[actor]:
                error('CHOICE_NOT_VISIBLE', f'{actor}: {picks.get(actor)} w turze {turn}')
        if set(picks) != set(menu):
            error('INCOMPLETE_CHOICES', str(picks))
        action_picks = set()
        synthetic = []
        for actor, selected in sorted(picks.items()):
            opt = menu[actor][selected]
            ef = opt['effect']
            if ef['kind'] == 'action':
                action_id = ef['action_id']
                if action_id in st['actions'] or action_id in action_picks:
                    error('ACTION_ALREADY_INITIALIZED', action_id)
                action_picks.add(action_id)
                st['actions'][action_id] = 'WYBRANE'
                st['action_meta'][action_id] = {'selected_by':actor,'selected_turn':turn}
                st['trace'].append({'turn':turn, 'phase':'choice', 'actor':actor,
                    'choice':selected, 'action':action_id, 'status':'WYBRANE'})
            else:
                st['trace'].append({'turn':turn, 'phase':'choice', 'actor':actor,
                    'choice':selected, 'inaction':ef['category'],
                    'consequence':ef['consequence']})
            # Nawet brak operacji ma jawną, opisaną konsekwencję.
            synthetic.append({'id': f'CHOICE-{turn}-{actor}-{selected}', 'when': None,
                    'ops': deepcopy(ef['ops']), 'grounds': opt['grounds']})
        st['choices'].append(deepcopy(picks))
        run_phase(st, s, turn, 'resolve', t.get('resolve', []) + synthetic, picks)
        for phase in ('npc', 'consequence'):
            run_phase(st, s, turn, phase, t.get(phase, []), picks)
    return (st, views) if return_views else st


def static_information_audit(s):
    """W wersji B/1 audyt informacji opiera się na konkretnych przebiegach."""
    issues = validate_definition(s)
    return {'definition_errors': issues, 'effect_findings': effect_static_findings(s), 'checks': ['choice_effect', 'K_only_gate', 'source_time_mode', 'effect_owner']}


def digest_world(st):
    return json.dumps({'world':st['world'], 'actions':st['actions']}, sort_keys=True, ensure_ascii=False)
