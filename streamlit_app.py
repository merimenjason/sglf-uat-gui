from __future__ import annotations

import base64
import os
import re
import selectors
import shutil
import subprocess
import sys
import tempfile
import time
from collections import deque
from pathlib import Path
from typing import TypedDict

import streamlit as st

try:
    import fcntl
except ImportError:  # pragma: no cover - Streamlit Community Cloud runs Linux.
    fcntl = None


APP_DIR = Path(__file__).resolve().parent
AUTOMATION_SCRIPT = APP_DIR / "singlife_travel_claim.py"
FAVICON_PATH = APP_DIR / "assets" / "favicon.png"
RUN_TIMEOUT_SECONDS = 10 * 60
POLICY_PATTERN = re.compile(r"Using policy number:\s*([^\s|]+)")
SCREENSHOT_PATTERN = re.compile(r"Failure screenshot saved to\s+(.+)$")
LIVE_SCREENSHOT_PATTERN = re.compile(r"Live screenshot:\s*(.+)$")


class RunResult(TypedDict):
    status: str
    scenario: str
    mode: str
    policy: str | None
    elapsed: float
    logs: list[str]
    screenshot_path: str | None
    live_screenshot: bytes | None
    live_stage: str | None
    message: str


SCENARIOS = {
    "Medical expense": {
        "id": "medical",
        "icon": "✚",
        "description": "Flu consultation in Singapore",
        "detail": "Default claim: S$250.00",
    },
    "Flight delay": {
        "id": "flight_delay",
        "icon": "✈",
        "description": "AV222 delay in Colombia",
        "detail": "Fixed UAT test case",
    },
    "Baggage damage": {
        "id": "baggage",
        "icon": "▣",
        "description": "Two lost or damaged items",
        "detail": "Default: S$75.00 per item",
    },
}


def apply_styles() -> None:
    st.markdown(
        """
        <style>
        :root {
            --ink: #eaf6fa; --muted: #8fb6c4; --workspace: #0a2733;
            --header: #00567a; --nav: #006e96; --card: #0f3543;
            --line: #1e4e60; --lime: #c3d700; --cyan: #00a0b9;
        }
        html, body, [class*="css"] { font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
        .stApp, [data-testid="stAppViewContainer"] { background: var(--workspace); color: var(--ink); }
        [data-testid="stHeader"], [data-testid="stToolbar"] { display: none; }
        .block-container { max-width: 1280px; padding: 0 20px 3rem; }
        .app-header {
            width: 100vw; margin-left: calc(50% - 50vw); min-height: 80px;
            background: var(--header); padding: 16px max(26px, calc((100vw - 1228px) / 2));
            display: flex; justify-content: space-between; align-items: center; gap: 1rem;
        }
        .brand-lockup { display: flex; align-items: center; gap: 12px; min-width: 0; }
        .brand-mark {
            width: 36px; height: 36px; border-radius: 50%; overflow: hidden;
            display: block; flex: 0 0 auto;
        }
        .brand-mark img { display: block; width: 100%; height: 100%; object-fit: cover; }
        .brand-title { color: var(--ink); font-size: 18px; line-height: 1.05; font-weight: 800; letter-spacing: -.025em; }
        .brand-subtitle { color: #bfe6ef; font-size: 11px; line-height: 1.25; margin-top: 2px; }
        .header-right { text-align: right; line-height: 1.25; }
        .header-right span { display: block; color: #bfe6ef; font-size: 11px; }
        .header-right strong { color: var(--lime); font-size: 11px; font-weight: 700; }
        .nav-strip {
            width: 100vw; margin-left: calc(50% - 50vw); height: 43px; background: var(--nav);
            padding: 0 max(22px, calc((100vw - 1236px) / 2)); display: flex; align-items: stretch;
            overflow-x: auto; white-space: nowrap;
        }
        .nav-strip a {
            color: #9fc1ce; padding: 12px 15px 10px; font-size: 13px; line-height: 20px;
            text-decoration: none; border-bottom: 3px solid transparent;
        }
        .nav-strip a:hover { color: var(--ink); background: rgba(255,255,255,.035); }
        .nav-strip a.active { color: white; font-weight: 700; border-bottom-color: var(--lime); }
        .metric-grid {
            display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 11px;
            padding: 26px 6px 0; margin-bottom: 16px;
        }
        .metric-tile { background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 16px 18px; min-height: 84px; }
        .metric-value { color: var(--ink); font-size: 29px; line-height: 1; font-weight: 800; letter-spacing: -.035em; }
        .metric-value.cyan { color: var(--cyan); }
        .metric-value.lime { color: var(--lime); }
        .metric-label { color: var(--muted); font-size: 11.5px; margin-top: 7px; }
        .page-heading { padding: 7px 6px 15px; }
        .eyebrow { color: var(--lime); font-size: 11px; font-weight: 800; letter-spacing: .12em; text-transform: uppercase; }
        .page-heading h1 { color: var(--ink); font-size: 25px; line-height: 1.1; letter-spacing: -.035em; margin: 5px 0 6px; }
        .page-heading p { color: var(--muted); font-size: 13px; margin: 0; }
        [data-testid="stVerticalBlockBorderWrapper"] { background: var(--card); border: 1px solid var(--line); border-radius: 10px; box-shadow: none; }
        h1, h2, h3, p, label, [data-testid="stMarkdownContainer"] { color: var(--ink); }
        h3 { font-size: 14px !important; font-weight: 750 !important; }
        .scenario-summary { color: var(--muted); font-size: 12px; padding: 2px 0 10px; }
        .scenario-summary strong { color: var(--ink); }
        [data-testid="stRadio"] [role="radiogroup"] { gap: 8px; }
        [data-testid="stRadio"] [role="radiogroup"] label { background: #0c2f3c; border: 1px solid var(--line); border-radius: 7px; padding: 8px 10px; }
        [data-testid="stRadio"] [role="radiogroup"] label:has(input:checked) { background: #173f4e; border-color: var(--lime); box-shadow: inset 0 -2px 0 var(--lime); }
        [data-testid="stRadio"] label p, [data-testid="stCheckbox"] label p { color: var(--ink); font-size: 12px; }
        [data-baseweb="input"] { background: #0b2d39 !important; border: 1px solid var(--line); border-radius: 6px; }
        [data-baseweb="input"] input { color: var(--ink); caret-color: var(--lime); }
        [data-baseweb="input"] input::placeholder { color: #628896; }
        [data-testid="stWidgetLabel"] p { color: var(--muted); font-size: 11.5px; }
        .safe-note { background: #0b2f3d; border-left: 3px solid var(--cyan); border-radius: 4px; padding: 11px 12px; color: #bfe6ef; font-size: 12px; }
        .safe-note strong { color: var(--ink); }
        .live-preview {
            min-height: 188px; border: 1px dashed #397083; border-radius: 8px; background: #0b2d39;
            display: grid; place-items: center; text-align: center; padding: 24px; margin-top: 4px;
        }
        .live-preview strong { display: block; color: var(--lime); font-size: 11px; letter-spacing: .1em; text-transform: uppercase; }
        .live-preview span { display: block; max-width: 270px; color: var(--muted); font-size: 12px; margin-top: 7px; line-height: 1.45; }
        [data-testid="stImage"] img { border: 1px solid var(--line); border-radius: 7px; }
        .result-ok { background: #183b3d; border: 1px solid #55720f; border-radius: 7px; padding: 12px 14px; color: #dff5a5; }
        .result-error { background: #422a2d; border: 1px solid #7a4148; border-radius: 7px; padding: 12px 14px; color: #ffd8d8; }
        [data-testid="stMetric"] { background: #0b2f3c; border: 1px solid var(--line); padding: 10px 12px; border-radius: 7px; }
        [data-testid="stMetricValue"] { color: var(--ink); font-size: 19px; }
        [data-testid="stMetricLabel"] { color: var(--muted); }
        .stButton > button[kind="primary"] { background: var(--lime); color: #18313a; border: 1px solid var(--lime); font-weight: 800; border-radius: 6px; min-height: 42px; box-shadow: none; }
        .stButton > button[kind="primary"]:hover { background: #d3e71a; color: #102830; border-color: #d3e71a; }
        .stButton > button:disabled { background: #294550 !important; color: #6f8d98 !important; border-color: #315563 !important; }
        [data-testid="stStatusWidget"], [data-testid="stExpander"] { background: var(--card); border-color: var(--line); }
        [data-testid="stProgressBar"] > div > div { background-color: var(--lime); }
        hr { border-color: var(--line) !important; }
        code { color: #dff5a5 !important; }
        [data-testid="stCaptionContainer"] { color: var(--muted); }
        @media (max-width: 900px) { .metric-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); } .header-right { display: none; } }
        @media (max-width: 640px) {
            .block-container { padding-left: 1rem; padding-right: 1rem; }
            .app-header { padding-left: 18px; padding-right: 18px; }
            .nav-strip { padding-left: 6px; padding-right: 6px; }
            .metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); padding-left: 0; padding-right: 0; }
            .metric-tile { padding: 13px 14px; min-height: 75px; }
            .metric-value { font-size: 24px; }
            .page-heading { padding-left: 0; padding-right: 0; }
            .page-heading h1 { font-size: 22px; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def find_chromium() -> str | None:
    configured = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH")
    if configured and Path(configured).exists():
        return configured

    for executable in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        found = shutil.which(executable)
        if found:
            return found
    return None


def validate_suffix(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9-]{0,16}", value))


def build_command(
    scenario: str,
    mode: str,
    suffix: str,
    medical_amount: float,
    baggage_amount: float,
    pdf_dir: Path,
) -> list[str]:
    command = [
        sys.executable,
        "-u",
        str(AUTOMATION_SCRIPT),
        "--case",
        scenario,
        "--policy-suffix",
        suffix,
        "--pdf-dir",
        str(pdf_dir),
    ]
    if mode == "review":
        command.append("--no-submit")
    if scenario == "medical":
        command.extend(["--medical-amount", f"{medical_amount:.2f}"])
    if scenario == "baggage":
        command.extend(["--baggage-item-amount", f"{baggage_amount:.2f}"])
    return command


def run_automation(
    scenario: str,
    scenario_label: str,
    mode: str,
    suffix: str,
    medical_amount: float,
    baggage_amount: float,
    live_preview_slot,
) -> RunResult:
    started = time.monotonic()
    logs: deque[str] = deque(maxlen=250)
    policy: str | None = None
    screenshot_path: str | None = None
    live_screenshot: bytes | None = None
    live_stage: str | None = None
    lock_path = Path(tempfile.gettempdir()) / "singlife_uat_streamlit.lock"

    with lock_path.open("w") as lock_file:
        if fcntl is not None:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return {
                    "status": "busy",
                    "scenario": scenario_label,
                    "mode": mode,
                    "policy": None,
                    "elapsed": 0,
                    "logs": [],
                    "screenshot_path": None,
                    "live_screenshot": None,
                    "live_stage": None,
                    "message": "Another UAT claim is already running. Please wait for it to finish.",
                }

        with tempfile.TemporaryDirectory(prefix="singlife_streamlit_docs_") as pdf_temp:
            live_screenshot_path = Path(pdf_temp) / "live-browser.png"
            live_screenshot_mtime: int | None = None
            command = build_command(
                scenario,
                mode,
                suffix,
                medical_amount,
                baggage_amount,
                Path(pdf_temp),
            )
            environment = os.environ.copy()
            environment["PYTHONUNBUFFERED"] = "1"
            environment["PLAYWRIGHT_LIVE_SCREENSHOT_PATH"] = str(live_screenshot_path)
            chromium = find_chromium()
            if chromium:
                environment["PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"] = chromium

            with st.status("Starting the secure UAT browser…", expanded=True) as status_panel:
                progress = st.progress(10, text="Preparing the temporary test data")
                live_line = st.empty()
                live_line.caption("Live browser checkpoints will appear in the preview panel.")
                process = subprocess.Popen(
                    command,
                    cwd=APP_DIR,
                    env=environment,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )

                selector = selectors.DefaultSelector()
                assert process.stdout is not None
                selector.register(process.stdout, selectors.EVENT_READ)

                timed_out = False
                while True:
                    if time.monotonic() - started > RUN_TIMEOUT_SECONDS:
                        timed_out = True
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                        break

                    events = selector.select(timeout=0.25)
                    for key, _ in events:
                        line = key.fileobj.readline()
                        if not line:
                            continue
                        clean_line = line.rstrip()
                        logs.append(clean_line)
                        live_line.caption(clean_line)
                        progress.progress(55, text="Completing the claim form in Merimen UAT")

                        policy_match = POLICY_PATTERN.search(clean_line)
                        if policy_match:
                            policy = policy_match.group(1)
                        screenshot_match = SCREENSHOT_PATTERN.search(clean_line)
                        if screenshot_match:
                            screenshot_path = screenshot_match.group(1).strip()
                        live_match = LIVE_SCREENSHOT_PATTERN.search(clean_line)
                        if live_match:
                            live_stage = live_match.group(1).strip()

                    try:
                        current_mtime = live_screenshot_path.stat().st_mtime_ns
                        if current_mtime != live_screenshot_mtime:
                            candidate = live_screenshot_path.read_bytes()
                            if candidate:
                                live_screenshot = candidate
                                live_screenshot_mtime = current_mtime
                                caption = (live_stage or "Merimen UAT checkpoint").replace("_", " ").title()
                                live_preview_slot.image(
                                    live_screenshot,
                                    caption=f"Live · {caption}",
                                    use_container_width=True,
                                )
                    except (FileNotFoundError, OSError):
                        pass

                    if process.poll() is not None:
                        remaining = process.stdout.read()
                        for line in remaining.splitlines():
                            logs.append(line)
                            policy_match = POLICY_PATTERN.search(line)
                            if policy_match:
                                policy = policy_match.group(1)
                            screenshot_match = SCREENSHOT_PATTERN.search(line)
                            if screenshot_match:
                                screenshot_path = screenshot_match.group(1).strip()
                            live_match = LIVE_SCREENSHOT_PATTERN.search(line)
                            if live_match:
                                live_stage = live_match.group(1).strip()
                        break

                try:
                    final_candidate = live_screenshot_path.read_bytes()
                    if final_candidate:
                        live_screenshot = final_candidate
                except (FileNotFoundError, OSError):
                    pass

                elapsed = time.monotonic() - started
                if timed_out:
                    progress.progress(100, text="Run stopped after the ten-minute limit")
                    status_panel.update(label="The UAT run timed out", state="error", expanded=True)
                    result_status = "failed"
                    message = "The run exceeded ten minutes and was stopped."
                elif process.returncode == 0:
                    result_status = "prepared" if mode == "review" else "submitted"
                    progress.progress(100, text="Review prepared" if mode == "review" else "UAT claim submitted")
                    status_panel.update(
                        label="Ready for review" if mode == "review" else "UAT submission completed",
                        state="complete",
                        expanded=False,
                    )
                    message = (
                        "The form reached the final confirmation point without submitting."
                        if mode == "review"
                        else "The dummy claim was submitted to Merimen UAT."
                    )
                else:
                    result_status = "failed"
                    progress.progress(100, text="Run stopped with an error")
                    status_panel.update(label="The UAT run failed", state="error", expanded=True)
                    message = "The browser automation stopped before completing the requested run."

    return {
        "status": result_status,
        "scenario": scenario_label,
        "mode": mode,
        "policy": policy,
        "elapsed": elapsed,
        "logs": list(logs),
        "screenshot_path": screenshot_path,
        "live_screenshot": live_screenshot,
        "live_stage": live_stage,
        "message": message,
    }


def render_result(result: RunResult) -> None:
    if result["status"] in {"prepared", "submitted"}:
        title = "Prepared for review" if result["status"] == "prepared" else "Submitted to UAT"
        st.markdown(
            f'<div class="result-ok"><strong>{title}</strong><br>{result["message"]}</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f'<div class="result-error"><strong>Run not completed</strong><br>{result["message"]}</div>',
            unsafe_allow_html=True,
        )

    columns = st.columns(3)
    columns[0].metric("Scenario", result["scenario"])
    columns[1].metric("Result", result["status"].title())
    columns[2].metric("Duration", f'{result["elapsed"]:.0f}s')
    if result["policy"]:
        st.code(result["policy"], language=None)

    screenshot = result.get("screenshot_path")
    if screenshot and Path(screenshot).is_file():
        st.download_button(
            "Download failure screenshot",
            data=Path(screenshot).read_bytes(),
            file_name=Path(screenshot).name,
            mime="image/png",
        )

    live_screenshot = result.get("live_screenshot")
    if live_screenshot:
        stage = (result.get("live_stage") or "Final checkpoint").replace("_", " ").title()
        st.image(
            live_screenshot,
            caption=f"Last browser checkpoint · {stage}",
            use_container_width=True,
        )

    with st.expander("Technical run log"):
        st.code("\n".join(result["logs"]) or "No console output was produced.", language="text")


st.set_page_config(
    page_title="Travel Claims UAT Runner",
    page_icon=str(FAVICON_PATH),
    layout="wide",
    initial_sidebar_state="collapsed",
)
apply_styles()

st.markdown(
    f"""
    <div class="app-header">
      <div class="brand-lockup">
        <div class="brand-mark"><img src="data:image/png;base64,{base64.b64encode(FAVICON_PATH.read_bytes()).decode('ascii')}" alt="TravelClaims"></div>
        <div>
          <div class="brand-title">TravelClaims</div>
          <div class="brand-subtitle">UAT Automation Workspace for SG Travel Claims</div>
        </div>
      </div>
      <div class="header-right">
        <span>Powered by Python Playwright</span>
        <strong>Merimen UAT · private workspace</strong>
      </div>
    </div>
    <div class="nav-strip">
      <a class="active" href="#run-test">Run a Test</a>
      <a href="#scenarios">Scenarios</a>
      <a href="#latest-run">Recent Runs</a>
      <a href="#safety">Safety Notes</a>
      <a href="#method">Method Notes</a>
    </div>
    <div class="metric-grid">
      <div class="metric-tile"><div class="metric-value cyan">3</div><div class="metric-label">Test scenarios</div></div>
      <div class="metric-tile"><div class="metric-value">6</div><div class="metric-label">Automated stages</div></div>
      <div class="metric-tile"><div class="metric-value">10m</div><div class="metric-label">Maximum runtime</div></div>
      <div class="metric-tile"><div class="metric-value">1</div><div class="metric-label">Concurrent browser</div></div>
      <div class="metric-tile"><div class="metric-value">UAT</div><div class="metric-label">Target environment</div></div>
      <div class="metric-tile"><div class="metric-value lime">Submit</div><div class="metric-label">Default final action</div></div>
    </div>
    <div class="page-heading" id="run-test">
      <div class="eyebrow">New test run</div>
      <h1>Travel claim automation</h1>
      <p>Choose a scenario, verify the UAT controls, and start a temporary browser run.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown('<span id="scenarios"></span>', unsafe_allow_html=True)
left, right = st.columns([1.65, 1], gap="large")

with left:
    with st.container(border=True):
        st.subheader("1. Choose a scenario")
        scenario_label = st.radio(
            "Claim scenario",
            options=list(SCENARIOS),
            horizontal=True,
            label_visibility="collapsed",
        )
        selected = SCENARIOS[scenario_label]
        st.markdown(
            f'<div class="scenario-summary"><strong>{selected["icon"]} {scenario_label}</strong> · '
            f'{selected["description"]}<br>{selected["detail"]}</div>',
            unsafe_allow_html=True,
        )

        scenario_id = selected["id"]
        medical_amount = 250.0
        baggage_amount = 75.0
        if scenario_id == "medical":
            medical_amount = st.number_input(
                "Medical claim amount (S$)",
                min_value=0.01,
                max_value=100000.0,
                value=250.0,
                step=10.0,
                format="%.2f",
            )
        elif scenario_id == "baggage":
            baggage_amount = st.number_input(
                "Amount per baggage item (S$)",
                min_value=0.01,
                max_value=100000.0,
                value=75.0,
                step=5.0,
                format="%.2f",
            )

        suffix = st.text_input(
            "Optional policy suffix",
            max_chars=16,
            placeholder="Example: QA-42",
            help="Letters, numbers, and hyphens only. A random prefix is added automatically.",
        ).strip()
        suffix_valid = validate_suffix(suffix)
        if not suffix_valid:
            st.error("Use only letters, numbers, and hyphens in the policy suffix.")

        st.subheader("2. Choose the final action")
        mode_label = st.radio(
            "Final action",
            options=["Review before submission", "Submit to UAT"],
            index=1,
            horizontal=True,
            help="Review mode fills the form and stops at the final confirmation dialog.",
        )
        mode = "review" if mode_label.startswith("Review") else "submit"
        confirmed = True
        if mode == "submit":
            confirmed = st.checkbox(
                "I confirm this uses dummy data and the destination is Merimen UAT.",
                value=False,
            )

        run_disabled = not suffix_valid or not confirmed
        run_clicked = st.button(
            "Prepare review" if mode == "review" else "Submit dummy UAT claim",
            type="primary",
            use_container_width=True,
            disabled=run_disabled,
        )

with right:
    with st.container(border=True):
        st.subheader("Run summary")
        st.write(f"**Scenario:** {scenario_label}")
        if scenario_id == "medical":
            st.write(f"**Amount:** S${medical_amount:,.2f}")
        elif scenario_id == "baggage":
            st.write(f"**Amount:** 2 × S${baggage_amount:,.2f}")
        else:
            st.write("**Flight:** AV222 · 24 Feb 2026")
        st.write(f"**Final action:** {'Stop for review' if mode == 'review' else 'Submit to UAT'}")
        st.write(f"**Policy suffix:** {suffix or 'None'}")
        st.markdown(
            '<div class="safe-note" id="safety"><strong>Safety boundary</strong><br>'
            'The automation is hard-pinned to the Merimen UAT hostname and accepts only the three packaged dummy scenarios.</div>',
            unsafe_allow_html=True,
        )

        st.divider()
        st.caption("Cloud runner readiness")
        detected_chromium = find_chromium()
        st.write("✅ Automation script included")
        st.write("✅ One run at a time")
        st.write("✅ Ten-minute timeout")
        st.write("✅ Chromium available" if detected_chromium else "ℹ️ Chromium is installed during cloud deployment")

        st.divider()
        st.subheader("Live browser")
        st.caption("Latest Playwright checkpoint")
        live_preview_slot = st.empty()
        previous_live = st.session_state.get("last_result", {}).get("live_screenshot")
        previous_stage = st.session_state.get("last_result", {}).get("live_stage")
        if previous_live:
            stage_caption = (previous_stage or "Final checkpoint").replace("_", " ").title()
            live_preview_slot.image(
                previous_live,
                caption=f"Last run · {stage_caption}",
                use_container_width=True,
            )
        else:
            live_preview_slot.markdown(
                '<div class="live-preview"><div><strong>Waiting for a run</strong>'
                '<span>Screenshots will refresh here as Playwright moves through the UAT claim.</span></div></div>',
                unsafe_allow_html=True,
            )

if run_clicked:
    result = run_automation(
        scenario=scenario_id,
        scenario_label=scenario_label,
        mode=mode,
        suffix=suffix,
        medical_amount=medical_amount,
        baggage_amount=baggage_amount,
        live_preview_slot=live_preview_slot,
    )
    st.session_state["last_result"] = result
    history = st.session_state.setdefault("run_history", [])
    history.insert(0, result)
    del history[5:]

if "last_result" in st.session_state:
    st.markdown('<span id="latest-run"></span>', unsafe_allow_html=True)
    st.divider()
    st.subheader("Latest run")
    render_result(st.session_state["last_result"])

history = st.session_state.get("run_history", [])
if history:
    with st.expander("Recent runs in this session"):
        for item in history:
            st.write(
                f'**{item["scenario"]}** · {item["status"].title()} · '
                f'{item["elapsed"]:.0f}s · {item["policy"] or "Policy unavailable"}'
            )

st.markdown(
    '<div class="safe-note" id="method"><strong>Method note</strong><br>'
    'The packaged Python workflow uses fixed DOM selectors and dummy PDFs for three repeatable travel-claim scenarios.</div>',
    unsafe_allow_html=True,
)
st.caption("Use dummy UAT data only. Do not repoint the packaged automation at a production claims portal.")
