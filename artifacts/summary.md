# Raport Walidacji Deterministycznej Potoku CI/CD
**Projekt:** SSD_CICD_ORCHESTRATOR_1_0
**Wersja silnika (runner_version):** SSD-ENGINE-RUNNER 1.0
**Suma kontrolna silnika (SHA256):** `c39bf9b8a9d452a5e6387ee9e94f66214d570199930f5778a84808104f0d3450`
**Data wykonania:** 2026-11-11 15:28:08
**Status integralnoĹ›ci:** ZGODNY / BRAK REGRESJI / ODPORNOĹšÄ† SEMANTYCZNA POTWIERDZONA

---

## 1. Zbiorcze Metryki Wykonawcze

| Parametr weryfikacji | Scenariusze B2 | Scenariusze C0 | Scenariusze B3 (NIS 2) | ĹÄ…cznie |
| :--- | :--- | :--- | :--- | :--- |
| **Zbadane Ĺ›cieĹĽki decyzyjne** | 108 | 122 | 54 | 284 |
| **Wykonane permutacje (shuffles)** | 324 | 366 | 162 | 852 |
| **KompletnoĹ›Ä‡ enumeracji** | True | True | True | TAK |
| **Regresje sekwencyjne** | True | True | True | BRAK |
| **BĹ‚Ä™dy silnika wykonawczego** | False | False | False | 0 |

---

## 2. Wyniki Audytu Semantycznego i InvariantĂłw

### Domena B2 (Migracje Konstrukcyjne)
- Scenariusz: B2-CLINIC | ĹšcieĹĽki: 54 | BĹ‚Ä™dy definicji: 0 | OstrzeĹĽenia efektĂłw: 0
- Scenariusz: B2-MUNICIPAL | ĹšcieĹĽki: 54 | BĹ‚Ä™dy definicji: 0 | OstrzeĹĽenia efektĂłw: 0

### Domena C0 (Scenariusze Grafowe)
- Scenariusz: C0-CLINIC | ĹšcieĹĽki: 54 | BĹ‚Ä™dy definicji: 0 | OstrzeĹĽenia efektĂłw: 0
- Scenariusz: C0-MUNICIPAL | ĹšcieĹĽki: 54 | BĹ‚Ä™dy definicji: 0 | OstrzeĹĽenia efektĂłw: 0
- Scenariusz: C0-RETRY | ĹšcieĹĽki: 7 | BĹ‚Ä™dy definicji: 0 | OstrzeĹĽenia efektĂłw: 0
- Scenariusz: C0-DUO | ĹšcieĹĽki: 7 | BĹ‚Ä™dy definicji: 0 | OstrzeĹĽenia efektĂłw: 0

### Domena B3 (ZgodnoĹ›Ä‡ z DyrektywÄ… NIS 2 - Podmioty Kluczowe)
- Scenariusz: B3-CLINIC-NIS2 | ĹšcieĹĽki: 54 | BĹ‚Ä™dy definicji: 0 | OstrzeĹĽenia efektĂłw: 0

---

## 3. Audyt OdpornoĹ›ci Semantycznej (Negative Mutation Testing)

| Test mutacyjny | Cel reguĹ‚y | Oczekiwany kod wyjĹ›cia | Otrzymany status | Wynik walidacji |
| :--- | :--- | :--- | :--- | :--- |
| B3-MUTATION-SEMANTIC-VIOLATION | ReguĹ‚a PROTECTED_EFFECT_AT_SELECTION (ochrona zmiennej restytucyjnej bez zgody zarzÄ…du) | 2 (INVALID_DEFINITION) | BĹ‚Ä…d definicji przechwycony przez information_audit | **ZALICZONY** |

---
*Raport wygenerowany automatycznie przez procedurÄ™ potoku CI/CD orkiestratora.*