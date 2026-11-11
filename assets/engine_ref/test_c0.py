#!/usr/bin/env python3
"""Próby konstrukcyjne AI etapu C/0. NIE są walidacją niezależną."""
import copy, itertools, json, random, unittest
from pathlib import Path
import m2_etapB as B
import m2_etapC_graf as C

ROOT=Path(__file__).resolve().parent
S={s['id']:s for s in json.loads((ROOT/'C0_SCENARIUSZE_GRAFOWE.json').read_text('utf-8'))}
OLD={s['id']:s for s in json.loads((ROOT/'B2_GABINET_URZAD_MIGRACJE_KONSTRUKCYJNE.json').read_text('utf-8'))}


def paths(s):
    grids=[]
    for t in s['turns']:
        roles=sorted(t['choices'])
        grids.append([dict(zip(roles,items)) for items in itertools.product(*[[x['id'] for x in t['choices'][actor]] for actor in roles])])
    for cfg in s['configurations']:
        for seq in itertools.product(*grids):yield cfg,list(seq)

class GraphConstruction(unittest.TestCase):
    def test_01_definicje_grafow(self):
        for s in S.values():self.assertEqual(C.validate_graph(s),[],s['id'])
    def test_02_108_przebiegow_zgodnych_z_bazowym_B21(self):
        n=0
        for sid,source in [('C0-CLINIC','B2-CLINIC'),('C0-MUNICIPAL','B2-MUNICIPAL')]:
            s=S[sid];b=OLD[source]
            for cfg,seq in paths(s):
                c=C.execute_graph(s,cfg,seq);x=B.execute(b,cfg,seq)
                self.assertEqual(c['world'],x['world'])
                self.assertEqual(c['actions'],x['actions'])
                self.assertEqual(c['knowledge'],x['knowledge'])
                self.assertEqual(c['graph_end'],'ZAKONCZENIE_GRAFU')
                n+=1
        self.assertEqual(n,108)
    def test_03_powrot_do_wezla_i_drugie_wystapienie_dzialania(self):
        s=S['C0-RETRY'];st=C.new_state(s,s['configurations'][0])
        C.run_turn(st,s,{'technician':'retry'})
        self.assertEqual(st['positions']['technician'],'try');self.assertEqual(st['graph_turn'],1)
        C.run_turn(st,s,{'technician':'retry'})
        self.assertEqual(st['positions']['technician'],'end')
        self.assertEqual(st['graph_end'],'ZAKONCZENIE_GRAFU')
        self.assertEqual(set(st['action_occurrences']['attempt']),{'attempt#1','attempt#2'})
        self.assertEqual([x['status'] for x in st['action_occurrences']['attempt'].values()],['WYKONANE','WYKONANE'])
    def test_04_limit_tur_przerywa_petle(self):
        s=S['C0-RETRY'];st=C.new_state(s,s['configurations'][0])
        for _ in range(3):C.run_turn(st,s,{'technician':'wait'})
        self.assertEqual(st['graph_end'],'PRZERWANIE_PO_3_TURACH')
        self.assertEqual(st['world']['attempts'],0)
    def test_05_wartosc_konca_fazy_steruje_krawedzia(self):
        s=copy.deepcopy(S['C0-RETRY']);s['graph']['nodes']['try']['edges']=[
           {'to':'end','when':{'var':'attempts','op':'ge','value':1}},
           {'to':'try','when':{'var':'attempts','op':'lt','value':1}}]
        st=C.new_state(s,s['configurations'][0]);self.assertEqual(st['world']['attempts'],0)
        C.run_turn(st,s,{'technician':'retry'})
        self.assertEqual(st['positions']['technician'],'end')
        self.assertEqual(st['world']['attempts'],1)
    def test_06_aktualizacja_R_i_P_jest_atomowa_przy_bledzie(self):
        s=copy.deepcopy(S['C0-RETRY']);s['graph']['nodes']['try']['edges'].append({'to':'end'})
        st=C.new_state(s,s['configurations'][0]);before=copy.deepcopy(st)
        with self.assertRaises(C.PhaseError) as c:C.run_turn(st,s,{'technician':'retry'})
        self.assertEqual(c.exception.code,'GRAPH_EDGE_AMBIGUOUS_OR_MISSING')
        self.assertEqual(st,before)
    def test_07_po_ukonczeniu_jedna_postac_nie_blokuje_drugiej(self):
        s=S['C0-DUO'];st=C.new_state(s,s['configurations'][0])
        C.run_turn(st,s,{'alpha':'done','beta':'advance'})
        self.assertEqual(st['positions']['alpha'],'aend')
        self.assertEqual([x['id'] for x in C.available(s,st,'alpha')],['wait'])
        C.run_turn(st,s,{'beta':'advance'})
        self.assertEqual(st['world']['progress'],2)
        self.assertEqual(st['graph_end'],'ZAKONCZENIE_GRAFU')
    def test_08_wybor_niedostepny_odrzucony_bez_zmiany_stanu(self):
        s=S['C0-DUO'];st=C.new_state(s,s['configurations'][0]);old=copy.deepcopy(st)
        with self.assertRaises(C.PhaseError):C.run_turn(st,s,{'alpha':'advance','beta':'advance'})
        self.assertEqual(st,old)
    def test_09_pozycje_nie_sa_ujawniane_uczestnikowi(self):
        s=S['C0-CLINIC'];a,b=s['configurations']
        x=C.new_state(s,a);y=C.new_state(s,b)
        self.assertNotEqual(x['world'],y['world'])
        self.assertEqual(C.view(s,x,'doctor'),C.view(s,y,'doctor'))
        self.assertNotIn('positions',C.view(s,x,'doctor'))
    def test_10_brak_sciezki_nie_wybiera_krawedzi_domyslnie(self):
        s=copy.deepcopy(S['C0-RETRY']);s['graph']['nodes']['try']['edges']=[
           {'to':'end','when':{'var':'attempts','op':'ge','value':3}}]
        st=C.new_state(s,s['configurations'][0]);before=copy.deepcopy(st)
        with self.assertRaises(C.PhaseError):C.run_turn(st,s,{'technician':'retry'})
        self.assertEqual(st,before)
    def test_11_wykonanie_po_zakonczeniu_odrzucone(self):
        s=S['C0-RETRY'];st=C.new_state(s,s['configurations'][0])
        C.run_turn(st,s,{'technician':'retry'});C.run_turn(st,s,{'technician':'retry'})
        with self.assertRaises(C.PhaseError):C.run_turn(st,s,{'technician':'retry'})
    def test_12_korekta_informacyjna_B22_swiat_i_statusy_bez_zmian(self):
        old={s['id']:s for s in json.loads((ROOT/'B2_1_ARCHIWALNE_ZAMROZONE.json').read_text('utf-8'))}
        changes=0
        for sid in ('B2-CLINIC','B2-MUNICIPAL'):
            for cfg,seq in paths(OLD[sid]):
                b=B.execute(old[sid],cfg,seq)
                newer=B.execute(OLD[sid],cfg,seq)
                self.assertEqual(b['world'],newer['world'])
                self.assertEqual(b['actions'],newer['actions'])
                if b['knowledge']!=newer['knowledge']:
                    changes+=1
                    self.assertEqual(sid,'B2-MUNICIPAL')
                    self.assertEqual(cfg['id'],'HIGH_NO_VEHICLE')
                    self.assertEqual(seq[0]['crisis'],'shelter')
        self.assertEqual(changes,6)
    def test_13_regresja_kolejnosci_regul_2x108x3(self):
        n=0
        for sid in ('C0-CLINIC','C0-MUNICIPAL'):
            s=S[sid]
            for cfg,seq in paths(s):
                base=C.execute_graph(s,cfg,seq)
                key=(base['world'],base['actions'],base['knowledge'],base['positions'])
                for seed in range(3):
                    cp=copy.deepcopy(s);rng=random.Random(seed)
                    for t in cp['turns']:
                        for ph in B.PHASES:rng.shuffle(t.get(ph,[]))
                    tst=C.execute_graph(cp,cfg,seq)
                    self.assertEqual((tst['world'],tst['actions'],tst['knowledge'],tst['positions']),key)
                    n+=1
        self.assertEqual(n,324)

if __name__=='__main__':unittest.main(verbosity=2)
