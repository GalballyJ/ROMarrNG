"""The rendered page, as a browser reads it rather than as the source spells it."""

import re

from romarr.ui import page


def _text(html: str) -> str:
    """Tags stripped -- what a reader actually sees."""
    return re.sub(r"<[^>]+>", "", html)


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
    assert "let q='', cap='', inst='', actionError=''" in html
    assert "if(!r.ok||result.ok!==true)" in html
    assert "actionError=result.error||result.reason" in html
    assert "esc(actionError)" in html


def test_every_rendered_inline_script_parses_as_javascript():
    """Upstream #48: one bad help string disabled the entire dashboard."""
    import shutil
    import subprocess
    import pytest
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required to syntax-check rendered JavaScript")
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", page(), re.S)
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
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.S)
    script = next(x for x in scripts if "const REGIONAL_FORMAT_KEY" in x)
    start = script.index("const esc=")
    end = script.index("\nlet PLATFORMS=", start)
    helpers = script[start:end]
    harness = r"""
const memory = new Map();
let storageAvailable = true;
let storageWritable = true;
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
const writeFailureHandled = !applyRegionalFormat(failedWriteControl.value, failedWriteControl)
  && failedWriteControl.value === "de" && getRegionalLocale() === "de"
  && refreshCountCalls === refreshAfterSave;
storageWritable = true;
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
const invalidRejected = !applyRegionalFormat("not-a-locale")
  && getRegionalLocale() === "de" && refreshCountCalls === refreshAfterSave;
const resetSaved = applyRegionalFormat("system");
const failedControl = {value: "ja"};
storageAvailable = false;
const storageFailureHandled = !applyRegionalFormat(failedControl.value, failedControl)
  && failedControl.value === "system" && getRegionalLocale() === undefined
  && refreshCountCalls === 2;
storageAvailable = true;
const systemLocale = getRegionalLocale() ?? null;
const systemMarkup = regionalFormatField();
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
  storedAfterSystemReset: memory.get(REGIONAL_FORMAT_KEY) ?? null,
  accessible: selectedMarkup.includes('aria-describedby="g-regional-format-help"')
    && selectedMarkup.includes('id="g-regional-format-help"'),
  germanOptionSelected: selectedMarkup.includes('value="de" selected'),
  systemOptionSelected: systemMarkup.includes('value="system" selected')
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
    assert result["refreshCountCalls"] == 2
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
    assert "Clear ${fmt(failed)} failed" in html
    assert "<div><b>${fmt(h.platforms)}</b><span>Platforms</span></div>" in html
    assert "<div><b>${fmt(h.dats||0)}</b><span>DATs loaded</span></div>" in html
    assert "<div><b>${fmt(h.dat_games||0)}</b><span>Known dumps</span></div>" in html
    assert "<div><b>${fmt(h.events)}</b><span>History events</span></div>" in html
    assert "+fmt(x.percent)+'% — '+esc(x.status)" in html
    assert "+fmt(x.done)+'</td><td>'+fmt(x.failed)+'</td><td>'+fmt(x.remaining)" in html
    assert ">Page ${fmt(page)} of ${fmt(pages)}</span>" in html
    assert "${fmt(r.local||0)}" in html
    assert "${fmt(r.stream||0)}" in html
    assert "${fmt(r.archive||0)}" in html
    assert "${fmt(r.download_only||0)}" in html
    assert "${fmt(Math.max(0,Math.round((r.code_expires_in||0)/60)))} min" in html
    assert "fmt(p.max_size_mb/1024)+' GB' : fmt(p.max_size_mb)+' MB'" in html
    assert "${fmt(s/60)} min" in html and "${fmt(s)} s" in html
    assert "Disabled until ${esc(regionalDateTime(item.disabledUntil))}" in html
