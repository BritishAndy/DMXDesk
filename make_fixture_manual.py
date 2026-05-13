from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                 TableStyle, HRFlowable, PageBreak, KeepTogether)
from reportlab.lib.enums import TA_LEFT, TA_CENTER

W, H = A4
doc = SimpleDocTemplate(
    "/home/claude/DMX_Desk_Fixture_Definitions.pdf",
    pagesize=A4,
    leftMargin=20*mm, rightMargin=20*mm,
    topMargin=18*mm, bottomMargin=18*mm
)

# ── Colours ──────────────────────────────────────────────────────────────────
BLACK  = colors.black
WHITE  = colors.white
HBLUE  = colors.HexColor("#1a3a5c")
LGREY  = colors.HexColor("#f4f4f4")
MGREY  = colors.HexColor("#cccccc")
DGREY  = colors.HexColor("#444444")
CODE_BG= colors.HexColor("#f0f0f0")
AMBER  = colors.HexColor("#cc6600")
GREEN  = colors.HexColor("#226622")
TEAL   = colors.HexColor("#006666")

# ── Styles ────────────────────────────────────────────────────────────────────
styles = getSampleStyleSheet()

title_s   = ParagraphStyle("Title", parent=styles["Normal"],
    fontSize=22, textColor=BLACK, fontName="Helvetica-Bold",
    alignment=TA_CENTER, spaceAfter=4)
sub_s     = ParagraphStyle("Sub", parent=styles["Normal"],
    fontSize=10, textColor=DGREY, alignment=TA_CENTER, spaceAfter=12)
h1_s      = ParagraphStyle("H1", parent=styles["Normal"],
    fontSize=13, textColor=WHITE, fontName="Helvetica-Bold",
    spaceBefore=0, spaceAfter=0, leftIndent=4)
h2_s      = ParagraphStyle("H2", parent=styles["Normal"],
    fontSize=11, textColor=HBLUE, fontName="Helvetica-Bold",
    spaceBefore=10, spaceAfter=3)
h3_s      = ParagraphStyle("H3", parent=styles["Normal"],
    fontSize=10, textColor=DGREY, fontName="Helvetica-Bold",
    spaceBefore=6, spaceAfter=2)
body_s    = ParagraphStyle("Body", parent=styles["Normal"],
    fontSize=9, textColor=BLACK, spaceAfter=4, leading=14)
note_s    = ParagraphStyle("Note", parent=styles["Normal"],
    fontSize=8, textColor=DGREY, fontName="Helvetica-Oblique", spaceAfter=3)
code_s    = ParagraphStyle("Code", parent=styles["Normal"],
    fontSize=8, textColor=BLACK, fontName="Courier",
    backColor=CODE_BG, spaceAfter=4, leftIndent=8, rightIndent=8,
    borderPad=4, leading=12)
req_s     = ParagraphStyle("Req", parent=styles["Normal"],
    fontSize=9, textColor=colors.HexColor("#880000"), fontName="Helvetica-Bold",
    spaceAfter=2)
opt_s     = ParagraphStyle("Opt", parent=styles["Normal"],
    fontSize=9, textColor=GREEN, fontName="Helvetica-Bold", spaceAfter=2)

def h1(t):
    p = Paragraph(t, h1_s)
    t_obj = Table([[p]], colWidths=[170*mm])
    t_obj.setStyle(TableStyle([
        ("BACKGROUND",   (0,0), (-1,-1), HBLUE),
        ("TOPPADDING",   (0,0), (-1,-1), 6),
        ("BOTTOMPADDING",(0,0), (-1,-1), 6),
        ("LEFTPADDING",  (0,0), (-1,-1), 8),
        ("RIGHTPADDING", (0,0), (-1,-1), 8),
        ("TOPMARGIN",    (0,0), (-1,-1), 10),
    ]))
    return KeepTogether([Spacer(1, 10*mm), t_obj, Spacer(1, 3*mm)])
def h2(t):   return Paragraph(t, h2_s)
def h3(t):   return Paragraph(t, h3_s)
def p(t):    return Paragraph(t, body_s)
def note(t): return Paragraph(f"<i>Note: {t}</i>", note_s)
def code(t): return Paragraph(t.replace("\n","<br/>").replace(" ","&nbsp;"), code_s)
def sp(n=4): return Spacer(1, n*mm)
def hr():    return HRFlowable(width="100%", thickness=0.5, color=MGREY, spaceAfter=4)

def field_table(rows):
    """Render a field reference table. rows = [(field, type, req, description)]"""
    cell_s   = ParagraphStyle("cell",  parent=styles["Normal"], fontSize=8, leading=11)
    code_c   = ParagraphStyle("codec", parent=styles["Normal"], fontSize=8, fontName="Courier-Bold", leading=11)
    hdr_s    = ParagraphStyle("hdr",   parent=styles["Normal"], fontSize=8, fontName="Helvetica-Bold",
                               textColor=WHITE, leading=11)
    req_s2   = ParagraphStyle("req",   parent=styles["Normal"], fontSize=8, fontName="Helvetica-Bold",
                               textColor=colors.HexColor("#cc0000"), leading=11)
    opt_s2   = ParagraphStyle("opt",   parent=styles["Normal"], fontSize=8, fontName="Helvetica-Bold",
                               textColor=GREEN, leading=11)
    data = [[Paragraph("Field", hdr_s), Paragraph("Type", hdr_s),
             Paragraph("", hdr_s),      Paragraph("Description", hdr_s)]]
    for field, typ, req, desc in rows:
        req_text = "Required" if req else "Optional"
        req_style = req_s2 if req else opt_s2
        data.append([
            Paragraph(field, code_c),
            Paragraph(typ,   cell_s),
            Paragraph(req_text, req_style),
            Paragraph(desc,  cell_s),
        ])
    t = Table(data, colWidths=[30*mm, 22*mm, 18*mm, 100*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,0),  HBLUE),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [WHITE, LGREY]),
        ("VALIGN",        (0,0), (-1,-1), "TOP"),
        ("GRID",          (0,0), (-1,-1), 0.3, MGREY),
        ("LEFTPADDING",   (0,0), (-1,-1), 5),
        ("RIGHTPADDING",  (0,0), (-1,-1), 5),
        ("TOPPADDING",    (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
    ]))
    return t

def value_table(rows):
    """Value/meaning table for named fields."""
    cell_s = ParagraphStyle("vcell", parent=styles["Normal"], fontSize=8, leading=11)
    code_c = ParagraphStyle("vcode", parent=styles["Normal"], fontSize=8,
                             fontName="Courier", leading=11)
    hdr_s  = ParagraphStyle("vhdr",  parent=styles["Normal"], fontSize=8,
                             fontName="Helvetica-Bold", textColor=WHITE, leading=11)
    data = [[Paragraph("Value", hdr_s), Paragraph("Meaning", hdr_s)]]
    for v, m in rows:
        data.append([Paragraph(v, code_c), Paragraph(m, cell_s)])
    t = Table(data, colWidths=[55*mm, 115*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,0),  DGREY),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [WHITE, LGREY]),
        ("VALIGN",        (0,0), (-1,-1), "TOP"),
        ("GRID",          (0,0), (-1,-1), 0.3, MGREY),
        ("LEFTPADDING",   (0,0), (-1,-1), 5),
        ("RIGHTPADDING",  (0,0), (-1,-1), 5),
        ("TOPPADDING",    (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
    ]))
    return t

# ═══════════════════════════════════════════════════════════════════════════════
story = []

# ── Title ──────────────────────────────────────────────────────────────────────
story += [
    sp(6),
    Paragraph("DMX Desk Emulator", title_s),
    Paragraph("Fixture Definition Reference", title_s),
    Paragraph("A complete guide to writing and editing fixture JSON files",  sub_s),
    HRFlowable(width="100%", thickness=1.5, color=HBLUE, spaceAfter=8),
    p("Fixture definitions tell the desk how to display and control a DMX fixture — "
      "what channels it has, their labels, ranges, and behaviour. Each fixture type "
      "is defined in a <b>.json</b> file in the <b>fixtures/</b> folder. "
      "The filename (without .json) is used as the <b>type</b> field in patch.json."),
    sp(2),
]

# ── 1. File Structure ──────────────────────────────────────────────────────────
story += [
    h1("1. File Structure"),
    sp(2),
    p("A fixture definition file is a single JSON object with one required key: "
      "<b>channels</b>. It may also have a top-level <b>lockable</b> flag."),
    sp(2),
    code('{\n'
         '  "channels": [ ... ],\n'
         '  "lockable": false\n'
         '}'),
    sp(2),
    field_table([
        ("channels",  "array",   True,  "List of channel definition objects, one per DMX channel. "
                                        "Order matches DMX address offset (first entry = base address)."),
        ("lockable",  "boolean", False, "If true, lock buttons appear on the fixture faceplate. "
                                        "Locked fixtures are excluded from scene recalls. "
                                        "Default: false. Use for house lights, special effects etc."),
    ]),
    sp(4),
]

# ── 2. Channel Fields ──────────────────────────────────────────────────────────
story += [
    h1("2. Channel Fields"),
    sp(2),
    p("Each entry in the channels array defines one DMX channel. "
      "Channels are assigned DMX addresses sequentially starting from the fixture's base address."),
    sp(2),
    field_table([
        ("label",   "string",  True,  "Short display name shown on the fader. "
                                      "Max ~8 characters for best layout. "
                                      "Special labels R, G, B, W, A, UV trigger colour swatch display."),
        ("master",  "boolean", True,  "Exactly one channel per fixture should be true. "
                                      "This channel is shown as the large master fader. "
                                      "All other channels are shown as smaller sub-channel faders."),
        ("default", "number",  True,  "Default value sent to DMX when the fixture is first loaded "
                                      "and for hidden channels. Must be within the channel's range."),
        ("range",   "varies",  True,  "Defines the fader range. Either a numeric array [min, max] "
                                      "or a named dict {\"lo-hi\": \"name\"}. See Section 3."),
        ("unit",    "string",  True,  "How the value is displayed and scaled. "
                                      "One of: %, raw, named. See Section 4."),
        ("show",    "boolean", True,  "If true, the channel appears as a visible fader. "
                                      "If false, the channel is hidden — its default value is sent "
                                      "to DMX but the operator cannot adjust it from the desk."),
        ("jump",    "boolean", False, "If true, this channel snaps instantly during scene fades "
                                      "rather than interpolating. Use for mode/program/strobe channels "
                                      "where fading through intermediate values is undesirable. "
                                      "Snap direction is automatic: snaps before fade-in "
                                      "(when master increases) or after fade-out (when master goes to zero). "
                                      "Default: false."),
        ("role",    "string",  False, "Assigns a special role to this channel. "
                                      "Currently supported: \"pan\" and \"tilt\". "
                                      "If both pan and tilt roles are present, an XY joystick pad "
                                      "appears on the faceplate alongside the colour faders. "
                                      "Default: none."),
    ]),
    sp(4),
]

# ── 3. Range ──────────────────────────────────────────────────────────────────
story += [
    h1("3. The range Field"),
    sp(2),
    h2("3.1 Numeric Range"),
    p("A two-element array <b>[min, max]</b> defines a continuous numeric fader. "
      "The fader moves between these values. DMX output is scaled proportionally "
      "to the 0–255 DMX range."),
    sp(2),
    code('"range": [0, 255]    // raw 0-255\n'
         '"range": [0, 100]    // percentage 0-100%'),
    sp(2),
    p("Use <b>[0, 100]</b> with <b>\"unit\": \"%\"</b> for intensity channels — "
      "the desk displays values as percentages and scales to 0–255 DMX internally. "
      "Use <b>[0, 255]</b> with <b>\"unit\": \"raw\"</b> for channels where you want "
      "direct DMX value control."),
    sp(4),

    h2("3.2 Named Range"),
    p("A JSON object maps value ranges to display names. Each key is either a single "
      "value or a range in the form <b>\"lo-hi\"</b>. The fader snaps between "
      "the defined zones and the label updates to show the current zone name."),
    sp(2),
    code('"range": {\n'
         '  "0-31":   "LED Off",\n'
         '  "32-63":  "LED On",\n'
         '  "64-95":  "Strobe",\n'
         '  "96-127": "LED On",\n'
         '  "128-255":"Pulse"\n'
         '}'),
    sp(2),
    p("Named ranges are ideal for strobe, colour wheel, gobo wheel, program select, "
      "and mode channels — anywhere the DMX value selects a discrete function rather "
      "than a continuous level. Always combine with <b>\"unit\": \"named\"</b> and "
      "consider adding <b>\"jump\": true</b> (see Section 5)."),
    sp(2),
    note("The key is the start value of the zone. The desk determines zone boundaries "
         "from consecutive keys. The last key's zone extends to 255. "
         "Keys must be quoted strings even though they represent numbers."),
    sp(4),
]

# ── 4. Unit ───────────────────────────────────────────────────────────────────
story += [
    h1("4. The unit Field"),
    sp(2),
    value_table([
        ("%",     "Percentage display. Range should be [0, 100]. "
                  "Value is shown as 0%–100% on the fader. "
                  "DMX output is scaled: 100% = DMX 255, 50% = DMX 127 etc. "
                  "Use for intensity, dimmer, and colour mixing channels."),
        ("raw",   "Direct DMX value display. Range should be [0, 255]. "
                  "Value shown as 0–255. No scaling — fader value = DMX value. "
                  "Use when you need precise DMX control or when the fixture "
                  "manual specifies exact DMX values."),
        ("named", "Named selector display. Range must be a named dict (see 3.2). "
                  "Fader becomes a selector that snaps between named zones. "
                  "The zone name is shown instead of a number. "
                  "Use for mode, program, strobe, colour wheel, gobo channels."),
    ]),
    sp(4),
]

# ── 5. Jump Channels ──────────────────────────────────────────────────────────
story += [
    h1("5. Jump Channels  (\"jump\": true)"),
    sp(2),
    p("When a scene is recalled with a fade time, most channels interpolate smoothly "
      "from their current value to the target value. Jump channels bypass this and "
      "snap instantly — like professional console mark/unmark behaviour."),
    sp(2),
    h2("5.1 Snap at Start (fade-in)"),
    p("When the fixture's master channel is increasing (or going from zero), "
      "jump channels snap to their target value <b>at the beginning</b> of the fade, "
      "before intensity rises. The fixture arrives at full brightness already "
      "in the correct mode, colour, or gobo position."),
    sp(2),
    h2("5.2 Snap at End (fade-out)"),
    p("When the fixture's master channel is going to zero, jump channels snap "
      "<b>after</b> the fade completes. The audience never sees the channel "
      "fading through intermediate values — the change happens silently in the dark."),
    sp(2),
    h2("5.3 When to use jump"),
    p("Add <b>\"jump\": true</b> to channels where fading through intermediate "
      "values would be wrong or ugly:"),
    sp(2),
    value_table([
        ("Strobe",         "Fading from 0 to 64 would briefly strobe — snap instead."),
        ("Colour wheel",   "Fading through intermediate positions shows wrong colours."),
        ("Gobo wheel",     "Intermediate positions show split gobos — always snap."),
        ("Program select", "Stepping through programs looks unintentional."),
        ("Mode channels",  "Any channel that selects a mode rather than a level."),
        ("Prism",          "Intermediate values may cause unexpected effects."),
        ("Reset",          "Should never interpolate — always jump."),
        ("Dimming curves", "Changing curve mid-fade produces unpredictable results."),
    ]),
    sp(4),
]

# ── 6. Role ───────────────────────────────────────────────────────────────────
story += [
    h1("6. The role Field"),
    sp(2),
    p("The role field assigns special behaviour to a channel beyond its normal "
      "fader display."),
    sp(2),
    value_table([
        ('"role": "pan"',
         'Marks this channel as the Pan (horizontal movement) channel. '
         'When both pan and tilt roles are present in the same fixture, '
         'an XY joystick pad appears on the faceplate. '
         'Dragging the pad sets both pan and tilt simultaneously. '
         'The fader is still shown for fine control.'),
        ('"role": "tilt"',
         'Marks this channel as the Tilt (vertical movement) channel. '
         'Works in conjunction with the pan role to enable the XY pad. '
         'Default value 128 (centre) is recommended for both pan and tilt.'),
    ]),
    sp(2),
    note("The XY pad appears in the same row as colour faders (R/G/B/W etc) "
         "to keep the fixture widget compact. If there are no colour channels, "
         "the pad gets its own row. Pan fine and tilt fine channels (16-bit) "
         "should be set to \"show\": false to keep the faceplate clean — "
         "the XY pad provides sufficient positional control for most purposes."),
    sp(4),
]

# ── 7. The lockable Flag ───────────────────────────────────────────────────────
story += [
    h1("7. The lockable Flag"),
    sp(2),
    p("Set at the top level of the fixture definition (not inside a channel). "
      "When true, a lock button appears on the fader for each channel."),
    sp(2),
    code('{\n'
         '  "channels": [ ... ],\n'
         '  "lockable": true\n'
         '}'),
    sp(2),
    p("Locking a channel prevents it from being changed by scene recalls. "
      "The channel stays at its current value regardless of what the recalled "
      "scene specifies. An <b>UNLOCK ALL</b> button in the footer clears all locks."),
    sp(2),
    p("Use lockable for fixtures that must not be affected by show cues — "
      "house lights, work lights, and special effects cannons are the primary use cases. "
      "A dedicated <b>houselights.json</b> fixture type is provided which is "
      "identical to dimmer.json but with lockable: true."),
    sp(4),
]

# ── 8. Complete Examples ───────────────────────────────────────────────────────
story += [
    h1("8. Complete Examples"),
    sp(2),

    h2("8.1 Simple Dimmer"),
    code('{\n'
         '  "channels": [\n'
         '    {"label": "Dimmer", "master": true, "default": 0,\n'
         '     "range": [0, 100], "unit": "%", "show": true}\n'
         '  ]\n'
         '}'),
    sp(4),

    h2("8.2 RGBW LED Fixture"),
    code('{\n'
         '  "channels": [\n'
         '    {"label": "Intensity", "master": true,  "default": 0,\n'
         '     "range": [0, 100], "unit": "%", "show": true},\n'
         '    {"label": "R",         "master": false, "default": 0,\n'
         '     "range": [0, 100], "unit": "%", "show": true},\n'
         '    {"label": "G",         "master": false, "default": 0,\n'
         '     "range": [0, 100], "unit": "%", "show": true},\n'
         '    {"label": "B",         "master": false, "default": 0,\n'
         '     "range": [0, 100], "unit": "%", "show": true},\n'
         '    {"label": "W",         "master": false, "default": 255,\n'
         '     "range": [0, 100], "unit": "%", "show": true}\n'
         '  ]\n'
         '}'),
    sp(4),

    h2("8.3 Fixture with Strobe and Program (jump channels)"),
    code('{\n'
         '  "channels": [\n'
         '    {"label": "R",       "master": false, "default": 0,\n'
         '     "range": [0, 100],  "unit": "%", "show": true},\n'
         '    {"label": "G",       "master": false, "default": 0,\n'
         '     "range": [0, 100],  "unit": "%", "show": true},\n'
         '    {"label": "B",       "master": false, "default": 0,\n'
         '     "range": [0, 100],  "unit": "%", "show": true},\n'
         '    {"label": "Strobe",  "master": false, "default": 32,\n'
         '     "range": {"0-31":"Off","32-63":"On","64-255":"Strobe"},\n'
         '     "unit": "named", "show": true, "jump": true},\n'
         '    {"label": "Program", "master": false, "default": 0,\n'
         '     "range": {"0-10":"Off","11-50":"Prog 1","51-100":"Prog 2",\n'
         '               "101-255":"Sound Active"},\n'
         '     "unit": "named", "show": true, "jump": true},\n'
         '    {"label": "Master",  "master": true,  "default": 0,\n'
         '     "range": [0, 100],  "unit": "%", "show": true}\n'
         '  ]\n'
         '}'),
    sp(4),

    h2("8.4 Moving Head with Pan/Tilt XY Pad"),
    code('{\n'
         '  "channels": [\n'
         '    {"label": "Pan",      "master": false, "default": 128,\n'
         '     "range": [0, 255], "unit": "raw", "show": true, "role": "pan"},\n'
         '    {"label": "Pan Fine", "master": false, "default": 0,\n'
         '     "range": [0, 255], "unit": "raw", "show": false},\n'
         '    {"label": "Tilt",     "master": false, "default": 128,\n'
         '     "range": [0, 255], "unit": "raw", "show": true, "role": "tilt"},\n'
         '    {"label": "Tilt Fine","master": false, "default": 0,\n'
         '     "range": [0, 255], "unit": "raw", "show": false},\n'
         '    {"label": "Dimmer",   "master": true,  "default": 0,\n'
         '     "range": [0, 255], "unit": "raw", "show": true},\n'
         '    {"label": "Colour",   "master": false, "default": 0,\n'
         '     "range": {"0-9":"White","10-19":"Red","20-29":"Green",\n'
         '               "30-39":"Blue","40-49":"Yellow"},\n'
         '     "unit": "named", "show": true, "jump": true},\n'
         '    {"label": "Gobo",     "master": false, "default": 0,\n'
         '     "range": {"0-9":"Open","10-19":"Gobo 1","20-29":"Gobo 2"},\n'
         '     "unit": "named", "show": true, "jump": true}\n'
         '  ]\n'
         '}'),
    sp(4),

    h2("8.5 Lockable House Lights"),
    code('{\n'
         '  "channels": [\n'
         '    {"label": "Dimmer", "master": true, "default": 0,\n'
         '     "range": [0, 100], "unit": "%", "show": true}\n'
         '  ],\n'
         '  "lockable": true\n'
         '}'),
    sp(4),
]

# ── 9. Quick Reference ─────────────────────────────────────────────────────────
story += [
    h1("9. Quick Reference"),
    sp(2),
    h2("Colour swatch automatic activation"),
    p("A colour swatch appears automatically when the fixture has channels with "
      "labels from this list: R, G, B, W, A, UV. No special configuration needed."),
    sp(3),
    h2("DMX scaling rules"),
    value_table([
        ('unit: "%",  range: [0,100]',  "Fader 0–100 → DMX 0–255 (linear scale)"),
        ('unit: "raw", range: [0,255]', "Fader 0–255 → DMX 0–255 (no scaling)"),
        ('unit: "named"',               "Fader value sent directly to DMX with no scaling"),
    ]),
    sp(3),
    h2("Hidden channel defaults"),
    p("Hidden channels (\"show\": false) send their default value to DMX immediately "
      "when the fixture is loaded. This is the correct way to handle channels like "
      "Pan Fine / Tilt Fine, reserved channels, or mode-select channels that should "
      "always be at a fixed value."),
    sp(3),
    h2("File naming"),
    p("The filename (without .json) is used as the fixture type in patch.json. "
      "Use lowercase with underscores: <b>my_fixture.json</b> → "
      "<b>\"type\": \"my_fixture\"</b>. "
      "Avoid spaces and special characters in filenames."),
    sp(3),
    h2("Loading and caching"),
    p("Fixture definitions are cached in memory when first loaded. "
      "After editing a .json file, use <b>Save &amp; Reload</b> in the patch editor "
      "to pick up the changes. The cache clears automatically on reload."),
]

story += [
    sp(6),
    HRFlowable(width="100%", thickness=0.5, color=MGREY),
    sp(2),
    Paragraph("DMX Desk Emulator  —  Fixture Definition Reference",
              ParagraphStyle("Footer", parent=styles["Normal"],
                             fontSize=8, textColor=DGREY, alignment=TA_CENTER)),
]

doc.build(story)
print("Written to /home/claude/DMX_Desk_Fixture_Definitions.pdf")
