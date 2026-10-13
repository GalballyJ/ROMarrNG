# UI localization roadmap

## Existing support and verified gap

ROMarrNG has no human-language UI catalogs or language selector in the reachable source and pull-request history. The existing translation policy, translation-language filter, and `Translations/` ROM subfolder are about fan-translated game dumps; they are library behavior and must not be repurposed as an interface language setting. The interface is rendered by the Python service in `romarr/ui.py`.

## Implementation plan

1. Extract server-rendered UI labels and browser-side messages into a small Python-backed catalog module with one English source. Keep the current HTML/JavaScript architecture; do not add a frontend framework for this.
2. Add a Display Language field under Settings > General. Register it in the app's default settings, persist it with the existing app settings, apply changes on the next render, and expose the chosen locale in the page's `lang` attribute.
3. Use the selected locale for dates, counts, and plural forms while preserving ROM names, platform slugs, filenames, paths, DAT values, and user data exactly.
4. Add locales in the ranked order below, keeping English fallback for any untranslated key and a check for missing keys and placeholder mismatches.
5. Before Arabic is marked supported, set document `dir=rtl`, convert layout rules to logical properties where needed, and inspect Settings, Library, collection plans, import flows, login/first-run, and invitation pages at narrow and desktop widths.

## First-pass locale order

This is a practical rollout order, not a claim about these apps' actual user base. Product-level language analytics are not available. It combines global speaker estimates with online-content usage, and keeps the requested Arabic and Asian-language coverage in the first waves:

1. Spanish (es; es-MX where the product already distinguishes it)
2. Simplified Chinese (zh-Hans / zh-CN)
3. Hindi (hi)
4. German (de)
5. Japanese (ja)
6. French (fr)
7. Brazilian Portuguese (pt-BR)
8. Arabic (ar; requires right-to-left layout support)
9. Korean (ko)
10. Traditional Chinese (zh-Hant / zh-TW)
11. Vietnamese (vi)
12. Indonesian (id)

The World Bank's 2025 report estimates Mandarin Chinese, Hindi, and Spanish at 15%, 7.6%, and 6.9% of the global population respectively; its online-content data also places German, Chinese, and Japanese among the leading languages. [World Bank, Digital Progress and Trends Report 2025](https://documents1.worldbank.org/curated/en/099112525160536089/pdf/P505350-59c98ca8-0803-4f23-b470-17f3dab010ab.pdf). W3Techs tracks website content-language share rather than app users. [W3Techs content-language survey](https://w3techs.com/technologies/cross/content_language/ranking). Reorder this list if maintainers later receive reliable demand signals.

## Translation boundaries and acceptance

Translate interface labels, help, empty states, validation, notifications, and errors. Keep media titles, user names, filenames and paths, commands, API identifiers, protocol values, and other user-supplied content unchanged. Use the selected UI language for date, time, number, and plural formatting. Every locale must fall back to English for a missing key; CI should check placeholder parity and report missing strings. Arabic ships only after the app sets `lang` and `dir`, uses logical layout properties, and verifies the core workflows, login/first-run, and invitation pages in RTL at narrow and desktop widths.
