-- =====================================================================
-- Verifiche post-ingestion (run di test con MAX_PAGES=3, 300 articoli)
-- =====================================================================


-- 1. CONTEGGI DI BASE
-- Atteso: 300 articoli, 269 categorie (come da log), articles_categories > 0
SELECT
  (SELECT COUNT(*) FROM articles_dim) AS totale_articoli,
  (SELECT COUNT(*) FROM categories_dim) AS totale_categorie,
  (SELECT COUNT(*) FROM articles_categories) AS totale_associazioni;


-- 2. UN ARTICOLO A CAMPIONE, CONTROLLO CAMPI CHIAVE
-- Verifica che content_html non sia vuoto/NULL, che le date siano popolate,
-- che author_wp_id/author_name siano coerenti.
SELECT
  article_id, slug, title, status,
  LEFT(content_html, 80) AS content_preview,
  LENGTH(content_html) AS content_length,
  author_wp_id, author_name,
  featured_media_url,
  published_at, modified_at
FROM articles_dim
ORDER BY published_at DESC
LIMIT 5;


-- 3. ARTICOLI SENZA CONTENUTO O SENZA DATA
-- Atteso: 0 righe. Se ce ne sono, vale la pena capire perché (es. articoli
-- con status diverso da publish che sono comunque passati).
SELECT article_id, slug, status, content_html IS NULL AS content_nullo, published_at
FROM articles_dim
WHERE content_html IS NULL OR content_html = '' OR published_at IS NULL;


-- 4. GERARCHIA CATEGORIE: verifica che il fix a due passate abbia funzionato
-- Controlla che esistano categorie con parent_id valorizzato (non tutto NULL)
-- e che ogni parent_id punti a una categoria realmente esistente (la FK lo
-- garantirebbe comunque, ma è una controprova diretta).
SELECT
  COUNT(*) FILTER (WHERE parent_id IS NOT NULL) AS categorie_con_padre,
  COUNT(*) FILTER (WHERE parent_id IS NULL) AS categorie_radice,
  COUNT(*) AS totale
FROM categories_dim;

-- Esempio concreto: la sottocategoria live-streaming-on-demand deve avere
-- come padre la categoria "review" (id 218), stesso caso che ha causato
-- l'errore FK corretto in questa sessione.
SELECT c.category_id, c.name, c.slug, c.parent_id, p.name AS nome_padre
FROM categories_dim c
LEFT JOIN categories_dim p ON p.category_id = c.parent_id
WHERE c.slug = 'live-streaming-on-demand';


-- 5. UN ARTICOLO CON LE SUE CATEGORIE ASSOCIATE
-- Verifica che il join articles_dim -> articles_categories -> categories_dim
-- restituisca nomi sensati, non solo ID.
SELECT
  a.article_id, a.title, a.slug,
  string_agg(c.name, ', ' ORDER BY c.name) AS categorie
FROM articles_dim a
JOIN articles_categories ac ON ac.article_id = a.article_id
JOIN categories_dim c ON c.category_id = ac.category_id
GROUP BY a.article_id, a.title, a.slug
ORDER BY a.article_id DESC
LIMIT 5;


-- 6. ARTICOLI SENZA NESSUNA CATEGORIA ASSOCIATA
-- Non necessariamente un errore (un articolo potrebbe davvero non avere
-- categorie sul sito), ma utile sapere quanti sono.
SELECT COUNT(*) AS articoli_senza_categoria
FROM articles_dim a
WHERE NOT EXISTS (
  SELECT 1 FROM articles_categories ac WHERE ac.article_id = a.article_id
);


-- 7. IDEMPOTENZA: controlla che non ci siano articoli o categorie duplicati
-- Atteso: 0 righe in entrambe le query (le PK/UNIQUE dovrebbero già
-- impedirlo, ma è una controprova diretta sui dati reali).
SELECT article_id, COUNT(*) FROM articles_dim GROUP BY article_id HAVING COUNT(*) > 1;
SELECT category_id, COUNT(*) FROM categories_dim GROUP BY category_id HAVING COUNT(*) > 1;