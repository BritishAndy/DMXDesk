from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.enums import TA_LEFT, TA_CENTER

W, H = A4
doc = SimpleDocTemplate(
    "/home/claude/DMX_Desk_Test_Script.pdf",
    pagesize=A4,
    leftMargin=18*mm, rightMargin=18*mm,
    topMargin=16*mm, bottomMargin=16*mm
)

styles = getSampleStyleSheet()

BG     = colors.HexColor("#1a1a2b")
GOLD   = colors.HexColor("#ffcc00")
TEAL   = colors.HexColor("#44ffee")
GREEN  = colors.HexColor("#aaffaa")
WHITE  = colors.white
GREY   = colors.HexColor("#888888")
LGREY  = colors.HexColor("#dddddd")
DGREY  = colors.HexColor("#333333")
PASS   = colors.HexColor("#22aa44")
FAIL   = colors.HexColor("#cc2222")

title_style = ParagraphStyle("Title", parent=styles["Normal"],
    fontSize=20, textColor=GOLD, spaceAfter=4, fontName="Helvetica-Bold",
    alignment=TA_CENTER)
sub_style = ParagraphStyle("Sub", parent=styles["Normal"],
    fontSize=10, textColor=GREY, spaceAfter=10, alignment=TA_CENTER)
section_style = ParagraphStyle("Section", parent=styles["Normal"],
    fontSize=13, textColor=WHITE, spaceBefore=12, spaceAfter=4,
    fontName="Helvetica-Bold", backColor=DGREY, leftIndent=-4, rightIndent=-4,
    borderPad=4)
subsec_style = ParagraphStyle("SubSec", parent=styles["Normal"],
    fontSize=10, textColor=TEAL, spaceBefore=8, spaceAfter=2,
    fontName="Helvetica-Bold")
step_style = ParagraphStyle("Step", parent=styles["Normal"],
    fontSize=9, textColor=colors.HexColor("#cccccc"), spaceAfter=2,
    leftIndent=6)
note_style = ParagraphStyle("Note", parent=styles["Normal"],
    fontSize=8, textColor=GREY, spaceAfter=4, leftIndent=6,
    fontName="Helvetica-Oblique")

def section(title):
    return [Spacer(1, 4*mm),
            Paragraph(f"  {title}", section_style),
            Spacer(1, 2*mm)]

def subsec(title):
    return [Paragraph(title, subsec_style)]

def step(text, n=None):
    prefix = f"<b>{n}.</b> " if n else "• "
    return Paragraph(prefix + text, step_style)

def note(text):
    return Paragraph(f"<i>Note: {text}</i>", note_style)

def check_table(steps):
    """Steps is list of (step_text, expected_result) tuples."""
    data = [["#", "Action", "Expected Result", "Pass", "Fail"]]
    for i, (action, expected) in enumerate(steps, 1):
        data.append([str(i), action, expected, "☐", "☐"])
    t = Table(data, colWidths=[8*mm, 72*mm, 64*mm, 12*mm, 12*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND",   (0,0), (-1,0),  DGREY),
        ("TEXTCOLOR",    (0,0), (-1,0),  GOLD),
        ("FONTNAME",     (0,0), (-1,0),  "Helvetica-Bold"),
        ("FONTSIZE",     (0,0), (-1,-1), 8),
        ("ROWBACKGROUNDS",(0,1),(-1,-1), [colors.HexColor("#1a1a1a"), colors.HexColor("#222222")]),
        ("TEXTCOLOR",    (0,1), (-1,-1), LGREY),
        ("ALIGN",        (3,0), (-1,-1), "CENTER"),
        ("VALIGN",       (0,0), (-1,-1), "MIDDLE"),
        ("GRID",         (0,0), (-1,-1), 0.3, colors.HexColor("#444444")),
        ("ROWHEIGHT",    (0,1), (-1,-1), 14),
        ("LEFTPADDING",  (0,0), (-1,-1), 4),
        ("RIGHTPADDING", (0,0), (-1,-1), 4),
        ("TOPPADDING",   (0,0), (-1,-1), 3),
        ("BOTTOMPADDING",(0,0), (-1,-1), 3),
        ("WORDWRAP",     (1,1), (2,-1), "LTR"),
    ]))
    return t

story = []

# Title
story += [
    Spacer(1, 4*mm),
    Paragraph("DMX Desk Emulator", title_style),
    Paragraph("Test Script — v1.0", sub_style),
    HRFlowable(width="100%", thickness=1, color=GOLD, spaceAfter=6),
    Paragraph("Work through each section in order. Tick Pass or Fail for each step. "
              "Note any issues in the margins.", note_style),
    Spacer(1, 2*mm),
]

# ── 1. STARTUP ────────────────────────────────────────────────────────────────
story += section("1. Startup & Basic Layout")
story.append(check_table([
    ("Launch desk.py from terminal", "App opens, no errors in terminal"),
    ("Check fixture row 1 layout", "All row 1 fixtures visible, correct order"),
    ("Check fixture row 2 layout", "All row 2 fixtures visible, correct order"),
    ("Check scene buttons", "30 scene slots visible, named slots show correct names"),
    ("Check Grand Master fader", "GM fader present, value shows 100%"),
    ("Move GM fader to 50%", "All fixture values halve smoothly"),
    ("Return GM to 100%", "All fixture values restore"),
]))

# ── 2. FIXTURES ───────────────────────────────────────────────────────────────
story += section("2. Fixture Faders")
story.append(check_table([
    ("Move a dimmer master fader", "DMX channel updates, value label tracks"),
    ("Move an RGBW master fader",  "Intensity channel updates"),
    ("Move an RGBW R fader",       "R channel updates independently"),
    ("Move an RGBW G fader",       "G channel updates independently"),
    ("Move an RGBW B fader",       "B channel updates independently"),
    ("Move an RGBW W fader",       "W channel updates independently"),
    ("Double-click a fader value", "Entry field appears, accepts numeric input"),
    ("Enter a value and press Enter","Fader snaps to entered value"),
    ("Press S solo button on a channel","Solo illuminates amber"),
    ("Press S again",               "Solo locks red"),
    ("Press S again",               "Solo clears"),
    ("Press CLEAR SOLOS",           "All amber solos clear"),
    ("Press CLEAR LOCKS",           "All red locks clear"),
]))

# ── 3. SCENES ─────────────────────────────────────────────────────────────────
story += section("3. Scene Recording & Recall")
story.append(check_table([
    ("Set some faders to non-zero values", "Faders at desired levels"),
    ("Right-click an empty scene slot", "Context panel opens"),
    ("Enter a name, click Record", "Slot shows name, green background"),
    ("Move faders to different values", "Faders move"),
    ("Click the recorded scene button", "Faders return to recorded values"),
    ("Record a second scene with different values", "Second slot shows name"),
    ("Recall scene 1 then scene 2 rapidly", "Each recall works correctly"),
    ("Set a fade time of 3s, record a scene", "Fade time saved with scene"),
    ("Recall scene with fade time", "Faders move smoothly over 3 seconds"),
    ("Press STOP during a fade", "Fade stops immediately at current position"),
    ("Right-click scene, change colour", "Scene button shows tinted background"),
    ("Ctrl+drag a scene button", "Scene reorders to new position"),
]))

# ── 4. GROUPS ─────────────────────────────────────────────────────────────────
story += section("4. Groups")
story += subsec("4a. Dimmer Group")
story.append(check_table([
    ("Locate dimmer group, ACT amber, outline visible", "Group shows with correct name"),
    ("Move group master fader with ACT on", "All member dimmers move together"),
    ("Move group master with ACT off", "Members do not move, no DMX output"),
    ("Click › to expand", "Member fixture panels appear to right"),
    ("Move one member fader independently", "ACT extinguishes immediately"),
    ("Press ACT", "ACT illuminates, members align to group over 0.5s"),
    ("Move group master", "All members follow again"),
    ("Click ‹ to collapse", "Member panels hide, group strip remains"),
]))
story += subsec("4b. RGBW Group")
story.append(check_table([
    ("Check group shows RGBW faders", "Master strip matches member fixture type"),
    ("Move group R fader with ACT on", "All members' R channels move together"),
    ("Move member R independently", "ACT extinguishes"),
    ("Record scene: group at 50%, ACT on", "Scene button appears"),
    ("Change group to 0%, recall scene with 2s fade", "Members fade to 50%, master tracks smoothly"),
    ("Check ACT status after recall", "ACT on, matches recorded state"),
    ("Zoom in/out", "ACT state preserved after zoom"),
]))

# ── 5. SEQUENCES ──────────────────────────────────────────────────────────────
story += section("5. Sequences")
story += subsec("5a. Basic Sequence")
story.append(check_table([
    ("Right-click empty slot, Convert to sequence", "Sequence editor opens"),
    ("Add 3 scene steps with different fades", "Steps appear in editor"),
    ("Save sequence", "Slot shows ▶ prefix"),
    ("Click sequence button", "Steps fire in order, button stays gold"),
    ("Watch timing", "Each fade takes correct duration"),
    ("Press another scene during sequence", "Sequence stops, scene fires"),
]))
story += subsec("5b. Loop & Wait")
story.append(check_table([
    ("Add a Loop step (until GO)", "Loop row shows in editor"),
    ("Run sequence", "Sequence loops continuously"),
    ("Press sequence button while looping", "Loop exits after iteration, continues"),
    ("Add a Wait step", "Wait row shows in editor"),
    ("Run sequence to Wait step", "Sequence pauses, button stays gold"),
    ("Press sequence button at Wait", "Sequence advances to next step"),
    ("Press STOP during sequence", "Sequence stops immediately"),
]))
story += subsec("5c. Channel Steps")
story.append(check_table([
    ("Add a Channel step targeting a group", "Group appears in fixture dropdown"),
    ("Set channel, value and fade", "Step saves correctly"),
    ("Run sequence", "Channel fades to target value over specified time"),
    ("Add simultaneous steps (gap=0)", "Multiple steps fire at same instant"),
    ("Add negative gap step", "Next step starts before previous fade ends"),
]))

# ── 6. OSC ────────────────────────────────────────────────────────────────────
story += section("6. OSC Integration")
story.append(check_table([
    ("Send /desk/scene/recall 1 from QLab", "Scene 1 recalled"),
    ("Send /desk/scene/go", "Next scene or sequence advances"),
    ("Send /desk/grandmaster 50", "GM fader moves to 50%"),
    ("Send /desk/fader/FixtureName 128", "Named fixture master updates"),
    ("Trigger a Wait sequence via OSC go", "Sequence advances at Wait step"),
]))

# ── 7. PATCH EDITOR ───────────────────────────────────────────────────────────
story += section("7. Patch Editor")
story.append(check_table([
    ("Open patch editor", "All fixtures listed with correct types"),
    ("Double-click a fixture entry", "Edit dialog opens"),
    ("Change fixture row (1/2)", "Dialog shows Row dropdown"),
    ("Save patch, verify reload", "Fixture appears on correct row"),
    ("Add a Group entry", "Group type available, Members field shown"),
    ("Enter member names, save", "Group appears in fixture area"),
    ("Edit group outline colour", "Outline colour field available"),
    ("Reload patch", "Group shows correct outline colour"),
    ("Check no duplicate fixtures", "Group members not shown individually"),
]))

# ── 8. ZOOM ───────────────────────────────────────────────────────────────────
story += section("8. Zoom & Appearance")
story.append(check_table([
    ("Click + zoom button", "Fixtures scale up"),
    ("Click - zoom button", "Fixtures scale down"),
    ("Check fixture proportions at various zooms", "No jumping or resizing on fader move"),
    ("Check scene buttons at various zooms", "Consistent height, no resize on right-click"),
    ("Close and reopen app", "Zoom level restored from preferences"),
]))

# ── 9. ART-NET ────────────────────────────────────────────────────────────────
story += section("9. Art-Net Output")
story.append(check_table([
    ("Run monitor.py or DMX Monitor app", "DMX channels visible"),
    ("Move a dimmer fader", "Corresponding DMX channel updates in monitor"),
    ("Move an RGBW fixture fader", "Correct DMX channels update"),
    ("Recall a scene with fade", "DMX values change smoothly in monitor"),
    ("Check 40Hz output rate", "Monitor shows continuous updates"),
]))

# ── 10. GENERAL ───────────────────────────────────────────────────────────────
story += section("10. Stability & Edge Cases")
story.append(check_table([
    ("Run sequence while zoom changes", "Zoom ignored during sequence (no crash)"),
    ("Record scene during fade", "Scene records current mid-fade values"),
    ("Load a different show file", "Scenes update, fixtures unchanged"),
    ("Save show, close, reopen", "All scenes restore correctly"),
    ("Open sequence editor during playback", "No crash"),
    ("Check terminal for errors after full test", "No unhandled exceptions"),
]))

story += [
    Spacer(1, 6*mm),
    HRFlowable(width="100%", thickness=1, color=GREY),
    Spacer(1, 2*mm),
    Paragraph("Test completed by: ___________________________  Date: ___________  "
              "Build: ___________", note_style),
    Spacer(1, 2*mm),
    Paragraph("Issues found:", note_style),
    Spacer(1, 16*mm),
]

doc.build(story)
print("Done")
