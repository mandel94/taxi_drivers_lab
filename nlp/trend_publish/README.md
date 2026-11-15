# trend_publish: dal testo del Trend Radar all'HTML per WordPress

Pacchetto del flusso che prende il testo di un Trend Radar scritto da Manuel e, in tre fasi, produce:

1. **Correzione grammaticale** del solo testo, con rapporto (`grammar.py`).
2. **Link**: interni verso articoli di taxidrivers.it scelti per punteggio editoriale, esterni verificati, corsivo sui titoli (`link_resolver.py`, `sources.py`, `linker.py`, `external_links.py`).
3. **HTML copia-incollabile** nella forma del sito (editor classico) con titoli H2 (`wp_html.py`).

I moduli sono puri: nessuna rete e nessun database. Le fonti (database, API di WordPress, HTTP) si iniettano come funzioni, così i test usano dati finti. Il giudizio (cosa è un errore grammaticale, quale fonte esterna, quale titolo H2, pertinenza di un link) lo danno i sottoagenti della skill `td-trend-radar-publish`; questi moduli lo applicano soltanto dopo averlo controllato.

Convenzioni del sito che il codice rispetta (dai Trend Radar pubblicati):
- titolo dell'opera in corsivo; alla **prima citazione** è un link in grassetto-corsivo;
- persone e festival non si linkano; nessun link in intro e nello sguardo d'insieme (salvo `scope="any"`);
- i link esterni non hanno attributi `rel` o `target`;
- HTML: `<p><span style="font-weight: 400;">…</span></p>`, `<h2><strong>…</strong></h2>`, link `<a href><em><strong>Titolo</strong></em></a>`.

Python 3.12; solo libreria standard e `beautifulsoup4` (nei test).

## Contratto delle interfacce

### `doc.py`

```python
@dataclass
class Section:
    kind: str            # 'intro' | 'section' | 'pdl' | 'sguardo'
    title: str | None    # None per l'intro
    paragraphs: list[str]
    items: list[str]     # solo per 'pdl'

@dataclass
class Draft:
    sections: list[Section]
    def to_markdown(self) -> str: ...
    def plain_blocks(self) -> list[str]: ...

def parse_draft(text: str) -> Draft
def markdown_to_draft(md: str) -> Draft
```

`parse_draft` legge il testo incollato (righe separate da `\n`, righe vuote ripetute, spazi finali):

- prima del primo titolo c'è la sezione `intro` (`title=None`); ogni riga non vuota è un paragrafo;
- una **riga titolo** è una riga non vuota senza punto finale (`.` `!` `?` `:`), con al massimo 14 parole, seguita da almeno un'altra riga non vuota; oppure è uguale (ignorando maiuscole, due punti finali e apostrofo dritto o curvo) a «Prima di lasciarci» o «Uno sguardo d'insieme»;
- dopo «Prima di lasciarci» la sezione è `pdl`, con titolo canonico `Prima di lasciarci` (senza due punti); ogni riga non vuota è un item (anche senza punto finale) fino a «Uno sguardo d'insieme»;
- «Uno sguardo d'insieme» è `sguardo` (titolo conservato come scritto, solo `strip()`), con i paragrafi come le sezioni normali;
- tutte le altre sezioni sono `section`;
- il testo dei paragrafi si conserva identico (doppi spazi compresi), con `strip()` solo agli estremi.

`to_markdown()`: paragrafi dell'intro separati da una riga vuota; poi per ogni sezione `## <titolo>`, riga vuota, paragrafi separati da una riga vuota; per `pdl` l'elenco `- item`, una riga per voce. Un solo `\n` finale. `markdown_to_draft` è l'inverso (prima dei titoli `##` c'è l'intro; le righe `- ` sono item).
`plain_blocks()`: paragrafi e item in ordine, senza titoli.

### `link_resolver.py`

```python
def normalize_title(s: str) -> str
def quoted_titles(article_title: str) -> list[tuple[str, int | None]]
def matches_entity(article_title: str, entity: dict) -> bool
def section_of(link: str) -> str
def is_si_fara(link: str) -> bool
def eligible_score(scores: list[dict], min_users: int = 15) -> float | None

@dataclass
class Choice:
    article_id: int | None
    link: str | None
    title: str | None
    reason: str
    score: float | None
    alternatives: list[dict]

def choose_article(entity, candidates, today, min_users=15, recent_days=14) -> Choice
def choose_si_fara(entity, candidates) -> Choice
```

- `normalize_title`: `html.unescape`, casefold, via gli accenti, uniforma apostrofi e virgolette, ogni carattere non `[a-z0-9]` diventa spazio, spazi collassati.
- `quoted_titles`: titoli tra virgolette in un titolo di articolo, in qualunque posizione. Dopo `html.unescape`, i caratteri di virgoletta sono `‘ ’ “ ” '`. Si ignorano (non sono virgolette): un carattere con una lettera o una cifra subito prima **e** subito dopo (`l'essere`, `Don’t`), e un apostrofo seguito da due cifre e da un non-lettera (`'27`). Gli altri caratteri di virgoletta si appaiano in sequenza (il primo col secondo, il terzo col quarto), così anche una virgoletta di apertura usata per sbaglio come chiusura (`‘Look Back ‘di Kore-eda`) chiude il titolo. Ritorna `(testo normalizzato, numero di stagione | None)`. Il numero è quello che chiude il titolo dentro le virgolette (`'Black Doves 2'` → `("black doves", 2)`) oppure subito dopo la virgoletta di chiusura (`'Black Doves' 2: …` → `("black doves", 2)`). Un numero di 4 cifre (`2001`) non è mai una stagione e resta nel titolo.
- `matches_entity`: `entity = {"title": str, "aliases": list[str] (opz.), "season": int | None (opz.)}`. True se un titolo tra virgolette, normalizzato, è **uguale** (mai sottostringa) al titolo o a un alias normalizzati. Se `entity["season"]` è un intero e l'articolo ha un numero di stagione diverso: False; se l'articolo non ha numero: True.
- `section_of`: primo segmento del percorso dopo l'id (`…/564645/serie-tv/x.html` → `serie-tv`; `…/561788/latest-news/si-fara/a.html` → `latest-news`).
- `is_si_fara`: `si-fara` è un segmento del percorso.
- `eligible_score`: `scores = [{"editorial_score": float, "active_users": int}, …]` (una per settimana); massimo `editorial_score` tra quelle con `active_users >= min_users`; `None` se nessuna.
- `choose_article`: `candidate = {"article_id", "title", "link", "pub_date": date, "scores": [...]}`. Si tengono i candidati con `matches_entity`. Regole in ordine:
  1. **recensione recente:** candidati con `section_of(link) == "review"`, `pub_date >= today - recent_days` e senza `eligible_score` → vince la più recente; reason `"recensione recente senza score"`;
  2. **score:** tra i candidati con `eligible_score` vince il massimo (a parità la `pub_date` più recente); reason `"score massimo"`;
  3. **fallback:** il più recente tra quelli che corrispondono (a parità: sezione `review`, poi `serie-tv`); reason `"nessun articolo sopra soglia: il più recente"`;
  4. nessun candidato: `Choice(None, None, None, "nessun articolo", None, [])`.
  `alternatives`: fino a 3 altri candidati corrispondenti `{"article_id","title","link","score"}`, per score decrescente (`None` in fondo).
- `choose_si_fara`: solo candidati con `is_si_fara(link)` e titolo tra virgolette uguale al titolo o agli alias **ignorando** la stagione; vince la `pub_date` più recente; reason `"articolo Si farà"`; se nessuno, `"nessun articolo Si farà"`.

### `sources.py`

```python
def candidates_from_db(query_fn, entity) -> list[dict]
def candidates_from_wp(http_get_json, entity, since: date) -> list[dict]
def merge_candidates(db, wp) -> list[dict]
```

- `query_fn(sql: str, params: dict) -> list[dict]` è iniettata. Una sola query su `articles_dim` con `LEFT JOIN fact_article_score_period` (`method_version = 'balanced-v2'`) e `ILIKE` sul titolo e sugli alias; i candidati escono nel formato di `choose_article`, con `scores` raggruppate per articolo e `pub_date` come `date`. Righe senza punteggio: `scores = []`.
- `http_get_json(url: str) -> list[dict]` è iniettata. Chiama `/wp-json/wp/v2/posts?search=<titolo>&per_page=20&after=<since>T00:00:00&_fields=id,date,link,title` (url-encoded) per il titolo e per ogni alias; titolo = `html.unescape(title["rendered"])`; `scores = []`.
- `merge_candidates`: unione per `article_id`; vince la riga DB; ordine stabile (prima DB, poi WP).

### `grammar.py`

```python
ALLOWED_CATEGORIES = frozenset({"ortografia", "accento", "apostrofo", "doppie", "concordanza",
                                "tempo_verbale", "congiuntivo", "preposizione", "articolo", "refuso"})

@dataclass
class Edit:
    id: str
    original: str
    replacement: str
    category: str
    reason: str

@dataclass
class Rejection:
    edit: Edit
    reason: str

def validate_edits(text, edits, protected=()) -> tuple[list[Edit], list[Rejection]]
def apply_edits(text, accepted) -> str
def only_listed_changes(original, corrected, accepted) -> bool
def render_report(accepted, rejected, doubts) -> str
```

`validate_edits` rifiuta un edit (motivo esatto) se:
- categoria fuori da `ALLOWED_CATEGORIES` → `"categoria non ammessa"`;
- `original` vuoto o assente nel testo → `"frammento assente"`;
- `original` presente più di una volta → `"frammento ambiguo"`;
- `original == replacement` → `"nessuna modifica"`;
- l'intervallo si sovrappone a un frammento protetto (le stringhe di `protected`, cercate nel testo; un link Markdown `[..](..)`; un URL) → `"tocca una zona protetta"`;
- più di 4 parole diverse tra `original` e `replacement` (confronto per parole) → `"modifica troppo estesa"`;
- si sovrappone a un edit già accettato → `"sovrapposto a un'altra modifica"`.

Gli edit validi sono `accepted`, nell'ordine di input. Gli spazi doppi e la forma dei nomi propri **non** sono categorie ammesse: si segnalano come dubbi, non si modificano.

- `apply_edits`: applica tutte le modifiche accettate alle posizioni trovate nel testo originale, senza altri cambi.
- `only_listed_changes`: True solo se ogni differenza carattere per carattere (`difflib`) tra `original` e `corrected` cade dentro l'intervallo di un edit accettato.
- `render_report`: Markdown con titolo `# Correzioni grammaticali`; riga di riepilogo `N correzioni applicate, M rifiutate, K dubbi non toccati`; tabella (prima | dopo | categoria | motivo) raggruppata per categoria con il conteggio; sezione `## Rifiutate` con il motivo; sezione `## Dubbi (non modificati)` con `doubts = [{"fragment", "note"}]`. Con zero correzioni: `Nessuna correzione necessaria.`

### `linker.py`

```python
@dataclass
class LinkSpec:
    surface: str
    url: str
    scope: str = "body"   # 'body' | 'pdl' | 'any'

def apply_internal_links(draft, specs) -> tuple[Draft, list[dict]]
def italicize_titles(draft, surfaces) -> Draft
def apply_external_links(draft, picks) -> tuple[Draft, list[dict]]
```

- `apply_internal_links`: per ogni spec cerca la **prima** occorrenza esatta di `surface` nelle sezioni consentite dallo scope (`body`: solo paragrafi di sezioni `section`; `pdl`: solo item; `any`: tutti i paragrafi e gli item, esclusi i titoli), non già dentro un link Markdown, e la sostituisce con `[***surface***](url)`. Un url si usa una sola volta (lo spec successivo con lo stesso url è scartato). Non tocca titoli né le sezioni `intro` e `sguardo` (salvo `any`). Rapporto: una voce per spec `{"surface", "url", "applied": bool, "where": "<indice sezione>/<indice paragrafo o item>" | None, "reason"}`. Funzione pura: il `Draft` in input non cambia.
- `italicize_titles`: avvolge in `*…*` ogni occorrenza non già in un link o in corsivo di ciascuna surface, anche nei titoli di sezione, con le surface più lunghe per prime; non annida corsivi.
- `apply_external_links`: `picks = [{"anchor", "url"}]`; l'ancora deve comparire **esattamente una volta** nei paragrafi di sezioni `section`, fuori da link e da titoli; altrimenti non si applica (reason `"ancora assente"` o `"ancora ambigua"`). Inserisce `[anchor](url)` senza attributi. Ritorna `Draft` e rapporto.

### `external_links.py`

```python
@dataclass
class UrlCheck:
    ok: bool
    status: int | None
    final_url: str | None
    found_text: bool
    reason: str

def verify_url(url, expect_text, http_get) -> UrlCheck
def pick_external(candidates, min_links=2, max_links=3, blacklist=()) -> tuple[list[dict], bool]
```

- `http_get(url) -> (status: int, final_url: str, text: str)` è iniettata e può lanciare eccezioni (`ok=False`, reason con il messaggio). `ok` solo se `status == 200`, lo schema è `https` e `normalize_title(expect_text)` compare come sottostringa di `normalize_title(text)`.
- `pick_external`: `candidate = {"url", "anchor", "authority": int, "check": UrlCheck}`. Scarta `check.ok == False` e i domini in `blacklist` (dominio = host senza `www.`). Un solo link per dominio. Ordina per `authority` decrescente. Ritorna `(scelti fino a max_links, satisfied)` con `satisfied = len(scelti) >= min_links`.

### `wp_html.py`

```python
def to_wp_html(draft: Draft) -> str
def build_cf_html(fragment: str) -> bytes
```

- `to_wp_html`, un blocco per riga:
  - intro e paragrafi: `<p><span style="font-weight: 400;">TESTO</span></p>`;
  - titolo di sezione (`section` e `sguardo`): `<h2><strong>TESTO</strong></h2>`;
  - `pdl`: `<h2><strong>Prima di lasciarci</strong></h2>` e poi `<ul><li>TESTO</li>…</ul>`;
  - inline Markdown: `[***T***](u)` → `<a href="u"><em><strong>T</strong></em></a>`; `[*T*](u)` → `<a href="u"><em>T</em></a>` (come le voci di «Prima di lasciarci»); `[t](u)` → `<a href="u">t</a>`; `*x*` → `<em>x</em>`; `**x**` → `<strong>x</strong>`; nel titolo H2 il corsivo resta `<em>` dentro `<strong>`;
  - escape di `&`, `<`, `>` (le virgolette tipografiche restano); `&` negli URL come `&amp;`;
  - nessun `<script>`, `<style>`, `<iframe>`; nessun paragrafo vuoto.
- `build_cf_html`: formato "HTML Format" degli appunti di Windows: intestazione `Version:0.9`, `StartHTML`, `EndHTML`, `StartFragment`, `EndFragment` (otto cifre con zeri a sinistra, offset in byte UTF-8), poi `<html><body><!--StartFragment-->FRAMMENTO<!--EndFragment--></body></html>`. Gli offset puntano esattamente ai marcatori.
