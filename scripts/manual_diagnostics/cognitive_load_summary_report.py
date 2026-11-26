"""Compose the audited cognitive-load study outputs into a local four-page PDF.

Run using a Python environment with ReportLab and Pillow. Existing EEG/counting/
fixation results remain authoritative; this script only formats their outputs.
All input/output paths must be inside the supplied Toolbox project.
"""

from __future__ import annotations

import argparse
import csv
from datetime import UTC, datetime
import hashlib
import json
import logging
from pathlib import Path
import shutil

from PIL import Image
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph, Table, TableStyle

LOGGER = logging.getLogger(__name__)
TASKS = ["Semantic Categories", "Recognition Memory", "Angry Facial Expressions"]
SHORT = {TASKS[0]: "Semantic", TASKS[1]: "Memory", TASKS[2]: "Angry faces"}
PAGE_W, PAGE_H = 8.5 * inch, 11 * inch
LEFT, WIDTH = inch, 6.5 * inch
INK, MUTED, RULE = colors.HexColor("#142336"), colors.HexColor("#425466"), colors.HexColor("#d5dce4")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_eeg_analysis(directory: Path, endpoint: str) -> tuple[list[dict], list[str]]:
    results = read_json(directory / "results.json")
    plan = read_json(directory / "analysis_plan.json")
    rows = results["comparisons"]
    if results.get("endpoint") != endpoint or plan.get("endpoint") != endpoint:
        raise ValueError(f"Expected {endpoint} EEG analysis: {directory}")
    if len(rows) != 3 or {row["task"] for row in rows} != set(TASKS):
        raise ValueError(f"Incomplete {endpoint} EEG task coverage")
    electrodes = next((roi["electrodes"] for roi in plan["roi_snapshot"]["rois"]
                       if roi["name"] == endpoint), None)
    if not electrodes:
        raise ValueError(f"Missing frozen {endpoint} ROI definition")
    return rows, electrodes


def eeg_findings(analyses: list[tuple[str, list[dict], list[str]]]) -> str:
    findings = []
    for endpoint, rows, _ in analyses:
        lower = [SHORT[row["task"]].lower() for row in rows if row["mean_diff"] < 0]
        higher = [SHORT[row["task"]].lower() for row in rows if row["mean_diff"] > 0]
        directions = []
        if lower:
            directions.append(f"lower with load for {', '.join(lower)}")
        if higher:
            directions.append(f"higher for {', '.join(higher)}")
        findings.append(f"{endpoint} means were {'; '.join(directions)}." if directions
                        else f"{endpoint} means were unchanged with load.")
    raw_significant = [(endpoint, row) for endpoint, rows, _ in analyses
                       for row in rows if row["p_raw"] < .05]
    if not raw_significant:
        findings.append(f"None of the {3 * len(analyses)} paired EEG comparisons was significant, "
                        "even before correction.")
    else:
        labels = ", ".join(f'{endpoint.lower()} {SHORT[row["task"]].lower()}'
                           for endpoint, row in raw_significant)
        findings.append(f"Uncorrected p &lt; .05: {labels}; adjusted p values are shown below.")
    return " ".join(findings)


class Report:
    def __init__(self, output: Path, font_dir: Path) -> None:
        pdfmetrics.registerFont(TTFont("Arial", str(font_dir / "arial.ttf")))
        pdfmetrics.registerFont(TTFont("Arial-Bold", str(font_dir / "arialbd.ttf")))
        pdfmetrics.registerFontFamily("Arial", normal="Arial", bold="Arial-Bold")
        self.canvas = Canvas(str(output), pagesize=(PAGE_W, PAGE_H), pageCompression=1)
        self.canvas.setTitle("Cognitive load: EEG, counting and fixation results")
        self.canvas.setAuthor("FPVS cognitive-load analysis")
        self.page = 0
        self.y = 0.0

    def begin(self, title: str, subtitle: str) -> None:
        if self.page:
            self.finish_page()
            self.canvas.showPage()
        self.page += 1
        self.canvas.setFillColor(MUTED)
        self.canvas.setFont("Arial-Bold", 9)
        self.canvas.drawString(LEFT, PAGE_H - 42, "COGNITIVE LOAD / P1-P3 / RECORDED 30 OCTOBER 2026")
        self.y = PAGE_H - 65
        self.para(title, size=18, bold=True, gap=5)
        self.para(subtitle, size=10, color=MUTED, gap=15)

    def para(self, text: str, *, size: float = 10.5, bold: bool = False,
             color=INK, gap: float = 9) -> None:
        style = ParagraphStyle("body", fontName="Arial-Bold" if bold else "Arial",
                               fontSize=size, leading=size * 1.32, textColor=color,
                               alignment=TA_LEFT)
        item = Paragraph(text, style)
        _, height = item.wrap(WIDTH, PAGE_H)
        self.y -= height
        if self.y < 48:
            raise ValueError(f"Page {self.page} content overflows: {text[:50]}")
        item.drawOn(self.canvas, LEFT, self.y)
        self.y -= gap

    def table(self, headers: list[str], rows: list[list[str]], widths: list[float], *, size: float = 9.5) -> None:
        style = ParagraphStyle("cell", fontName="Arial", fontSize=size, leading=size * 1.2, textColor=INK)
        hstyle = ParagraphStyle("header", parent=style, fontName="Arial-Bold")
        data = [[Paragraph(str(value), hstyle) for value in headers]]
        data.extend([[Paragraph(str(value), style) for value in row] for row in rows])
        table = Table(data, colWidths=[value * WIDTH for value in widths], hAlign="LEFT")
        table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#edf1f5")),
            ("LINEBELOW", (0, 0), (-1, 0), .6, RULE),
            ("LINEBELOW", (0, -1), (-1, -1), .6, RULE),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafb")]),
        ]))
        _, height = table.wrap(WIDTH, PAGE_H)
        self.y -= height
        if self.y < 48:
            raise ValueError(f"Page {self.page} table overflows")
        table.drawOn(self.canvas, LEFT, self.y)
        self.y -= 12

    def figure(self, path: Path, *, max_height: float) -> None:
        with Image.open(path) as image:
            width, height = image.size
        scale = min(WIDTH / width, max_height / height)
        draw_w, draw_h = width * scale, height * scale
        self.y -= draw_h
        if self.y < 48:
            raise ValueError(f"Page {self.page} figure overflows")
        self.canvas.drawImage(str(path), LEFT + (WIDTH - draw_w) / 2, self.y,
                              width=draw_w, height=draw_h, mask="auto")
        self.y -= 8

    def finish_page(self) -> None:
        self.canvas.setStrokeColor(RULE)
        self.canvas.line(LEFT, 37, LEFT + WIDTH, 37)
        self.canvas.setFillColor(MUTED)
        self.canvas.setFont("Arial", 8)
        self.canvas.drawString(LEFT, 24, "Exploratory analysis | 3 paired participants | Prepared 5 November 2026")
        self.canvas.drawRightString(LEFT + WIDTH, 24, str(self.page))

    def save(self) -> None:
        self.finish_page()
        self.canvas.save()


def create_report(project: Path, eeg_dir: Path, counting_dir: Path, fixation_dir: Path,
                  output_dir: Path, font_dir: Path, *, frontal_dir: Path | None = None,
                  scalp_figure: Path | None = None, counting_figure: Path | None = None) -> dict:
    scalp = scalp_figure or eeg_dir / "condition_grid" / "cognitive_load_signed_scalp_grid.png"
    count_image = counting_figure or counting_dir / "counting_net_progress.png"
    fixation_image = fixation_dir / "fixation_hit_rate_paired.png"
    input_paths = [eeg_dir, counting_dir, fixation_dir, output_dir, scalp, count_image, fixation_image]
    if frontal_dir is not None:
        input_paths.append(frontal_dir)
    for path in input_paths:
        if not path.resolve().is_relative_to(project.resolve()):
            raise ValueError(f"Path must be under active project: {path}")
    eeg, occipital_electrodes = read_eeg_analysis(eeg_dir, "Occipital")
    eeg_analyses = [("Occipital", eeg, occipital_electrodes)]
    if frontal_dir is not None:
        frontal, frontal_electrodes = read_eeg_analysis(frontal_dir, "Frontal")
        eeg_analyses.append(("Frontal", frontal, frontal_electrodes))
    roi_caption = "; ".join(f"{endpoint.lower()} ({', '.join(electrodes)})"
                            for endpoint, _, electrodes in eeg_analyses)
    counting = read_csv(counting_dir / "load_vs_baseline.csv")
    fixation = read_json(fixation_dir / "results.json")
    comparisons = fixation["comparisons"]
    participant_rows = read_csv(fixation_dir / "participant_condition_counts.csv")
    if len(comparisons) != 3 or len(counting) != 9 or len(participant_rows) != 18:
        raise ValueError("Incomplete input coverage")
    for source in (scalp, count_image, fixation_image):
        if source.suffix.lower() != ".png":
            raise ValueError(f"Figure must be a PNG with a matching PDF: {source}")
        for suffix in (".png", ".pdf"):
            if not source.with_suffix(suffix).is_file():
                raise FileNotFoundError(source.with_suffix(suffix))
    output_dir.mkdir(parents=True, exist_ok=False)
    assets = output_dir / "figures"
    assets.mkdir()
    for source in (scalp, count_image, fixation_image):
        for suffix in (".png", ".pdf"):
            shutil.copy2(source.with_suffix(suffix), assets / source.with_suffix(suffix).name)
    pdf_path = output_dir / "cognitive_load_results_summary.pdf"
    report = Report(pdf_path, font_dir)

    report.begin("Cognitive load: results overview", "EEG responses, counting progress and fixation-target detection")
    report.para(eeg_findings(eeg_analyses), size=10, gap=8)
    report.para("Summed baseline-corrected amplitude (µV)", bold=True, gap=6)
    report.table(["ROI", "Task", "No load", "Load", "Difference", "Raw p", "Holm p"], [
        [endpoint, SHORT[row["task"]], f'{row["mean_no_load_uv"]:.3f}', f'{row["mean_load_uv"]:.3f}',
         f'{row["mean_diff"]:+.3f}', f'{row["p_raw"]:.3f}', f'{row["p_adjusted"]:.3f}']
        for endpoint, rows, _ in eeg_analyses for row in rows],
        [.14, .22, .13, .13, .14, .12, .12], size=9)
    report.para("Fixation-target detection (%)", bold=True, gap=6)
    report.table(["Task", "No load", "Load", "Diff. (pp)", "Raw p", "Holm p"], [
        [SHORT[row["task"]], f'{row["mean_no_load_percent"]:.1f}', f'{row["mean_load_percent"]:.1f}',
         f'{row["mean_diff"]:+.1f}', f'{row["p_raw"]:.3f}', f'{row["p_adjusted"]:.3f}']
        for row in comparisons], [.25, .15, .15, .17, .14, .14])
    report.para("Mean fixation detection was lower with load in all three tasks; none of the paired tests "
                "was significant. P3's semantic-load run had 0/10 hits versus 7/8 without load. "
                "False alarms totaled 2 under load and 6 without load and are not deducted from hit accuracy.")
    report.para("Counting progressed more slowly during load than in the 30-second baseline in 7 of 8 "
                "interpretable reports. P1 reached 51-60% of baseline pace; P2 reached 12-16%. "
                "P3's small baseline and one increasing endpoint make that participant's ratios less reliable. "
                "These are net endpoint estimates, not verified correct subtraction counts.")
    report.para("Each table uses three participants and two-sided paired t tests (df = 2); differences are "
                "load minus no load. Holm correction is applied separately to the three tests within each "
                "EEG ROI and to the three fixation tests. With this small sample, ceiling effects and wide uncertainty, "
                "non-significance does not establish equivalence.", size=9, color=MUTED)

    report.begin("Whole-scalp maps of summed BCA", "Figure 1. No load on the left; load on the right. "
                 f"Paired inference: {roi_caption}.")
    report.figure(scalp, max_height=7 * inch)
    report.para("Maps show signed summed BCA over 1.2, 2.4, 3.6, 4.8 and 7.2 Hz, averaged across P1-P3; "
                "negative values are retained. Row labels show uncorrected paired p values for "
                f"{'both ROIs' if frontal_dir is not None else 'the occipital ROI'}. "
                "The common color scale permits comparisons across all six panels.", size=9, gap=6)
    report.para("The fixed five-frequency domain was selected after the standard harmonic rule retained none; "
                "these tests are exploratory. BioSemi 64; C4 was removed and interpolated in all recordings. "
                "All conditions were one 90-second repetition, with 87.5 seconds analyzed. No 3 × 40-second "
                "or 122-second recording was found. Automatic experimental raw/kurtosis screening was off.", size=9, color=MUTED)

    report.begin("Counting slowed relative to baseline", "Figure 2. Endpoint-derived progress per second, as a percentage of each participant's own baseline.")
    report.figure(count_image, max_height=3.3 * inch)
    report.para("The frozen session prompts specify subtraction by 13 for one 30-second baseline per participant and "
                "90 seconds during each load condition. Equal pace therefore predicts three times the baseline "
                "number decrease. All 12 endpoints have nonzero remainders when the decrease is divided by 13; "
                "arithmetic accuracy cannot be recovered from endpoint reports alone.", size=10)
    report.table(["PID / task", "Start", "Reported end", "Expected end*", "Baseline pace"], [
        [f'{row["participant_id"]} / {SHORT[row["task"]]}', row["start_number"], row["endpoint"],
         f'{float(row["expected_90s_endpoint_at_baseline_net_rate"]):.0f}',
         f'{float(row["percent_of_own_baseline_planned"]):.1f}%' if row["interpretable_net_progress"] == "True" else "Not interpretable"]
        for row in counting], [.27, .12, .18, .21, .22], size=9)
    report.para("*Expected end = load start - 3 × (baseline start - baseline end). Baselines: "
                "P1 509 to -34 (41.77 implied steps); P2 916 to 10 (69.69); P3 948 to 925 (1.77). "
                "P3's angry-face endpoint rose from 391 to 394 and is not interpretable as backward progress. "
                "The eight remaining reports come from only three people, not eight independent participants.", size=9, color=MUTED)

    report.begin("Fixation accuracy was mostly near ceiling", "Figure 3. Each line joins one participant's no-load and load detection percentages.")
    report.figure(fixation_image, max_height=3.3 * inch)
    by_cell = {(row["participant_id"], row["task"], row["condition"]): row for row in participant_rows}
    table_rows = []
    for task in TASKS:
        for participant in ("P1", "P2", "P3"):
            no_load, load = (by_cell[(participant, task, condition)] for condition in ("No load", "Load"))
            table_rows.append([f"{participant} / {SHORT[task]}",
                               f'{no_load["hits"]}/{no_load["targets"]}',
                               f'{load["hits"]}/{load["targets"]}',
                               no_load["false_alarms"], load["false_alarms"]])
    report.table(["PID / task", "No-load hits", "Load hits", "No-load FA", "Load FA"],
                 table_rows, [.28, .18, .18, .18, .18], size=9)
    report.para("Accuracy = hits / targets × 100. A hit is the first Space press within 1 second of a "
                "whole-cross blue-to-red change; the color change lasts 0.3 seconds. False alarms (FA) are "
                "unmatched presses and remain separate. All 18 runs completed their target windows; counts "
                "and classifications were reproduced from the recorded events and responses.", size=9)
    report.para("P3's single semantic-load press occurred 1.781 seconds after the final target, outside the "
                "response window. Its 0/10 result is retained. Descriptive pooled hits: load 75/87; no load "
                "80/83. Tests use participant percentages, not pooled trials. Native Studio summaries and "
                "source hashes, calculations, confidence intervals and figure files are retained with this report.", size=9, color=MUTED)
    report.save()
    sources = [eeg_dir / "results.json", eeg_dir / "analysis_plan.json",
               counting_dir / "results.json", counting_dir / "load_vs_baseline.csv",
               fixation_dir / "results.json", fixation_dir / "participant_condition_counts.csv"]
    if frontal_dir is not None:
        sources.extend([frontal_dir / "results.json", frontal_dir / "analysis_plan.json"])
    sources.extend(source.with_suffix(suffix) for source in (scalp, count_image, fixation_image) for suffix in (".png", ".pdf"))
    evidence = output_dir / "evidence"
    evidence.mkdir()
    evidence_directories = [("eeg", eeg_dir), ("counting", counting_dir), ("fixation", fixation_dir)]
    if frontal_dir is not None:
        evidence_directories.append(("eeg_frontal", frontal_dir))
    for prefix, directory in evidence_directories:
        for source in directory.iterdir():
            if source.is_file() and source.suffix in {".json", ".csv"}:
                shutil.copy2(source, evidence / f"{prefix}_{source.name}")
    manifest = {"created_utc": datetime.now(UTC).isoformat(), "project": str(project),
                "pdf": pdf_path.name, "pages": 4, "source_paths_sha256": {str(p): digest(p) for p in sources},
                "script_sha256": digest(Path(__file__)),
                "inference": f"Participant paired t tests; EEG {roi_caption}; separate three-test Holm families per ROI and fixation",
                "eeg_rois": {endpoint: electrodes for endpoint, _, electrodes in eeg_analyses},
                "eeg_comparison_count": sum(len(rows) for _, rows, _ in eeg_analyses),
                "interpretation": "Exploratory n=3; counting is net endpoint progress, not arithmetic accuracy",
                "behavior_to_eeg_association": "Participant/date/order/654 marker sequences and relative timings agree; no BDF hash in Studio; P2 clock offset acknowledged",
                "source_association_evidence": "Quality Check/Headless Cognitive Load/studio_live_acquisition_association.json"}
    (output_dir / "provenance.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    shutil.copy2(Path(__file__), output_dir / Path(__file__).name)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--eeg-dir", type=Path, required=True)
    parser.add_argument("--frontal-dir", type=Path,
                        help="Optional completed Frontal analysis; electrodes come from its frozen ROI snapshot")
    parser.add_argument("--scalp-figure", type=Path,
                        help="Optional scalp-grid PNG, with matching PDF, inside the project")
    parser.add_argument("--counting-figure", type=Path,
                        help="Optional revised counting PNG, with matching PDF, inside the project")
    parser.add_argument("--counting-dir", type=Path, required=True)
    parser.add_argument("--fixation-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--font-dir", type=Path, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    result = create_report(args.project_root, args.eeg_dir, args.counting_dir, args.fixation_dir,
                           args.output_dir, args.font_dir, frontal_dir=args.frontal_dir,
                           scalp_figure=args.scalp_figure, counting_figure=args.counting_figure)
    LOGGER.info("Saved %s", args.output_dir / result["pdf"])


if __name__ == "__main__":
    main()
