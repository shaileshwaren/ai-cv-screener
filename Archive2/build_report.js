/**
 * build_report.js
 * Called by generate_submission_report.py via subprocess.
 * Reads candidate data from stdin (JSON), writes .docx to stdout (binary).
 *
 * Usage:
 *   echo '<json>' | node build_report.js > output.docx
 */

const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  AlignmentType, LevelFormat, BorderStyle, WidthType, ShadingType,
  VerticalAlign, HeadingLevel
} = require('docx');

// ── Read stdin ────────────────────────────────────────────────────────────────
let raw = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', chunk => { raw += chunk; });
process.stdin.on('end', () => {
  try {
    const data = JSON.parse(raw);
    buildReport(data).then(buf => {
      process.stdout.write(buf);
    }).catch(err => {
      process.stderr.write('BUILD ERROR: ' + err.message + '\n');
      process.exit(1);
    });
  } catch (err) {
    process.stderr.write('JSON PARSE ERROR: ' + err.message + '\n');
    process.exit(1);
  }
});

// ── Colours ───────────────────────────────────────────────────────────────────
const C = {
  darkBlue:  "1F4E79",
  midBlue:   "2E75B6",
  lightBlue: "EBF3FB",
  headerBg:  "D6E4F0",
  green:     "27AE60",
  amber:     "E67E22",
  red:       "C0392B",
  gray:      "595959",
  lightGray: "F5F5F5",
  white:     "FFFFFF",
  black:     "000000",
};

// ── Border helpers ────────────────────────────────────────────────────────────
const NO_BORDER  = { style: BorderStyle.NONE,   size: 0, color: "FFFFFF" };
const LINE       = (color = C.midBlue,  size = 8)  => ({ style: BorderStyle.SINGLE, size, color });
const CELL_LINE  = (color = "BBBBBB",  size = 4)  => ({ style: BorderStyle.SINGLE, size, color });

function cellBorders(top, right, bottom, left) {
  const B = (show) => show ? CELL_LINE() : NO_BORDER;
  return { top: B(top), right: B(right), bottom: B(bottom), left: B(left) };
}

// ── Fit mapping — icon + label ───────────────────────────────────────────────
function scoreToFit(score) {
  if (score >= 4) return { symbol: "\u2705", label: "Meets",   fill: C.white };
  if (score >= 2) return { symbol: "\u26A0\uFE0F", label: "Partial", fill: C.white };
  return             { symbol: "\u274C", label: "Not Met", fill: C.white };
}

function complianceToFit(status) {
  return status === "PASS"
    ? { symbol: "\u2705", label: "Meets",   fill: C.white }
    : { symbol: "\u274C", label: "Not Met", fill: C.white };
}

// ── Paragraph helpers ─────────────────────────────────────────────────────────
function gap(size = 6) {
  return new Paragraph({
    spacing: { before: 0, after: size * 20 },
    children: [new TextRun({ text: "", size: size * 2 })]
  });
}

function sectionLabel(text) {
  return new Paragraph({
    spacing: { before: 240, after: 100 },
    border: { bottom: LINE(C.midBlue, 8) },
    children: [new TextRun({
      text, bold: true, size: 22, color: C.darkBlue, font: "Arial", allCaps: true
    })]
  });
}

function headerPara(runs, spacingAfter = 40) {
  return new Paragraph({
    spacing: { before: 0, after: spacingAfter },
    children: runs
  });
}

function run(text, opts = {}) {
  return new TextRun({ text, font: "Arial", ...opts });
}

// ── Assessment box (single-cell table) ───────────────────────────────────────
function assessmentBox(text) {
  return new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: [9360],
    rows: [new TableRow({ children: [
      new TableCell({
        width: { size: 9360, type: WidthType.DXA },
        borders: {
          top:    LINE(C.midBlue, 6),
          bottom: LINE(C.midBlue, 6),
          left:   LINE(C.midBlue, 6),
          right:  LINE(C.midBlue, 6),
        },
        shading: { fill: C.lightBlue, type: ShadingType.CLEAR },
        margins: { top: 160, bottom: 160, left: 200, right: 200 },
        children: [new Paragraph({
          spacing: { before: 0, after: 0 },
          children: [run(text, { size: 21, color: C.black })]
        })]
      })
    ]})]
  });
}

// ── Grid border presets (exact match to reference docx) ──────────────────────
// Outer frame border: BBBBBB sz4
// Inner grid border:  D1D1D1 sz4
// No border:          FFFFFF sz0 none
const OUTER = { style: BorderStyle.SINGLE, size: 4, color: "BBBBBB" };
const INNER = { style: BorderStyle.SINGLE, size: 4, color: "D1D1D1" };
const NONE2 = { style: BorderStyle.NONE,   size: 0, color: "FFFFFF" };

// Column widths — with Hiring Risk (total = 9360 DXA)
// Without risk: REQ=3680, FIT=1000, EV=4680
// With risk:    REQ=2600, FIT=1100, EV=2760, RISK=2900
const W_REQ  = 2600, W_FIT  = 1100, W_EV  = 2760, W_RISK = 2900;
const W_REQ3 = 3680, W_FIT3 = 1000, W_EV3 = 4680; // fallback no-risk widths

// Risk label colour based on content prefix
function riskLabelColor(riskText) {
  const t = (riskText || "").toLowerCase();
  if (t.startsWith("no risk"))   return C.green;
  if (t.startsWith("low risk"))  return C.amber;
  if (t.startsWith("high risk")) return C.red;
  return C.darkBlue; // default
}

// Build a Fit cell paragraph: icon + label text
function fitPara(fit) {
  return new Paragraph({
    spacing: { before: 0, after: 0 },
    children: [
      run(fit.symbol + " ", { bold: false, size: 24 }),
      run(fit.label,         { bold: false, size: 20, color: C.black }),
    ]
  });
}

// Build a Hiring Risk cell paragraph: bold label + em-dash + explanation
function riskPara(riskText) {
  if (!riskText) return new Paragraph({ children: [run("", { size: 20 })] });
  // Split on first " – " or " - " or "–"
  const dashMatch = riskText.match(/^(.+?)\s*[–-]\s*(.+)$/s);
  if (dashMatch) {
    const label = dashMatch[1].trim();
    const body  = dashMatch[2].trim();
    return new Paragraph({
      spacing: { before: 0, after: 0 },
      children: [
        run(label, { bold: true, size: 20, color: riskLabelColor(label) }),
        run(" – " + body, { bold: false, size: 20, color: C.black }),
      ]
    });
  }
  return new Paragraph({
    spacing: { before: 0, after: 0 },
    children: [run(riskText, { size: 20, color: C.black })]
  });
}

// reqTable — showRisk flag controls 3-col vs 4-col layout
function reqTable(rows, reqKey = "requirement", evKey = "evidence", showRisk = false) {
  const lastIdx  = rows.length - 1;
  const totalW   = 9360;
  const colW     = showRisk
    ? [W_REQ, W_FIT, W_EV, W_RISK]
    : [W_REQ3, W_FIT3, W_EV3];

  // ── Header row ─────────────────────────────────────────────────────────────
  const hdrDefs = showRisk
    ? [
        { text: "Requirement", width: colW[0], isLeft: true,  isRight: false },
        { text: "Fit",         width: colW[1], isLeft: false, isRight: false },
        { text: "Evidence",    width: colW[2], isLeft: false, isRight: false },
        { text: "Hiring Risk", width: colW[3], isLeft: false, isRight: true  },
      ]
    : [
        { text: "Requirement", width: colW[0], isLeft: true,  isRight: false },
        { text: "Fit",         width: colW[1], isLeft: false, isRight: false },
        { text: "Evidence",    width: colW[2], isLeft: false, isRight: true  },
      ];

  const hdrCells = hdrDefs.map(({ text, width, isLeft, isRight }) =>
    new TableCell({
      width: { size: width, type: WidthType.DXA },
      borders: {
        top:    OUTER,
        bottom: INNER,
        left:   isLeft  ? OUTER : NONE2,
        right:  isRight ? OUTER : NONE2,
      },
      shading: { fill: C.headerBg, type: ShadingType.CLEAR },
      margins: { top: 100, bottom: 100, left: 140, right: 140 },
      children: [new Paragraph({
        spacing: { before: 0, after: 0 },
        children: [run(text, { bold: true, size: 21, color: C.darkBlue })]
      })]
    })
  );

  // ── Data rows ──────────────────────────────────────────────────────────────
  const dataRows = rows.map((item, idx) => {
    const isLast = (idx === lastIdx);
    const fit    = ("score" in item)
      ? scoreToFit(Number(item.score))
      : complianceToFit(item.status || "FAIL");

    const reqText  = item[reqKey]       || item.skill || "";
    const evText   = item[evKey]        || "Not demonstrated";
    const riskText = item.hiring_risk   || "";

    function dataBorder(isLeftEdge, isRightEdge) {
      return {
        top:    INNER,
        bottom: isLast ? OUTER : INNER,
        left:   (isLast && isLeftEdge)  ? OUTER : INNER,
        right:  (isLast && isRightEdge) ? OUTER : INNER,
      };
    }

    const cells = [
      // Requirement
      new TableCell({
        width: { size: colW[0], type: WidthType.DXA },
        borders: dataBorder(true, false),
        shading: { fill: C.white, type: ShadingType.CLEAR },
        margins: { top: 100, bottom: 100, left: 140, right: 140 },
        children: [new Paragraph({
          spacing: { before: 0, after: 0 },
          children: [run(reqText, { size: 20, color: C.black })]
        })]
      }),
      // Fit — icon + label
      new TableCell({
        width: { size: colW[1], type: WidthType.DXA },
        borders: dataBorder(false, false),
        shading: { fill: C.white, type: ShadingType.CLEAR },
        margins: { top: 100, bottom: 100, left: 100, right: 100 },
        verticalAlign: VerticalAlign.CENTER,
        children: [fitPara(fit)]
      }),
      // Evidence
      new TableCell({
        width: { size: colW[2], type: WidthType.DXA },
        borders: dataBorder(false, !showRisk),
        shading: { fill: C.white, type: ShadingType.CLEAR },
        margins: { top: 100, bottom: 100, left: 140, right: 140 },
        children: [new Paragraph({
          spacing: { before: 0, after: 0 },
          children: [run(evText, { size: 20, color: C.black })]
        })]
      }),
    ];

    // Hiring Risk column (only when showRisk)
    if (showRisk) {
      cells.push(new TableCell({
        width: { size: colW[3], type: WidthType.DXA },
        borders: dataBorder(false, true),
        shading: { fill: C.white, type: ShadingType.CLEAR },
        margins: { top: 100, bottom: 100, left: 140, right: 140 },
        children: [riskPara(riskText)]
      }));
    }

    return new TableRow({ children: cells });
  });

  return new Table({
    width: { size: totalW, type: WidthType.DXA },
    columnWidths: colW,
    rows: [new TableRow({ children: hdrCells }), ...dataRows]
  });
}

// ── Main build function ───────────────────────────────────────────────────────
async function buildReport(d) {
  const {
    full_name, job_name, overall_score, recommendation,
    ai_summary, compliance, technical, soft_skill, nice_to_have,
    location, nationality, relevant_experience, report_date,
    show_risk = true,
  } = d;

  const recColor = recommendation === "PASS" ? C.green
                 : recommendation === "REVIEW" ? C.amber
                 : C.red;

  const children = [
    // ── Name
    new Paragraph({
      spacing: { before: 0, after: 60 },
      children: [run(full_name, { bold: true, size: 32, color: C.darkBlue })]
    }),

    // ── Role + Experience
    headerPara([
      run("Role Applied: ",    { bold: true, size: 24 }),
      run(job_name,            { bold: true, size: 24, color: C.darkBlue }),
      run("     |     Relevant Experience: ", { bold: true, size: 24 }),
      run(relevant_experience, { size: 24 }),
    ], 40),

    // ── Location + Notice Period
    headerPara([
      run("Location: ",        { bold: true, size: 22 }),
      run(location,            { size: 22 }),
      run("     |     Notice Period: ", { bold: true, size: 22 }),
      run("[To be filled by recruiter]", { size: 22, color: C.gray }),
    ], 40),

    // ── Nationality
    headerPara([
      run("Nationality: ",     { bold: true, size: 22 }),
      run(nationality,         { size: 22 }),
    ], 40),

    // ── Score line
    headerPara([
      run(`AI Score: ${Number(overall_score).toFixed(0)}/100     `, { bold: true, size: 22, color: C.gray }),
      run(`  ${recommendation}  `,  { bold: true, size: 22, color: recColor }),
      run(`     Report Date: ${report_date}`, { size: 20, color: C.gray }),
    ], 80),

    // ── Recruiter's Assessment
    sectionLabel("Recruiter's Assessment"),
    gap(6),
    assessmentBox(ai_summary),
    gap(10),
  ];

  // ── Compliance
  if (compliance && compliance.length > 0) {
    children.push(sectionLabel("Compliance Gates"));
    children.push(gap(6));
    children.push(reqTable(compliance, "requirement", "evidence", show_risk));
    children.push(gap(12));
  }

  // ── Must-Have (technical)
  if (technical && technical.length > 0) {
    children.push(sectionLabel("Must-Have Requirements"));
    children.push(gap(6));
    children.push(reqTable(technical, "requirement", "evidence", show_risk));
    children.push(gap(12));
  }

  // ── Soft Skills (only if present)
  if (soft_skill && soft_skill.length > 0) {
    children.push(sectionLabel("Soft-Skill Indicators"));
    children.push(gap(6));
    children.push(reqTable(soft_skill, "requirement", "evidence", show_risk));
    children.push(gap(12));
  }

  // ── Nice-to-Have
  if (nice_to_have && nice_to_have.length > 0) {
    children.push(sectionLabel("Nice-to-Have"));
    children.push(gap(6));
    children.push(reqTable(nice_to_have, "skill", "evidence", show_risk));
    children.push(gap(16));
  }

  // ── Footer
  children.push(new Paragraph({
    spacing: { before: 240, after: 0 },
    border: { top: { style: BorderStyle.SINGLE, size: 4, color: "CCCCCC" } },
    children: [run(
      "Submitted by Oxydata Software Sdn Bhd  |  parikshit@oxydata.my  |  +603-7625 8298  |  www.oxydata.my",
      { size: 17, color: C.gray, italics: true }
    )]
  }));
  children.push(new Paragraph({
    spacing: { before: 20, after: 0 },
    children: [run(
      "Confidential — for evaluation purposes only. Do not contact candidate directly without consent.",
      { size: 17, color: C.gray, italics: true }
    )]
  }));

  const doc = new Document({
    sections: [{
      properties: {
        page: {
          size:   { width: 11906, height: 16838 },
          margin: { top: 1224, right: 1080, bottom: 1080, left: 1080 }
        }
      },
      children
    }]
  });

  return Packer.toBuffer(doc);
}
