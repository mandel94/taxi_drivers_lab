{#- Fascia di eta' dell'articolo, calcolata alla data della metrica e non a oggi, cosi' i
    confronti tra periodi restano stabili. `age_days` e' un'espressione SQL intera >= 0. -#}
{% macro age_bucket(age_days) -%}
    case
        when {{ age_days }} <= 7   then '0-7'
        when {{ age_days }} <= 30  then '8-30'
        when {{ age_days }} <= 90  then '31-90'
        when {{ age_days }} <= 365 then '91-365'
        else '366+'
    end
{%- endmacro %}
