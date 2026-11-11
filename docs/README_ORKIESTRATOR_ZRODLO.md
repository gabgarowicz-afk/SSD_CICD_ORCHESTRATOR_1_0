# Pakiet audytora konstrukcyjnego SSD — instrukcja dla orkiestratora

**Wersja:** 1.0 · 10.11.2026

| Plik | Rola |
|---|---|
| `AUDYTOR_SYSTEM_PROMPT.md` | Parametr `system` wywołania Claude API (komentarz HTML na początku można usunąć) |
| `raport_audytu.schema.json` | JSON Schema (draft 2020-12) odpowiedzi audytora |
| `przyklad_raportu_FAIL.json` | Przykład raportu zgodnego ze schematem; zbudowany na rzeczywistym błędzie silnika B2.2 dla mutacji scenariusza urzędu (`scenario_sha256` w przykładzie jest zastępczy) |
| `INWARIANTY_M2_v0.3.md` | Inwarianty INV-01…INV-16 z oznaczeniem, które sprawdza kod silnika |

## Kolejność kroków w potoku

1. **Najpierw silnik, potem AI.** Uruchom kod deterministyczny:
   - `validate_definition` / `static_information_audit`;
   - pełna enumeracja konfiguracji × ścieżek wyborów;
   - test przetasowań reguł;
   - testy regresji.

   Wynik przekaż jako `<engine_report>`. Bez enumeracji audytor zwróci `ESCALATE_HUMAN` (`INCOMPLETE_INPUT`), i tak ma być.
2. Wywołaj audytora:
   - `temperature: 0`;
   - przypięta wersja modelu;
   - komunikat użytkownika z blokami `<run_context>`, `<scenario_json>`, `<engine_report>`, opcjonalnie `<engine_diff>` i `<previous_report>`.
3. **Zweryfikuj odpowiedź, zanim jej użyjesz:**
   - parsowanie JSON i walidacja ze schematem; przy błędzie jedno ponowienie, potem `ESCALATE_HUMAN`;
   - `run_context` w raporcie identyczny z wysłanym;
   - w `checks` każdy INV-01…INV-16 dokładnie raz (schemat sprawdza tylko liczbę 16, nie unikalność).
4. **Nie ufaj samemu polu `status`. Przelicz go w orkiestratorze:**
   - błąd w `engine_report` → `FAIL`, niezależnie od tego, co zwrócił model;
   - zmiana w plikach silnika → co najmniej `ESCALATE_HUMAN`;
   - jeżeli przeliczony status różni się od statusu modelu, przyjmij surowszy i zapisz rozbieżność.
5. **Pętla generator ↔ audytor:**
   - przekazuj generatorowi wyłącznie `generator_feedback.items` i `remediation` ustaleń z `target: GENERATOR`;
   - limit `max_iterations` = 3; po jego przekroczeniu sprawa trafia do człowieka.
6. Archiwizuj raport razem z SHA-256 scenariusza, silnika i promptu.

## Czego potok nie zastępuje

- `PASS_CONSTRUCTION` nie jest walidacją ani zatwierdzeniem (M1 3.5, 3.8; D-21).
- Scenariusz po `PASS_CONSTRUCTION` nadal ma `validation_status: AI_CONSTRUCTION_ONLY`. Zmienić go może tylko protokół etapu D.
- Generator (model OpenAI) i audytor (Claude) to dwa systemy AI. Ich zgodność nie spełnia wymogu niezależnej weryfikacji przez ludzi.

## Schemat w prompcie (od wersji promptu 1.1)

Prompt zawiera pełny schemat raportu, bo instancja w API nie ma dostępu do plików. Plik `raport_audytu.schema.json` jest tym samym schematem i służy orkiestratorowi do walidacji. Przy każdej zmianie schematu podmień oba miejsca i przelicz SHA-256 promptu.

Alternatywa: zdefiniuj narzędzie `submit_audit_report` z `input_schema` = ten schemat i wymuś jego użycie (`tool_choice`). Część konstrukcji draft 2020-12 (`if/then`, `allOf`) może nie być egzekwowana po stronie API, więc walidacja w orkiestratorze pozostaje obowiązkowa.
