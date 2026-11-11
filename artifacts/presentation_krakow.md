# Formalne Bramkowanie Stanów w Grafie Decyzyjnym a Dyrektywa NIS 2
**Konferencja:** Kurza wiada, Kraków, listopad 2026
**Autorzy:** dr Michał Tuz, dr Iwona Paciepnik

---

## Slajd 1: Teza badawcza – Problem pozornej mitygacji w sektorze medycznym (NIS 2)

### Kontekst normatywny
* Art. 23 Dyrektywy (UE) 2022/2555 (NIS 2) nakłada na podmioty kluczowe bezwzględny obowiązek wczesnego ostrzegania (24 h) oraz powiadamiania o incydencie poważnym (72 h).
* W praktyce szpitalnej (systemy HIS, PACS, poczta korporacyjna) kluczowym czynnikiem ryzyka pozostaje błąd ludzki w fazie wstępnego triażu anomalii.

### Zjawisko „pozornej mitygacji” (*illusory mitigation*)
* W klasycznych symulatorach decyzyjnych użytkownik może pominąć detekcję wektora ataku (np. zignorować anomalię w Turze 1), a w fazie końcowej zlecić blokadę konta i uzyskać fałszywy status opanowania incydentu.
* Taki model fałszuje ocenę dojrzałości operacyjnej organizacji i prowadzi do naruszenia rygorów audytowych.

### Teza
* Skuteczność działań naprawczo-restytucyjnych w modelu cyberbezpieczeństwa musi być ściśle uwarunkowana zachowaniem łańcucha dowodowego (*chain of custody*) i nie może zachodzić w oderwaniu od rzetelności wczesnego triażu.

---

## Slajd 2: Aparat formalny – Bramkowanie stanów w deterministycznym grafie decyzyjnym

### Struktura tranzycji w silniku regułowym
* Zamiast traktować akcję restytucyjną jako bezwarunkowy wyzwalacz zmiany stanu, model wprowadza koniunkcję predykatów w definicji reguły decyzyjnej:
  Transition(s, a_restore) <=> Action(a_restore) AND PreconditionsMet(s)

### Predykat gatingu stanu
* Zmiana stanu chronionego (`mailbox_secured = true`) jest blokowana, jeśli w trajektorii wystąpiło zignorowanie wczesnych symptomów:
  PreconditionsMet(s) <=> var(ignored_count) == 0 AND var(mailbox_compromised) == true

### Weryfikacja maszynowa i testy mutacyjne
* Deterministyczna ewaluacja 54 ścieżek scenariusza wykazuje brak false-positive: przy wyborze `ignore` akcja kończy się statusem `ZLECONE`, a zmienna `mailbox_secured` pozostaje w stanie `False`.
* Negatywne testy mutacyjne (*semantic mutation testing*) potwierdzają, że próba ominięcia bramki skutkuje natychmiastowym kodem błędu `INVALID_DEFINITION` na poziomie potoku CI/CD.

---

## Slajd 3: Wnioski i implikacje dla podmiotów kluczowych

### Wymuszenie rygoru proceduralnego w placówkach medycznych
* Wyeliminowanie retrospektywnej racjonalizacji: podjęcie procedury naprawczej przez administratora IT nie maskuje pierwotnego błędu personelu medycznego.
* Pełna zgodność z zasadą rozliczalności (RODO art. 5 ust. 2 oraz NIS 2 art. 21/23).

### Wartość dowodowa w procesie audytu i nadzoru CSIRT
* Automatyczne rozróżnienie pomiędzy incydentem opanowanym proceduralnie a incydentem, w którym doszło do kompromitacji danych pacjenta wskutek opóźnionej reakcji.
* Narzędzie obiektywnej weryfikacji kompetencji personelu bez ryzyka powstawania martwych procedur papierowych.

### Konkluzja wdrożeniowa
* Deterministyczne grafy decyzyjne z bramkowaniem logicznym stanowią niezawodny fundament pod budowę certyfikowanych systemów zarządzania bezpieczeństwem informacji (ISO/IEC 27001, KSC) w podmiotach leczniczych.

## Sekcja V: Formalizm dowodowy i linia obrony przed audytem (NIS 2 / ISO 27001)

### 1. Przełamanie zarzutu pozornej mitygacji (art. 21 ust. 2 lit. c NIS 2)
* Zarzut audytora / recenzenta: W jaki sposób organizacja dowodzi, że zamknięcie incydentu w SOAR/SIEM było rzeczywistą mitygacją podatności infrastrukturalnej, a nie jedynie zmianą statusu zgłoszenia w warstwie workflow?
* Wymóg normatywny: Art. 21 ust. 2 lit. c NIS 2 (zarządzanie incydentami i ciągłość działania) w powiązaniu z art. 20 (odpowiedzialność osobista zarządu) oraz normą ISO/IEC 27001 (kontrole A.5.24 - A.5.28). Zgodność wymaga wykazania stanu faktycznego na poziomie zasobów, a nie deklaratywnego odznaczenia procedury.
* Rozwiązanie orkiestratora: Zmiana stanu systemu na MITIGATED jest bramkowana twardą asercją logiczną w grafie decyzyjnym (scenariusz B3_CLINIC_NIS2.json wymusza ignored_count == 0). Dopóki telemetria aparatury medycznej wykazuje niezweryfikowane komponenty lub nieobsłużone wektory, graf blokuje przejście w stan bezpieczny. Mitygacja stanowi wynik dowodu formalnego, a nie decyzję dyskrecjonalną analityka.

### 2. Nienaruszalność łańcucha dowodowego w relacji z dostawcą (art. 21 ust. 2 lit. d NIS 2)
* Zarzut audytora / recenzenta: Jak wykazać należytą staranność przed organem nadzorczym (CSIRT sektorowy / Ministerstwo Zdrowia) w przypadku incydentu mającego źródło w zewnętrznej usłudze zarządzanej (MDR / zewnętrzny SOC)?
* Wymóg normatywny: Art. 21 ust. 2 lit. d NIS 2 (bezpieczeństwo łańcucha dostaw) oraz wytyczne KSC i ISO/IEC 27001 (A.5.19 - A.5.22). Podmiot kluczowy ma obowiązek niezależnej weryfikacji operacji prowadzonych przez kontrahenta w jego strefie sieciowej.
* Rozwiązanie orkiestratora: Każdy krok decyzyjny i tranzycja stanu są kryptograficznie pieczętowane skrótem SHA-256 i powiązane z surową telemetrią. Wygenerowany w potoku CI raport engine_report.json tworzy nierozerwalny, deterministyczny ślad wykonania (execution trace), uniemożliwiający dostawcy usług manipulację historią zdarzeń lub zatajenie opóźnień w reakcji.

### 3. Odporność na dryf semantyczny i testowanie mutacyjne (art. 21 ust. 2 lit. a, e NIS 2)
* Zarzut audytora / recenzenta: Dlaczego klasyczne testy jednostkowe reguł detekcji i korelacji są niewystarczające w środowisku szpitalnym o wysokim profilu ryzyka dla zdrowia i życia?
* Wymóg normatywny: Art. 21 ust. 2 lit. a oraz e NIS 2 (analiza ryzyka, audyt techniczny i odporność systemów). Weryfikacja musi uwzględniać odporność na ciche degradacje reguł logicznych (semantic drift).
* Rozwiązanie orkiestratora: Wdrożenie testów mutacyjnych w potoku CI (katalog artifacts/ssd_audit/B3_mutation_semantic). Celowe zaburzenia operatorów logicznych (np. zamiana koniunkcji na alternatywę w procedurze odcinania segmentu z pompami infuzyjnymi) muszą zostać natychmiast przechwycone przez orkiestrator jako naruszenie kontraktu semantycznego. Wskaźnik zabicia mutantów (mutation kill rate) stanowi dowód braku ukrytych ścieżek obejścia nadzoru.
