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
