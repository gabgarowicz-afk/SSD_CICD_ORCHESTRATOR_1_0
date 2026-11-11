# Raport Walidacji Deterministycznej Potoku CI/CD
**Projekt:** SSD_CICD_ORCHESTRATOR_1_0
**Wersja silnika (runner_version):** SSD-ENGINE-RUNNER 1.0
**Suma kontrolna silnika (SHA256):** `c39bf9b8a9d452a5e6387ee9e94f66214d570199930f5778a84808104f0d3450`
**Data wykonania:** 2026-11-11 15:36:32
**Status integralnosci:** ZGODNY / BRAK REGRESJI / ODPORNOSC SEMANTYCZNA POTWIERDZONA

---

## 1. Zbiorcze Metryki Wykonawcze

| Parametr weryfikacji | Scenariusze B2 | Scenariusze C0 | Scenariusze B3 (NIS 2) | Scenariusz D0 (Silent Drop) | Lacznie |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Zbadane sciezki decyzyjne** | 108 | 122 | 54 | 2 | 286 |
| **Wykonane permutacje (shuffles)** | 324 | 366 | 162 | 6 | 858 |
| **Kompletnosc enumeracji** | True | True | True | True | TAK |
| **Regresje sekwencyjne** | True | True | True | True | BRAK |
| **Bledy silnika wykonawczego** | False | False | False | False | 0 |

---

## 2. Wyniki Audytu Semantycznego i Invariantow

### Domena B2 (Migracje Konstrukcyjne)
- Scenariusz: `B2-CLINIC` | Sciezki: 54 | Bledy definicji: 0 | Ostrzezenia efektow: 0
- Scenariusz: `B2-MUNICIPAL` | Sciezki: 54 | Bledy definicji: 0 | Ostrzezenia efektow: 0

### Domena C0 (Scenariusze Grafowe)
- Scenariusz: `C0-CLINIC` | Sciezki: 54 | Bledy definicji: 0 | Ostrzezenia efektow: 0
- Scenariusz: `C0-MUNICIPAL` | Sciezki: 54 | Bledy definicji: 0 | Ostrzezenia efektow: 0
- Scenariusz: `C0-RETRY` | Sciezki: 7 | Bledy definicji: 0 | Ostrzezenia efektow: 0
- Scenariusz: `C0-DUO` | Sciezki: 7 | Bledy definicji: 0 | Ostrzezenia efektow: 0

### Domena B3 (Zgodnosc z Dyrektywa NIS 2 - Podmioty Kluczowe)
- Scenariusz: `B3-CLINIC-NIS2` | Sciezki: 54 | Bledy definicji: 0 | Ostrzezenia efektow: 0

### Domena D0 (Odpornosc na degradacje telemetrii i ciche awarie wezla)
- Scenariusz: `D0-SILENT-FAILURE` | Sciezki: 2 | Bledy definicji: 0 | Ostrzezenia efektow: 0

---

## 3. Audyt Odpornosci Semantycznej (Negative Mutation Testing)

| Test mutacyjny | Cel reguly | Oczekiwany kod wyjscia | Otrzymany status | Wynik walidacji |
| :--- | :--- | :--- | :--- | :--- |
| `B3-MUTATION-SEMANTIC-VIOLATION` | Regula `PROTECTED_EFFECT_AT_SELECTION` (ochrona zmiennej restytucyjnej bez zgody zarzadu) | 2 (INVALID_DEFINITION) | Bledy definicji przechwycone przez information_audit | **ZALICZONY** |

---
*Raport wygenerowany automatycznie przez procedure potoku CI/CD orkiestratora.*