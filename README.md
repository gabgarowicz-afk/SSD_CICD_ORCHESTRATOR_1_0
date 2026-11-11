# SSD CI/CD — orkiestrator audytu konstrukcyjnego 1.0

**Status:** wykonywalny pakiet implementacyjny, testowany lokalnie z silnikiem referencyjnym B2.2/C0. **Nie jest to zatwierdzenie M2 ani niezależna walidacja etapu D.**

## Zawartość

- `ssd_ci/models.py` — modele Pydantic v2 zgodne ze schematem `SSD-AUDIT-REPORT 1.0` (decydującym walidatorem pozostaje Draft202012Validator).
- `ssd_ci/scenario.py` — struktury scenariusza M2 v0.3 B2.2/C0: R/K, `ordinary/protected`, `effect_owner`, bramka tylko na obserwacji K, `wait/defer/omit`, fazy, obserwacje i graf.
- `ssd_ci/runner.py` — adapter istniejącego, niezmodyfikowanego silnika, pełna enumeracja konfiguracji × wyborów, kontrole statyczne, przetasowania reguł, testy regresji.
- `ssd_ci/clients.py` — bezpośredni klient Anthropic Messages (`temperature=0`) oraz klient OpenAI Responses do propozycji poprawek.
- `ssd_ci/orchestrator.py` — potok, XML, SHA-256, schema validation, polityka statusów, ograniczona pętla samonaprawcza.
- `ssd_ci/cli.py` — polecenia `check` (bez API) i `run` (z API).
- `assets/engine_ref/` — **historyczny silnik C0**: wyłącznie demonstracja integracyjna; NIE jest nową wersją silnika C1.
- `assets/scenarios/` — dwa pełne scenariusze B2.2 i cztery konstrukcyjne grafy C0.
- `assets/schema/raport_audytu.schema.json` — oryginalny schemat użytkownika, bez zmian.
- `.github/workflows/ssd-ci.yml` — przykładowy potok GitHub Actions, krok kosztowy uruchamiany tylko ręcznie.

## Instalacja

```bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows PowerShell: .venv\\Scripts\\Activate.ps1
pip install -e '.[test]'
python -m pytest -q
```

## Deterministyczna kontrola bez kluczy API

```bash
python -m ssd_ci check \
  --scenarios assets/scenarios/B2_GABINET_URZAD_MIGRACJE_KONSTRUKCYJNE.json \
  --engine-root assets/engine_ref \
  --shuffles 3 --max-paths 2000 --output artifacts/check_B22
```

Dla C0:

```bash
python -m ssd_ci check --output artifacts/check_C0
```

Wynik `engine_report.json` zawiera **wszystkie** osiągnięte ścieżki wraz z kontekstem, stanami końcowymi i SHA-256 rezultatu, a także błędy i wyniki regresji. Jeżeli nie można wykonać całej enumeracji, status `enumeration_complete` jest fałszywy. Żadna niejawna próba losowa nie zastępuje pełnej enumeracji.

## Audyt Claude i pętla OpenAI — wymaga dostarczonego promptu

W **załącznikach nie było** pliku `AUDYTOR_SYSTEM_PROMPT.md v1.1`, przykładowego raportu ani `INWARIANTY_M2_v0.3.md`. Nie wymyślono ich zawartości. Przed faktycznym wywołaniem API przekaż prawdziwy prompt v1.1, zawierający pełny schemat raportu. Zainstalowana aplikacja nie potrzebuje plików inwariantów do wykonania silnika, ale audyt semantyczny Claude musi mieć ich definicje w swoim rzeczywistym prompcie.

```bash
export ANTHROPIC_API_KEY='...'
export OPENAI_API_KEY='...'
python -m ssd_ci run \
  --scenarios assets/scenarios/B2_GABINET_URZAD_MIGRACJE_KONSTRUKCYJNE.json \
  --engine-root assets/engine_ref \
  --engine-baseline assets/engine_ref/BASELINE_ENGINE_SHA256.txt \
  --schema assets/schema/raport_audytu.schema.json \
  --prompt /bezpieczna/sciezka/AUDYTOR_SYSTEM_PROMPT.md \
  --claude-model 'PRZYP_I_PINNED_MODEL' \
  --openai-model 'PRZYP_I_PINNED_MODEL' \
  --max-iterations 3 --output artifacts/audit_run
```

`--disable-autofix --max-iterations 1` uruchamia wyłącznie kontrolę i Claude. Model Claude musi być jednoznacznie określoną wersją w danym środowisku. Kluczy nie należy umieszczać w kodzie, skryptach, konfiguracji ani artefaktach.

## Polityka potoku

1. Faktyczny silnik uruchamia się **zawsze przed Claude**. Błędy silnika mają pierwszeństwo przed oceną AI.
2. `scenario_sha256` = SHA-256 **kanonicznego UTF-8 JSON wysyłanego do audytora**, a `source_scenario_sha256` archiwizuje hash oryginalnych bajtów wejściowych. `engine_sha256` = hash ustalonej listy czterech plików silnika (nazwa/długość/zawartość). `auditor_prompt_sha256` = hash dokładnych bajtów przesłanego promptu.
3. Claude dostaje XML z `run_context`, `scenario_json`, `engine_report`, opcjonalnie `engine_diff`, `previous_report`. Znaki specjalne w danych są escapowane.
4. Raport przechodzi `jsonschema` draft 2020-12, modele Pydantic v2, porównanie całego `run_context`, unikalność szesnastu INV oraz sprawdzenie dowodów deterministycznych. Jeden błędny raport jest ponawiany, potem `ESCALATE_HUMAN` (błąd silnika nadal oznacza `FAIL`).
5. **Zasada statusów:** `FAIL` przy błędzie silnika lub inwariancie FAIL / ustaleniu MAJOR/BLOCKER; zmiana silnika min. `ESCALATE_HUMAN`; przerwana enumeracja bez błędu silnika -> `ESCALATE_HUMAN`. Nigdy nie zaakceptuj łagodniejszej oceny Claude.
6. Generator OpenAI dostaje **tylko** `generator_feedback.items` dla ustaleń `target=GENERATOR` i pola `instruction`/`must_not` takich `remediation`. Nie dostaje pełnego raportu ani stanu świata. Może zaproponować wyłącznie `add`/`replace` wewnątrz `/scenariusz/turns/...`. Nigdy nie może zmienić kodu silnika, konfiguracji, identyfikatorów, `effect_role` lub `effect_owner`.
7. **Samonaprawa to tylko próba konstrukcyjna:** każda wersja scenariusza zapisywana w `iteration_XX/scenario.canonical.json`, oryginał jest nietknięty; każda poprawka uruchamia pełny runner od zera. Po 3 próbach nierozwiązany `FAIL` eskalowany jest człowiekowi; status `FAIL` nie jest przy tym rozmiękczany.
8. `PASS_CONSTRUCTION` i zgodność dwóch systemów AI nie są walidacją M1. `validation_status` nie może być automatycznie zmieniony na zatwierdzony. Akceptacja etapu D pozostaje po stronie ludzi.
9. Należy chronić katalog `artifacts/`, ponieważ zawiera stany świata i wiedzę postaci. Może być dostępny w CI tylko dla uprawnionych. Klient Claude otrzymuje scenariusz oraz pełne stany, które mogą zawierać informacje poufne — nie przekazuj danych rzeczywistych bez odpowiedniej oceny ochrony informacji.

## Znane granice wdrożenia

- Nie wykonano **realnego wywołania Anthropic ani OpenAI**: brak kluczy i prawdziwego promptu audytora. Testy klientów i pętli używają kontrolowanych atrap.
- Nie dołączono `INWARIANTY_M2_v0.3.md`; model enumeruje identyfikatory INV-01…INV-16, ale treści musi dostarczyć skonfigurowany Claude.
- C0 wymaga synchronizacji aktywnych szablonów tury: niesynchronizowane wielowątkowe grafy to prace C1, a nie funkcja niniejszego kodu.
- Przekazywanie wyłącznie informacji z `generator_feedback` ogranicza możliwości generatora; remediacje muszą podawać wystarczająco precyzyjne ścieżki. Jeśli nie można bezpiecznie naprawić scenariusza, eskalacja jest prawidłowym rezultatem.
- Limity rozmiaru wiadomości i enumeracji powodują jawne zatrzymanie i eskalację, a nie obcięcie danych.

## Osadzanie w CI/CD

W `.github/workflows/ssd-ci.yml` testy lokalne są wykonywane dla PR i `push`, a API Claude/OpenAI uruchamia się **wyłącznie na ręczne żądanie**. Ustaw sekrety `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` i `SSD_AUDITOR_PROMPT_B64`, zmienne `CLAUDE_MODEL_ID` i `OPENAI_MODEL_ID`. Dla prawidłowej identyfikowalności przypinaj także wersje pakietów Python i skróty `uses:` działań GitHub przed wdrożeniem produkcyjnym. Zmiany referencyjnego kodu silnika wymagają jawnej aktualizacji i przeglądu bazowego SHA-256, nie automatycznego nadpisania.
