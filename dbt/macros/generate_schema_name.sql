{#-
  Usa il nome dello schema cosi' com'e' (staging, intermediate, marts) invece di
  concatenarlo allo schema di default (che darebbe public_marts).
-#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
