"""Headless smoke tests of the Streamlit app (renders every tab, drives the What-If sliders,
switches language, uses the solutions simulator)."""

from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

from src.config import DB_PATH, PROJECT_ROOT

APP = str(PROJECT_ROOT / "src" / "app" / "dashboard.py")

pytestmark = [
    pytest.mark.warehouse,
    pytest.mark.skipif(not DB_PATH.exists(), reason="warehouse not built - run the ingestion"),
]


def _html(at: AppTest) -> str:
    return " ".join(m.value for m in at.markdown)


def _no_exceptions(at: AppTest) -> None:
    assert not at.exception, [e.value for e in at.exception]


@pytest.fixture
def app() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    return at


def test_renders_without_exceptions(app):
    _no_exceptions(app)
    assert len(app.tabs) == 5
    html = _html(app)
    for label in ("Basin storage now", "30-day expected inflow", "Mean FAO ET0", "Optimisation status"):
        assert label in html


def test_crisis_tab_tells_the_story(app):
    html = _html(app)
    for marker in ("What citizens face", "Why it happens", "What can be done", "Days without a drop"):
        assert marker in html, marker
    for marker in ("Water secured", "Time to deliver"):
        assert marker in html, marker


def test_sidebar_sliders_keep_spec_ranges(app):
    sliders = {s.label: s for s in app.sidebar.slider}
    assert (sliders["Climate inflow shock (%)"].min, sliders["Climate inflow shock (%)"].max) == (-50, 50)
    irr = sliders["Agricultural irrigation demand cap (%)"]
    assert (irr.min, irr.max) == (50, 120)
    buf = sliders["Minimum reservoir safety buffer (% of capacity)"]
    assert (buf.min, buf.max) == (10, 40)


def test_drought_scenario_resolves_and_warns(app):
    sliders = {s.label: s for s in app.slider}
    sliders["Climate inflow shock (%)"].set_value(-50)
    sliders["Minimum reservoir safety buffer (% of capacity)"].set_value(40)
    sliders["Starting storage (% of ABHOER seed)"].set_value(30)
    app.sidebar.radio[0].set_value("p25")
    app.run()
    _no_exceptions(app)
    assert "Deficit Warning" in _html(app)


def test_french_language(app):
    app.sidebar.segmented_control[0].set_value("fr")
    app.run()
    _no_exceptions(app)
    html = _html(app)
    assert "Réserves du bassin" in html
    assert "Ce que vivent les citoyens" in html
    assert "Vos solutions" in html
    assert "Eau sécurisée" in html
    assert "Délai de mise en œuvre" in html
    for marker in ("01 · LA SITUATION", "02 · VOTRE RÉPONSE", "03 · CE QUI CHANGE"):
        assert marker in html, marker
    assert "L'histoire du bassin · 3D" in html


def test_simulator_full_package_improves_service(app):
    package = next(b for b in app.button if "full package" in b.label)
    package.click()
    app.run()
    _no_exceptions(app)
    html = _html(app)
    assert "With your solutions, taps run" in html
    assert "The basin story · 3D" in html
    for marker in ("From drought pressure to household impact", "01 · THE SITUATION",
                   "02 · YOUR RESPONSE", "03 · WHAT CHANGES", "h/day"):
        assert marker in html, marker
    # month & focus now live inside the 3D story (client-side, no Python rerun): there must be
    # no Streamlit widgets for them, otherwise every scrub would rerun the simulator
    assert not any(s.label in ("Implementation focus", "Month in the replay") for s in app.selectbox)
    assert not any(s.label == "Month in the replay" for s in app.select_slider)
    # moving a solution slider afterwards still works
    leak = next(s for s in app.slider if "Fix leaks" in s.label)
    leak.set_value(15)
    app.run()
    _no_exceptions(app)


def test_simulator_presets(app):
    for label in ("Relive 2023-24", "The 2025-26 recovery"):
        btn = next(b for b in app.button if label in b.label)
        btn.click()
        app.run()
        _no_exceptions(app)
