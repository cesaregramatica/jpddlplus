# JPDDLPLUS: ONLD Heuristics for Numeric Planning

Questo repository contiene l'estensione del pianificatore ENHSP (basato su JPDDLPLUS API) con l'implementazione delle euristiche **ONLD** (*Ordered Numeric Landmark Distance*), sviluppate come progetto per il corso di Robotica.

## Panoramica del Progetto
L'obiettivo è migliorare la precisione della pianificazione numerica tramite l'uso di landmark ordinati e progressione dello stato sintetico.
Le principali innovazioni introdotte sono:
- **ONLD-Local** (`-h onld-local`): Stima di costo basata su contributi locali.
- **ONLD-HAdd** (`-h onld-hadd`): Stima di costo basata su euristica additiva globale.
- **Gestione Cicli SCC**: Fallback automatico su algoritmo di Kosaraju per dipendenze circolari tra landmark.
- **Priority Smearing**: Ottimizzazione della progressione numerica orientata ai landmark futuri.

## Prerequisiti
- **Java 16+** (consigliata versione 21)
- Tutte le dipendenze esterne sono incluse nella cartella `jar_dependencies/`.

## Compilazione
Per compilare il progetto e generare i file JAR (`enhsp25.jar` e `enhsp25-gui.jar`):
```bash
bash compile.sh
```

## Esecuzione
Per eseguire il pianificatore da riga di comando:
```bash
java -jar enhsp25.jar -o <dominio.pddl> -f <problema.pddl> -h <heuristica> -s <search_engine>
```
Esempio:
```bash
java -jar enhsp25.jar -o examples/pddl2_1/counters/domain.pddl -f examples/pddl2_1/counters/instance_4.pddl -h onld-hadd -s gbfs
```

## Demo Riproducibile
È disponibile uno script di demo che automatizza la compilazione e l'esecuzione di una serie di benchmark nel dominio *Counters*:
```bash
./demo_onld.sh
```

## Documentazione
La relazione tecnica completa e i risultati della valutazione sperimentale sono disponibili nella cartella `docs/`:
- `docs/relazione_progetto.md`: Relazione descrittiva completa (Introduzione, Metodologia, Risultati, Discussione).
- `docs/valutazione_sperimentale.md`: Dettaglio dei test e grafici di confronto.
- `docs/discussione_limiti.md`: Analisi di assunzioni e limiti teorici.
