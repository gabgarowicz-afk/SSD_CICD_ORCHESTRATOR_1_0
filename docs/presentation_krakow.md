# Deterministyczny formalizm decyzji incydentowych w podmiotach kluczowych sektora ochrony zdrowia
## Architektura odporna na audyt w świetle wymogów dyrektywy NIS 2 oraz normy ISO/IEC 27001

**Prelegenci:** Grzegorz Abgarowicz, dr Iwona Paciepnik  
**Miejsce:** Konferencja Naukowo-Szkoleniowa, Kraków  
**Projekt:** SSD_CICD_ORCHESTRATOR_1_0  

---

## Slajd 1: Tytuł i afiliacja
* **Tytuł:** Deterministyczny formalizm decyzji incydentowych w podmiotach kluczowych sektora ochrony zdrowia
* **Podtytuł:** Architektura odporna na audyt w świetle wymogów dyrektywy NIS 2 oraz normy ISO/IEC 27001
* **Prelegenci:** Grzegorz Abgarowicz, dr Iwona Paciepnik
* **Cel:** Przejście od deklaratywnego zarządzania incydentem w SOAR/SIEM do matematycznie weryfikowalnych dowodów stanu infrastruktury medycznej.

---

## Slajd 2: Problem badawczy – iluzja mitygacji w środowisku medycznym
* **Kluczowa teza:** Powszechny model reakcji na incydenty opiera się na deklaracjach proceduralnych personelu, a nie na weryfikacji stanu zasobów.
* **Kontekst prawny:** 
  * Art. 21 ust. 2 lit. c NIS 2 – bezwzględny wymóg skutecznej obsługi incydentów i ciągłości działania.
  * Art. 20 NIS 2 – bezpośrednia odpowiedzialność osobista kadry zarządzającej podmiotu kluczowego za zaniedbania.
* **Konflikt operacyjny:** Presja czasu personelu medycznego i powierzchowne odznaczanie zadań w workflow ticketowym (zjawisko pozornej mitygacji).

---

## Slajd 3: Luka dowodowa – dlaczego klasyczny audyt zawodzi
* **Badanie post factum:** Tradycyjny audyt weryfikuje jedynie dokumentację i oświadczenia analityków, a nie faktyczny stan sieci w momencie zdarzenia.
* **Brak integralności ścieżki decyzyjnej:** Podatność logów na błędy, opóźnienia telemetrii lub brak spójności chronologicznej.
* **Ryzyko prawne:** Niewykazanie należytej staranności przed organem nadzorczym (CSIRT sektorowy / Ministerstwo Zdrowia) w przypadku przestoju aparatury krytycznej.

---

## Slajd 4: Architektura formalna orkiestratora SSD
* **Paradygmat:** Zastąpienie heurystycznych reguł korelacyjnych deterministycznym grafem przejść stanów.
* **Bramkowanie logiczne (Gate Invariants):**
  * Stan MITIGATED nie jest etykietą tekstową, lecz węzłem osiągalnym wyłącznie po spełnieniu twardych warunków logicznych.
  * Reguła scenariusza B3: `ignored_count == 0` – blokada przejścia w stan bezpieczny przy jakimkolwiek niezweryfikowanym komponencie.
* **Powtarzalność:** 100% determinizmu – identyczny wektor wejściowy generuje niezmienny ślad decyzyjny w każdym środowisku wykonawczym.

---

## Slajd 5: Odporność łańcucha dostaw na audyt (art. 21 ust. 2 lit. d NIS 2)
* **Zagrożenie w łańcuchu dostaw:** Błędy, opóźnienia lub zafałszowania działań przez zewnętrznych dostawców usług zarządzanych (MDR, zewnętrzny SOC, serwisanci aparatury).
* **Kryptograficzny ślad wykonania (Execution Trace):**
  * Każdy krok decyzyjny i tranzycja stanu są pieczętowane skrótem SHA-256 wraz ze znacznikiem czasu i surową telemetrią.
  * Niezmienny plik `engine_report.json` generowany w potoku CI jako dowód cyfrowy dla audytora.
* **Spełnienie norm:** Realizacja wytycznych ISO/IEC 27001 (kontrole A.5.19–A.5.22) w zakresie niezależnej kontroli dostawców usług cyfrowych.

---

## Slajd 6: Weryfikacja mutacyjna – eliminacja dryfu semantycznego
* **Niewystarczalność testów jednostkowych:** Testy typu happy-path sprawdzają jedynie przewidziane scenariusze, ignorując ukryte luki logiczne.
* **Metodyka testowania mutacyjnego:**
  * Celowe wprowadzanie mutacji w operatorach logicznych (np. zamiana koniunkcji na alternatywę w procedurze odcinania segmentu z pompami infuzyjnymi).
  * Praktyczne wyniki z katalogu `artifacts/ssd_audit/B3_mutation_semantic`.
* **Wskaźnik zabicia mutantów (Mutation Kill Rate):** Dowód formalny, że orkiestrator natychmiast przerywa wykonanie na asercji przy jakiejkolwiek próbie ominięcia reguł bezpieczeństwa.

---

## Slajd 7: Studium przypadku – Scenariusz kliniczny B3
* **Symulacja incydentu:** Próba przedwczesnego zamknięcia incydentu sieciowego przy trwającym zagrożeniu w segmencie podtrzymywania życia.
* **Reakcja orkiestratora:** Automatyczne zatrzymanie procedury i odmowa przejścia do stanu bezpiecznego na poziomie potoku CI.
* **Artefakty dowodowe:** Demonstracja raportu `engine_report.json` i logów GitHub Actions jako gotowego pakietu dowodowego dla regulatora.

---

## Slajd 8: Wnioski i rekomendacje dla kadry zarządzającej
* **Nowy standard dowodowy:** Przeniesienie ciężaru dowodowego z deklaracji personelu na matematyczny dowód integralności operacyjnej.
* **Tarcza prawna dla zarządu (art. 20 NIS 2):** Deterministyczny orkiestrator jako obiektywny dowód dopełnienia należytej staranności w zarządzaniu ryzykiem.
* **Podsumowanie:** Bezpieczeństwo pacjenta wymaga automatyzacji opartej na niezmiennikach stanu, a nie na zaufaniu do manualnych procedur ticketowych.
