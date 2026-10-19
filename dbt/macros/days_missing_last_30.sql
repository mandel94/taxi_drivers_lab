{#- Quanti giorni degli ultimi 30 (fino a ieri) non hanno nessuna riga nella tabella.
    Parte da `start_date`: prima di quella data la copertura non e' attesa.
    Calcolato sempre rispetto a oggi, cosi' una pipeline ferma fa salire il numero. -#}
{% macro days_missing_last_30(relation, date_column, start_date) -%}
(
    select count(*)
    from generate_series(
            greatest(current_date - 30, '{{ start_date }}'::date)::timestamp,
            (current_date - 1)::timestamp,
            interval '1 day') as g(d)
    where g.d::date not in (select distinct {{ date_column }} from {{ relation }})
)
{%- endmacro %}
