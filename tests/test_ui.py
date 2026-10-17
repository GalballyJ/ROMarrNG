"""The rendered page, as a browser reads it rather than as the source spells it."""

import json
import re
from html.parser import HTMLParser
from pathlib import Path

from romarr.ui import page, steam_result_page


class _InlineScriptParser(HTMLParser):
    """Collect script contents with the browser-tolerant HTML parser."""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.scripts: list[str] = []
        self._current_script: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "script":
            self._current_script = []

    def handle_data(self, data):
        if self._current_script is not None:
            self._current_script.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "script" and self._current_script is not None:
            self.scripts.append("".join(self._current_script))
            self._current_script = None


def _inline_scripts(html: str) -> list[str]:
    parser = _InlineScriptParser()
    parser.feed(html)
    parser.close()
    return parser.scripts


class _RenderedTextParser(HTMLParser):
    """Collect rendered text without treating tag-like content as markup."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._inside_hidden_tag = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in {"script", "style"}:
            self._inside_hidden_tag += 1

    def handle_endtag(self, tag):
        if tag.lower() in {"script", "style"} and self._inside_hidden_tag:
            self._inside_hidden_tag -= 1

    def handle_data(self, data):
        if not self._inside_hidden_tag:
            self.parts.append(data)


def _text(html: str) -> str:
    """Tags stripped -- what a reader actually sees."""
    parser = _RenderedTextParser()
    parser.feed(html)
    parser.close()
    return "".join(parser.parts)


def test_inline_script_extraction_handles_browser_tolerated_end_tags():
    assert _inline_scripts("<SCRIPT>inline</sCrIpT >") == ["inline"]
    assert _inline_scripts("<script>inline</script\t\n bar>") == ["inline"]
    assert _inline_scripts("<scripture>not inline</scripture>") == []


def test_the_brand_reads_romarr():
    """The brand is split across an element boundary so "arr" can carry the
    accent colour: `Rom<span>arr</span>`. That is exactly why the rename from
    Rommarr missed it, and why grepping the source for the old name finds
    nothing -- neither half contains it, only the rendering does.

    So this asserts on rendered text. A test against the source would have
    passed on the broken version.
    """
    html = page()
    brand = re.search(r'<div id="brand">(.*?)</div>', html, re.S)
    assert brand, "the page no longer has a brand element"
    assert _text(brand.group(1)).strip() == "ROMarr"


def test_the_old_name_appears_nowhere_a_user_can_read_it():
    assert "Rommarr" not in _text(page())


def test_the_document_title_is_the_product_name():
    assert re.search(r"<title>ROMarr</title>", page())


def test_interface_language_name_is_localized_and_fallback_content_stays_english():
    html = page()
    selector = re.search(
        r'<label[^>]*for="interface-language"[^>]*>.*?</label>\s*'
        r'(<select id="interface-language"[^>]*>.*?</select>)',
        html,
        re.S,
    )
    assert selector, "the language picker needs its visible associated label"
    assert 'aria-label="Interface language"' not in selector.group(1)
    assert 'value="ar"' in selector.group(1)
    assert '<html lang="en">' in html
    assert "document.documentElement.lang=language;" in html
    assert "document.documentElement.dir='ltr';" in html
    assert "el.dir=translated&&language==='ar'?'rtl':'ltr'" in html
    assert "el.lang=translated?language:'en'" in html


def test_library_and_search_labels_cover_selectable_interface_languages():
    from romarr.ui import UI_LABELS

    html = page()
    selector = re.search(r'<select id="interface-language"[^>]*>(.*?)</select>', html, re.S)
    assert selector
    selectable = set(re.findall(r'<option value="([^"]+)"', selector.group(1))) - {"en"}
    for label in ("On disk & catalogued", "Any source", "Enter a game name"):
        assert selectable <= UI_LABELS[label].keys(), f"{label} is missing translations"
    assert "if(!game){toastLabel('Enter a game name');return;}" in html


def test_interface_catalog_covers_every_locale_and_placeholder():
    from romarr.ui import UI_LABELS

    html = page()
    selector = re.search(r'<select id="interface-language"[^>]*>(.*?)</select>', html, re.S)
    assert selector
    locales = set(re.findall(r'<option value="([^"]+)"', selector.group(1))) - {"en"}
    assert locales == {
        "es", "zh-Hans", "hi", "de", "ja", "fr", "pt-BR", "ar",
        "ko", "zh-Hant", "vi", "id",
    }
    assert "UI_LABELS[source]?.[language]||source" in html

    for source, translations in UI_LABELS.items():
        assert set(translations) == locales, f"{source} has incomplete locale coverage"
        source_placeholders = sorted(re.findall(r"\{([A-Za-z][A-Za-z0-9_]*)\}", source))
        for locale, translated in translations.items():
            assert isinstance(translated, str) and translated.strip(), (
                f"{source} is empty in {locale}"
            )
            translated_placeholders = sorted(
                re.findall(r"\{([A-Za-z][A-Za-z0-9_]*)\}", translated)
            )
            assert translated_placeholders == source_placeholders, (
                f"{source} has placeholder mismatch in {locale}"
            )


def test_static_localization_helper_sources_exist_in_every_catalog():
    from romarr.ui import UI_LABELS

    source = (Path(__file__).parents[1] / "romarr" / "ui.py").read_text(
        encoding="utf-8"
    )
    call = re.compile(
        r"\b(?:interfaceMarkup|interfaceTemplateMarkup|toastLabel|toastMessage|"
        r"confirmMessage|promptMessage)\(\s*(['\"`])((?:\\\\.|(?!\1).)*?)\1",
        re.S,
    )
    referenced = {match.group(2) for match in call.finditer(source)}
    assert referenced <= UI_LABELS.keys(), sorted(referenced - UI_LABELS.keys())


def test_localization_catalog_rejects_duplicate_source_keys():
    catalog = Path(__file__).parents[1] / "romarr" / "ui-labels.json"

    def unique_object(pairs):
        out = {}
        for key, value in pairs:
            assert key not in out, f"duplicate localization source key: {key}"
            out[key] = value
        return out

    json.loads(catalog.read_text(encoding="utf-8"), object_pairs_hook=unique_object)


def test_backend_explanations_and_validation_errors_reach_localized_sinks():
    from romarr.ui import UI_LABELS

    root = Path(__file__).parents[1]
    ui = (root / "romarr" / "ui.py").read_text(encoding="utf-8")
    selection = (root / "romarr" / "selection.py").read_text(encoding="utf-8")
    collections = (root / "romarr" / "collections.py").read_text(encoding="utf-8")
    catalogue = (root / "romarr" / "catalogue.py").read_text(encoding="utf-8")
    app = (root / "romarr" / "app.py").read_text(encoding="utf-8")
    library = (root / "romarr" / "library.py").read_text(encoding="utf-8")
    sniff = (root / "romarr" / "sniff.py").read_text(encoding="utf-8")
    profiles = (root / "romarr" / "profiles.py").read_text(encoding="utf-8")

    required = {
        "seeders: {count}",
        "no seeders on a public tracker",
        "no seeders (private tracker, often temporary)",
        "title does not match {title}",
        "blocklisted: {reason}",
        "region {region}",
        "region {region} is {rank} of {count} in your preference",
        "region {region} is {rank} of {count} in your preference; it is the parent dump",
        "no dump matched your preferred regions, so the set keeps this one rather than losing the game",
        "unknown platform: {platform}",
        "search failed: {error}",
        "No usable release was found. Checked results: {count}.",
        "no such queue item",
        "that search has expired -- run it again",
        "release offers no usable download link",
        "could not tell which platform this belongs to; choose one",
        "{path} does not exist",
        "no {platform} ROM found; candidate count: {count}.",
        "already in the library",
        "unsafe game directory",
        "unsafe or duplicate game file",
        "game import failed: {error}",
        "download path does not exist in this container: {path}. Mount the download client's completed directory at that exact path, or add a remote path mapping under Settings -> Media Management.",
        "two files in this download are both called {name} ({first} and {second}); refusing to guess which one the game needs",
        "slug must be lower-case words joined by hyphens, e.g. my-plugin",
        "name is required",
        "description is required -- it is what somebody reads before deciding to run your code",
        "declare at least one capability, or nothing will ever call the plugin",
        "repository: no URL given",
        "repository: must be https -- plain http lets anyone on the network choose what code you run",
        "repository: no host in the URL",
        "repository: {host} is not an allowed source. Allowed: {allowed}. Add it under Settings if you host your own forge.",
        "repository: that is a host, not a repository",
        "iNES header (NES\\x1a)",
        "Nintendo 64 magic, {order}",
        "Nintendo logo at 0x104, CGB flag set",
        "Nintendo logo at 0x104",
        "Nintendo logo at 0x04",
        "SEGA console name at 0x100",
        "TMR SEGA signature at {offset} (Master System or Game Gear)",
        "ATARI7800 header",
        "LYNX header",
        "Wii disc magic at 0x18",
        "GameCube disc magic at 0x1c",
        "{format} compressed disc image (GameCube or Wii)",
        "Sega CD boot header at {offset}",
        "Saturn boot header at {offset}",
        "Dreamcast boot header at {offset}",
        "3DO opera filesystem header",
        "ISO9660 with a PLAYSTATION volume identifier (PlayStation or PS2)",
        "{reason} — confirmed by the header",
        "{reason} — chosen over {count} platforms sharing this extension",
        "{empty} of {sampled} sampled regions are empty, including the start — the file has its full size ({size} MB) and almost no content, which is what an interrupted download leaves behind",
        "blocked by the operator",
        "release profile prefers {term}",
        "excluded by release profile ({term})",
        "missing a required term ({term})",
    }
    assert required <= UI_LABELS.keys(), sorted(required - UI_LABELS.keys())
    assert "r.reasons.map(searchReasonMarkup)" in ui
    assert "collectionReasonMarkup(t.why)" in ui
    assert "appMessageMarkup(i.detail)" in ui
    assert "d.problems.map(appMessageMarkup)" in ui
    assert "no usable release among (\\d+) result\\(s\\)" in ui
    assert "no (.+) ROM among (\\d+) file\\(s\\)" in ui
    assert "f\"seeders: {release.seeders}\"" in selection
    assert "no dump matched your preferred regions, so the set keeps " in collections
    assert "slug must be lower-case words joined by hyphens" in catalogue
    assert "declare at least one capability" in catalogue
    assert "repository: {host} is not an allowed source" in ui
    assert "sniffedMessageTemplate" in ui
    assert "manualDiagnosticTitle(x.hollow)" in ui
    assert "manualDiagnosticTitle(x.header_detail||'')" in ui
    assert '"Nintendo logo at 0x104, CGB flag set"' in sniff
    assert '"Wii disc magic at 0x18"' in sniff
    assert 'f"release profile prefers {term!r}"' in profiles
    assert 'f"excluded by release profile ({term!r})"' in profiles
    assert 'f"missing a required term ({term!r})"' in profiles
    assert 'f"unknown platform: {platform_name!r}"' in app
    assert 'f"no {platform.name} ROM found; candidate count: {len(candidates)}."' in library
    assert 'f"two files in this download are both called {name!r}' in library


def test_manual_import_localizes_header_label_but_preserves_dat_value():
    source = (Path(__file__).parents[1] / "romarr" / "ui.py").read_text(
        encoding="utf-8"
    )
    assert "interfaceMarkup('Header says')" in source
    assert """lang="und" dir="auto">'+esc(x.header_says)""" in source
    assert """+'header says '+esc(x.header_says)""" not in source


def test_runtime_status_fallbacks_and_generated_hub_errors_have_catalog_coverage():
    from romarr.ui import UI_LABELS

    source = (Path(__file__).parents[1] / "romarr" / "ui.py").read_text(
        encoding="utf-8"
    )
    runtime_labels = {
        "Bad",
        "Streamed",
        "Ready — you both have the same dump",
        "Playable, with a caveat",
        "Same game, different dumps",
        "They do not have this dump",
        "ROMarr has not hashed your copy yet",
    }
    assert "bad:'Bad'" in source
    netplay = re.search(r"const head=\{(.*?)\}\[r\.status\]", source, re.S)
    assert netplay
    netplay_labels = set(re.findall(r":'([^']+)'", netplay.group(1)))
    assert runtime_labels - {"Bad", "Streamed"} <= netplay_labels
    assert netplay_labels <= UI_LABELS.keys()
    route_labels = set(re.findall(r"routeRow\('[^']+','([^']+)'", source))
    assert {"Browser emulator", "Streamed", "Download only"} <= route_labels
    assert route_labels <= UI_LABELS.keys()
    assert runtime_labels <= UI_LABELS.keys()

    download_states = re.search(
        r"const DOWNLOAD_STATE_LABELS=\{(.*?)\};", source, re.S
    )
    assert download_states
    assert set(re.findall(r":'([^']+)'", download_states.group(1))) <= UI_LABELS.keys()

    library_states = {"Unreachable", "Cannot read", "Path missing", "Connected"}
    assert all(f"'{label}'" in source for label in library_states)
    assert library_states <= UI_LABELS.keys()

    actions = {"install", "enable", "disable"}
    generated_errors = {
        f"Could not {action} {{slug}} (HTTP {{status}})."
        for action in actions
    } | {
        f"Could not {action} {{slug}}: {{error}}"
        for action in actions
    }
    assert "Could not ${action} {slug} (HTTP {status})." in source
    assert "Could not ${action} {slug}: {error}" in source
    assert generated_errors <= UI_LABELS.keys()


def test_static_select_labels_use_interface_catalog_markers():
    source = (Path(__file__).parents[1] / "romarr" / "ui.py").read_text(
        encoding="utf-8"
    )
    for label in (
        "unrated",
        "All platforms",
        "Torrent",
        "Usenet",
        "Library",
        "Wanted",
        "Blocklist",
        "platform (match on disk)",
        "Base games",
        "Updates",
        "All three",
    ):
        assert f'data-i18n="{label}"' in source, (
            f"static select option is missing its translation marker: {label}"
        )
    assert (
        "const marker=Object.hasOwn(UI_LABELS,source)?` data-i18n=\"${esc(source)}\"`:'';"
        in source
    )


def test_public_auth_and_invitation_messages_have_catalog_coverage():
    from romarr.ui import UI_LABELS, link_page, login_page

    sources = {
        "This ROMarr already has a password. Sign in instead.",
        "Use at least {count} characters.",
        "two-factor code required or wrong",
        "Send the link however you like -- it carries no secret. Send the code separately if you can: by voice, by text, in another app. It works once, expires in 15 minutes, and you still confirm the peer here before they can see anything.",
        "This invitation carries no address for your server, so your friend's ROMarr cannot call you back. Set your public URL under Settings -> General, then mint a fresh invitation.",
        "the claim code is missing. It travels separately from the link on purpose -- ask your friend for the eight characters",
        "that claim code has expired -- ask your friend for a fresh one, it only lives 15 minutes",
        "Connected to {friend}. They confirm you on their side before you can see anything.",
        "Connected to {friend}: {count} title with hashes ROMarr can match on.",
        "Connected to {friend}: {count} titles with hashes ROMarr can match on.",
    }
    assert sources <= UI_LABELS.keys()

    setup = login_page(claimed=False)
    assert "Use at least {count} characters." in setup
    assert "window.ROMarrI18n.has(detail)" in setup
    invitation = link_page()
    assert "Checking this invitation…" in invitation
    assert "window.ROMarrI18n.translate(msg)" in invitation


def test_standalone_steam_result_uses_public_localization_and_escapes_message():
    page_html = steam_result_page("connected", "<img src=x onerror=alert(1)>")
    assert 'data-i18n="Steam connected"' in page_html
    assert 'data-i18n="Back to Lists"' in page_html
    assert "romarrng.interface-language" in page_html
    assert 'lang="und" dir="auto">&lt;img src=x onerror=alert(1)&gt;' in page_html
    assert "<img src=x onerror=alert(1)>" not in page_html


def test_interface_language_choice_survives_storage_failure_for_current_tab():
    import shutil
    import subprocess
    import pytest

    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required to exercise browser language preferences")

    scripts = _inline_scripts(page())
    script = next(x for x in scripts if "const INTERFACE_LANGUAGE_KEY" in x)
    language_helpers = script[
        script.index("const $=s=>document.querySelector(s);") : script.index("const j=")
    ]
    change_handler = script[
        script.index("const languageSelect=$('#interface-language');") : script.index(
            "  bindTheme();"
        )
    ]
    harness = r"""
let changeLanguage, syncLanguage;
let storedLanguage = null;
let storageWritable = false;
const selector = {
  value: "en",
  addEventListener: (_name, handler) => { changeLanguage = handler; }
};
globalThis.navigator = {languages: ["en"], language: "en"};
globalThis.localStorage = {
  getItem: () => storedLanguage,
  setItem: (_key, value) => {
    if (!storageWritable) throw new Error("storage unavailable");
    storedLanguage = String(value);
  }
};
globalThis.window = {
  addEventListener: (_name, handler) => { syncLanguage = handler; }
};
globalThis.Node = {ELEMENT_NODE: 1, TEXT_NODE: 3};
globalThis.NodeFilter = {SHOW_TEXT: 4};
globalThis.MutationObserver = class {
  observe() {}
};
const emptyElement = {
  nodeType: Node.ELEMENT_NODE,
  matches: () => false,
  closest: () => null,
  getAttribute: () => null,
  querySelectorAll: () => []
};
globalThis.document = {
  documentElement: {},
  nodeType: 9,
  body: emptyElement,
  querySelector: name => name === "#interface-language" ? selector : null,
  querySelectorAll: () => [],
  createTreeWalker: () => ({nextNode: () => false})
};
""" + language_helpers + change_handler + r"""
selector.value = "de";
changeLanguage();
applyInterfaceLanguage();
const storageFailureChoice = readInterfaceLanguage();
storageWritable = true;
selector.value = "es";
changeLanguage();
const successfulWriteChoice = readInterfaceLanguage();
storedLanguage = null;
syncLanguage({key: null, newValue: null});
const clearFallback = readInterfaceLanguage();
const selectedAfterClear = selector.value;
storedLanguage = "fr";
syncLanguage({key: INTERFACE_LANGUAGE_KEY, newValue: storedLanguage});
const crossTabLanguage = readInterfaceLanguage();
console.log(JSON.stringify({
  storageFailureChoice,
  successfulWriteChoice,
  crossTabLanguage,
  clearFallback,
  selectedAfterClear,
  selected: selector.value
}));
"""
    result = subprocess.run(
        [node, "-e", harness], text=True, capture_output=True, timeout=15
    )
    assert result.returncode == 0, result.stderr
    assert '"storageFailureChoice":"de"' in result.stdout
    assert '"successfulWriteChoice":"es"' in result.stdout
    assert '"crossTabLanguage":"fr"' in result.stdout
    assert '"clearFallback":"en"' in result.stdout
    assert '"selectedAfterClear":"en"' in result.stdout
    assert '"selected":"fr"' in result.stdout


def test_the_libraries_page_is_in_the_nav_and_rendered():
    """A feature configured only by hand-editing settings.json is not one most
    people can use."""
    html = page()
    assert 'data-page="libraries"' in html
    assert "RENDER.libraries" in html
    # The generic editor is driven by kind, so the library kind has to be known
    # to the schema cache or Add silently does nothing.
    assert "library: {}" in html
    assert "libraries:'Libraries'" in html


def test_the_status_page_names_each_library_rather_than_saying_romm():
    """With several libraries a hardcoded "RomM" row is both wrong and less
    informative than naming the servers actually configured."""
    html = page()
    assert "h.libraries||[]" in html


def test_a_list_field_round_trips_through_the_form():
    """Platform routing rules are a list. Without list handling the form would
    save the string "n64, snes" as a single platform name that matches nothing.
    """
    html = page()
    assert "f.type === 'list'" in html
    assert "el.dataset.list ? el.value.split(',')" in html


def test_the_system_page_explains_and_builds_the_ggrequestz_webhook():
    html = page()
    assert "GG Requestz page" in html
    assert "reachability only; request delivery is configured below" in html
    assert "REQUEST_WEBHOOK_URL=" in html
    assert "new URL('/api/v1/webhook/ggrequestz'" in html
    assert "target.searchParams.set('apikey',d.api_key)" in html
    assert "base.value=''" in html
    assert "base.oninput" in html
    assert "copy.disabled=true" in html
    assert "request.auto_approve" in html


def test_plugin_install_errors_are_displayed_in_the_hub():
    """A failed install used to refresh the catalogue and erase the API error."""
    html = page()
    assert "let q='', cap='', inst='', actionError=null" in html
    assert "if(!r.ok||result.ok!==true)" in html
    assert "const detail=result.error||result.reason" in html
    assert "actionError=detail?{raw:detail}" in html
    assert "actionError.source" in html
    assert "interfaceTemplateMarkup(actionError.source,actionError.values)" in html
    assert "<span lang=\"und\" dir=\"auto\">" in html


def test_every_rendered_inline_script_parses_as_javascript():
    """Upstream #48: one bad help string disabled the entire dashboard."""
    import shutil
    import subprocess
    import pytest
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required to syntax-check rendered JavaScript")
    scripts = _inline_scripts(page())
    assert scripts
    for script in scripts:
        checked = subprocess.run([node, "--check"], input=script, text=True,
                                 capture_output=True, timeout=15)
        assert checked.returncode == 0, checked.stderr


def test_browser_regional_formatting_helpers_and_settings_markup():
    """Locale selection persists in this browser and drives Intl formatting."""
    import json
    import shutil
    import subprocess
    import pytest

    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required to exercise browser formatting helpers")

    html = page()
    scripts = _inline_scripts(html)
    script = next(x for x in scripts if "const REGIONAL_FORMAT_KEY" in x)
    start = script.index("const esc=")
    end = script.index("\nlet PLATFORMS=", start)
    helpers = script[start:end]
    harness = r"""
const memory = new Map();
let storageAvailable = true;
let storageWritable = true;
const UI_LABELS = {};
const readInterfaceLanguage = () => "en";
const translateLabel = source => source;
globalThis.localStorage = {
  getItem: key => {
    if (!storageAvailable) throw new Error("storage unavailable");
    return memory.has(key) ? memory.get(key) : null;
  },
  setItem: (key, value) => {
    if (!storageAvailable || !storageWritable) throw new Error("storage unavailable");
    memory.set(key, String(value));
  },
  removeItem: key => {
    if (!storageAvailable) throw new Error("storage unavailable");
    memory.delete(key);
  }
};
let refreshCountCalls = 0;
const refreshCounts = () => { refreshCountCalls += 1; };
""" + helpers + r"""
const saved = applyRegionalFormat("de");
const refreshAfterSave = refreshCountCalls;
const failedWriteControl = {value: "ja"};
storageWritable = false;
const writeFailureResult = applyRegionalFormat(failedWriteControl.value, failedWriteControl);
const failedWriteMarkup = regionalFormatField();
const writeFailureHandled = writeFailureResult
  && failedWriteControl.value === "ja" && getRegionalLocale() === "ja"
  && /value="ja"[^>]* selected/.test(failedWriteMarkup)
  && refreshCountCalls === refreshAfterSave + 1;
storageWritable = true;
applyRegionalFormat("de");
const number = fmt(1234567.89);
const date = regionalDate("2026-10-12");
const leapDay = regionalDate("2024-02-29");
const invalidIsoDate = regionalDate("2026-02-31");
const invalidIsoMonth = regionalDate("2026-13-01");
const anniversary = regionalDate("10-12");
const invalidAnniversary = regionalDate("02-31");
const timestamp = regionalDateTime("2026-10-12T00:00:00Z");
const invalidTimestamp = regionalDateTime("2026-02-31T00:00:00Z");
const month = regionalMonth("2026-10");
const invalidMonth = regionalMonth("2026-13");
const year = regionalYear(2026);
const unknownYear = regionalYear("not-a-year");
const selectedMarkup = regionalFormatField();
const refreshBeforeInvalid = refreshCountCalls;
const invalidRejected = !applyRegionalFormat("not-a-locale")
  && getRegionalLocale() === "de" && refreshCountCalls === refreshBeforeInvalid;
const resetSaved = applyRegionalFormat("system");
const systemLocale = getRegionalLocale() ?? null;
const systemMarkup = regionalFormatField();
const storedAfterSystemReset = memory.get(REGIONAL_FORMAT_KEY) ?? null;
const refreshBeforeStorageFailure = refreshCountCalls;
const failedControl = {value: "ja"};
storageAvailable = false;
const storageFailureResult = applyRegionalFormat(failedControl.value, failedControl);
const failedStorageMarkup = regionalFormatField();
const storageFailureHandled = storageFailureResult
  && failedControl.value === "ja" && getRegionalLocale() === "ja"
  && /value="ja"[^>]* selected/.test(failedStorageMarkup)
  && refreshCountCalls === refreshBeforeStorageFailure + 1;
storageAvailable = true;
const expectedDate = new Intl.DateTimeFormat("de", {
  timeZone: "UTC"
}).format(new Date(Date.UTC(2026, 9, 12)));
const expectedLeapDay = new Intl.DateTimeFormat("de", {
  timeZone: "UTC"
}).format(new Date(Date.UTC(2024, 1, 29)));
const expectedAnniversary = new Intl.DateTimeFormat("de", {
  month: "short", day: "numeric", timeZone: "UTC"
}).format(new Date(Date.UTC(2000, 9, 12)));
const expectedTimestamp = new Date("2026-10-12T00:00:00Z").toLocaleString("de");
const expectedMonth = new Intl.DateTimeFormat("de", {
  month: "long", year: "numeric", timeZone: "UTC"
}).format(new Date(Date.UTC(2026, 9, 1)));
console.log(JSON.stringify({
  saved,
  resetSaved,
  writeFailureHandled,
  storageFailureHandled,
  refreshAfterSave,
  refreshCountCalls,
  locale: "de",
  numberMatches: number === new Intl.NumberFormat("de").format(1234567.89),
  dateMatches: date === expectedDate,
  leapDayMatches: leapDay === expectedLeapDay,
  invalidIsoDatePreserved: invalidIsoDate === "2026-02-31",
  invalidIsoMonthPreserved: invalidIsoMonth === "2026-13-01",
  anniversaryMatches: anniversary === expectedAnniversary
    && !/\b\d{4}\b/.test(anniversary),
  invalidAnniversaryPreserved: invalidAnniversary === "02-31",
  timestampMatches: timestamp === expectedTimestamp,
  invalidTimestampPreserved: invalidTimestamp === "2026-02-31T00:00:00Z",
  monthMatches: month === expectedMonth,
  invalidMonthPreserved: invalidMonth === "2026-13",
  yearMatches: year === new Intl.NumberFormat("de", {useGrouping: false}).format(2026),
  unknownYearPreserved: unknownYear === "not-a-year",
  invalidRejected,
  systemLocale,
  storedAfterSystemReset,
  accessible: selectedMarkup.includes('aria-describedby="g-regional-format-help"')
    && selectedMarkup.includes('id="g-regional-format-help"'),
  germanOptionSelected: /<option value="de"[^>]* selected>/.test(selectedMarkup),
  systemOptionSelected: /<option value="system"[^>]* selected>/.test(systemMarkup)
    && systemMarkup.includes('data-i18n="Use browser settings"')
}));
"""
    checked = subprocess.run(
        [node, "-e", harness], text=True, capture_output=True, timeout=15
    )
    assert checked.returncode == 0, checked.stderr
    result = json.loads(checked.stdout)
    assert result["saved"] is True
    assert result["resetSaved"] is True
    assert result["writeFailureHandled"]
    assert result["storageFailureHandled"]
    assert result["refreshAfterSave"] == 1
    assert result["refreshCountCalls"] == 5
    assert result["locale"] == "de"
    assert result["numberMatches"]
    assert result["dateMatches"]
    assert result["leapDayMatches"]
    assert result["invalidIsoDatePreserved"]
    assert result["invalidIsoMonthPreserved"]
    assert result["anniversaryMatches"]
    assert result["invalidAnniversaryPreserved"]
    assert result["timestampMatches"]
    assert result["invalidTimestampPreserved"]
    assert result["monthMatches"]
    assert result["invalidMonthPreserved"]
    assert result["yearMatches"]
    assert result["unknownYearPreserved"]
    assert result["invalidRejected"]
    assert result["systemLocale"] is None
    assert result["storedAfterSystemReset"] is None
    assert result["accessible"]
    assert result["germanOptionSelected"]
    assert result["systemOptionSelected"]

    # A JavaScript escape here used to render the two characters "\\n"
    # between the selector and the next setting.
    assert "regionalFormatField()}" + chr(92) + "n   <div" not in html
    assert "applyRegionalFormat(regionalFormat.value,regionalFormat);" in html


def test_regional_formatting_is_applied_at_dashboard_count_call_sites():
    """Formatting helpers must reach the visible values that claim to use them."""
    html = page()
    assert "if(setRegionalLocale(regionalFormat.value)) refreshCounts();" not in html
    assert "regionalFormat.onchange=()=>{\n      applyRegionalFormat(regionalFormat.value,regionalFormat);" in html
    assert "if(setRegionalLocale(regionalFormat.value)) go('general')" not in html
    assert "★ ${num(x.rating)}" in html
    assert "'Clear {count} failed'" in html
    assert "<div><b>${fmt(h.platforms)}</b><span>Platforms</span></div>" in html
    assert "<div><b>${fmt(h.dats||0)}</b><span>DATs loaded</span></div>" in html
    assert "<div><b>${fmt(h.dat_games||0)}</b><span>Known dumps</span></div>" in html
    assert "<div><b>${fmt(h.events)}</b><span>History events</span></div>" in html
    assert "+fmt(x.percent)+'% — '+statusMarkup(x.status)" in html
    assert "+fmt(x.done)+'</td><td>'+fmt(x.failed)+'</td><td>'+fmt(x.remaining)" in html
    assert "interfaceTemplateMarkup('Page {page} of {pages}'" in html
    assert "${fmt(r.local||0)}" in html
    assert "${fmt(r.stream||0)}" in html
    assert "${fmt(r.archive||0)}" in html
    assert "${fmt(r.download_only||0)}" in html
    assert "minutes:fmt(Math.max(0,Math.round((r.code_expires_in||0)/60)))" in html
    assert "Math.max(1,Math.round(left/60))" in html
    assert "fmt(p.max_size_mb/1024)+' GB' : fmt(p.max_size_mb)+' MB'" in html
    assert "interfaceTemplateMarkup('Interval: {count} min'" in html
    assert "interfaceTemplateMarkup('Interval: {count} s'" in html
    assert "interfaceTemplateMarkup('Disabled until {date}'" in html
