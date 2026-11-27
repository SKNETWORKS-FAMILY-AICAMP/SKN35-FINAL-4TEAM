-- OpenAI Standard text rates for gpt-4.1-mini: USD 0.40 input / 1.60 output per 1M tokens.
-- https://developers.openai.com/api/docs/models/gpt-4.1-mini
-- FX reference: 2026-11-26, KRW 1,343.90 per USD.
INSERT INTO sa_settings (scope, scope_ref, key, value, note)
SELECT 'global', '', 'price.gpt-4.1-mini',
       '{"in_per_1k_krw": 0.53756, "out_per_1k_krw": 2.15024}'::jsonb,
       'OpenAI Standard, USD 0.40/1.60 per 1M tokens, USD/KRW 1343.90 (2026-11-26)'
WHERE NOT EXISTS (
    SELECT 1 FROM sa_settings
    WHERE scope = 'global' AND scope_ref = '' AND key = 'price.gpt-4.1-mini'
);
