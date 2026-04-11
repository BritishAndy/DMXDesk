"""
Generate DMX Desk Emulator user manual PDFs:
  - DMX_Desk_Manual.pdf        (full manual)
  - DMX_Desk_Quick_Reference.pdf (one-page quick ref)
"""

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, KeepTogether
)

GOLD     = colors.HexColor("#ffcc00")
AMBER    = colors.HexColor("#ddaa00")
DIM_GREY = colors.HexColor("#aaaaaa")
MID_GREY = colors.HexColor("#666666")
WHITE    = colors.white

def make_styles():
    base = ParagraphStyle('base', fontName='Helvetica', fontSize=10,
                           textColor=colors.black, leading=14)
    return dict(
        title     = ParagraphStyle('T',  parent=base, fontSize=28,
                                    fontName='Helvetica-Bold', textColor=GOLD,
                                    alignment=TA_CENTER, spaceAfter=6),
        subtitle  = ParagraphStyle('St', parent=base, fontSize=14,
                                    textColor=DIM_GREY, alignment=TA_CENTER, spaceAfter=4),
        section   = ParagraphStyle('S',  parent=base, fontSize=14,
                                    fontName='Helvetica-Bold', textColor=GOLD,
                                    spaceBefore=14, spaceAfter=4),
        subsection= ParagraphStyle('Ss', parent=base, fontSize=11,
                                    fontName='Helvetica-Bold', textColor=AMBER,
                                    spaceBefore=8, spaceAfter=3),
        body      = ParagraphStyle('B',  parent=base, fontSize=9,
                                    textColor=colors.HexColor("#222222"),
                                    leading=13, spaceAfter=4),
        note      = ParagraphStyle('N',  parent=base, fontSize=8,
                                    textColor=MID_GREY, leading=12,
                                    leftIndent=8, spaceAfter=3),
        kbd       = ParagraphStyle('K',  parent=base, fontSize=9,
                                    fontName='Courier',
                                    textColor=colors.HexColor("#224422"),
                                    leading=13, spaceAfter=2),
    )

ST = make_styles()

def p(text, style='body'):   return Paragraph(text, ST[style])
def sp(n=4):                 return Spacer(1, n * mm)
def hr():
    return HRFlowable(width="100%", thickness=0.5,
                      color=colors.HexColor("#cccccc"), spaceAfter=4)
def section_title(text):     return KeepTogether([hr(), p(text, 'section')])
def sub(text):               return p(text, 'subsection')

def key_table(rows, col_widths=None):
    data = [[p('<b>' + k + '</b>', 'body'), p(v, 'body')] for k, v in rows]
    cw = col_widths or [55*mm, 110*mm]
    t = Table(data, colWidths=cw)
    t.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (0,-1), colors.HexColor("#f0f0f0")),
        ('FONTNAME',      (0,0), (0,-1), 'Courier'),
        ('FONTSIZE',      (0,0), (-1,-1), 9),
        ('VALIGN',        (0,0), (-1,-1), 'TOP'),
        ('ROWBACKGROUNDS',(0,0), (-1,-1), [WHITE, colors.HexColor("#f8f8f8")]),
        ('GRID',          (0,0), (-1,-1), 0.25, colors.HexColor("#cccccc")),
        ('TOPPADDING',    (0,0), (-1,-1), 3),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ('LEFTPADDING',   (0,0), (-1,-1), 5),
        ('RIGHTPADDING',  (0,0), (-1,-1), 5),
    ]))
    return t


def build_full_manual(path):
    doc = SimpleDocTemplate(path, pagesize=A4,
                             leftMargin=18*mm, rightMargin=18*mm,
                             topMargin=18*mm, bottomMargin=18*mm,
                             title="DMX Desk Emulator - User Manual",
                             author="DMX Desk")
    story = []

    story += [
        sp(20), p("DMX Desk Emulator", 'title'),
        p("User Manual", 'subtitle'), sp(2),
        p("v1.0  -  Art-Net DMX Control Software for macOS", 'subtitle'),
        sp(10),
        HRFlowable(width="60%", thickness=2, color=GOLD, hAlign='CENTER', spaceAfter=8),
        sp(4),
        p("A software lighting desk that outputs DMX over Art-Net UDP. "
          "Supports dimmers, RGB, RGBW and complex multi-channel fixtures, "
          "relay/digital fixtures, submasters, scenes with fade times, "
          "a built-in clock and timer, QLab OSC integration, "
          "and a full patch editor with Open Fixture Library support.", 'body'),
        PageBreak(),
    ]

    story += [
        p("Contents", 'section'),
        key_table([
            ("1. Getting Started",        "Launching the app, Art-Net setup"),
            ("2. The Main Interface",     "Header, fixture panel, footer"),
            ("3. Fixtures",               "Faders, solos, colour swatches"),
            ("4. Digital Fixtures",       "Relay and on/off fixture control"),
            ("5. Grand Master",           "Overall level control"),
            ("6. Submasters",             "Group level control"),
            ("7. Scene Memory",           "Recording, recalling, naming, colouring"),
            ("8. Fade Times",             "Setting, using and stopping fades"),
            ("9. Solo & Record",          "Partial scene recording"),
            ("10. Copy & Paste",          "Copying fixture states"),
            ("11. Group Selection",       "Ganging fixtures together"),
            ("12. Clock & Timers",        "Clock, stopwatch, countdown"),
            ("13. Patch Editor",          "Managing the fixture patch"),
            ("14. Fixture Definitions",   "JSON fixture files explained"),
            ("15. Open Fixture Library",  "Importing fixtures from OFL"),
            ("16. Settings",              "Art-Net, appearance, behaviour, OSC"),
            ("17. Save & Load",           "Saving shows and patches"),
            ("18. QLab Integration",      "OSC control from QLab"),
            ("19. Keyboard & Mouse",      "Quick reference"),
        ], col_widths=[60*mm, 105*mm]),
        PageBreak(),
    ]

    story += [
        section_title("1. Getting Started"),
        sub("Launching"),
        p("Double-click <b>DMX Desk.app</b> in Finder, or from Terminal:"),
        p("  python3 desk.py              - launches with default settings", 'kbd'),
        p("  python3 desk.py --dry-run    - no Art-Net output (testing)", 'kbd'),
        sp(2), sub("First Launch"),
        p("On first launch the app creates <b>desk_prefs.json</b> alongside desk.py "
          "to store window size, settings and the last loaded show file. "
          "Your patch file <b>patch.json</b> must be in the same folder."),
        sp(2), sub("Art-Net Setup"),
        p("Configure the target IP, port (default 6454) and universe (default 0) "
          "in Settings. The ArtNet indicator shows green when the node responds to ping."),
        sp(2), sub("On Exit"),
        p("A final DMX frame is sent with each fixture's default channel values "
          "so lights hold their default state rather than snapping to zero."),
    ]

    story += [
        section_title("2. The Main Interface"),
        sub("Top Bar"),
        key_table([
            ("DMX DESK EMULATOR v...", "App title and version."),
            ("Show: filename",         "Currently loaded show file (green)."),
            ("ArtNet",                 "Green = node reachable, red = unreachable, grey = dry run."),
            ("? Help",                 "Opens this manual."),
            ("Edit Patch",             "Opens the patch editor."),
            ("Settings",               "Opens the settings dialog."),
        ]),
        sp(3), sub("Footer - Scene Buttons"),
        p("30 scene buttons in two rows of 15. Left click to recall. "
          "Right double-click to edit name and colour. Ctrl+drag to reorder."),
        sp(3), sub("Footer - Controls Strip"),
        key_table([
            ("REC",           "Record current output to selected scene."),
            ("CLR",           "Clear selected scene (with confirmation)."),
            ("Fade (s)",      "Fade time in seconds for scene recall."),
            ("STOP FADE",     "Interrupts a running fade, leaving faders where they are. "
                               "Lights amber during an active fade."),
            ("CLEAR SOLOS",   "Clears all active solo buttons."),
            ("SAVE / LOAD",   "Save or load a show file."),
            ("- / +",         "Zoom 25% to 175% in 5% steps."),
            ("GRAND MASTER",  "Scales all DMX output proportionally."),
        ]),
    ]

    story += [
        section_title("3. Fixtures"),
        sub("Master Fader"),
        p("The large vertical fader controls intensity. Double-click the value to type directly."),
        sp(2), sub("Colour Faders"),
        p("R/G/B/W/A/UV channels appear below the master. "
          "The master fader track shows the live colour mix as a swatch."),
        sp(2), sub("Non-Colour Channels"),
        p("Channels such as Strobe, Zoom, Mode appear beside the master. "
          "Named-range channels show the current mode name."),
        sp(2), sub("Solo Buttons"),
        p("Each channel has a small S button for partial recording. "
          "Solo fix solos all channels and illuminates all S buttons."),
        sp(2), sub("Submaster Tint"),
        p("Amber highlight border when a submaster is scaling the fixture below 100%."),
    ]

    story += [
        section_title("4. Digital Fixtures"),
        p("Fixtures where all channels are binary (On/Off) show a digital faceplate "
          "with toggle buttons instead of faders."),
        sp(2),
        key_table([
            ("Dark grey",  "Channel is Off."),
            ("Bright green","Channel is On."),
            ("Click button","Toggle on or off."),
            ("layout",     'Set "layout": "vertical" or "horizontal" in the fixture JSON. '
                           'Omit for auto (horizontal if 3 or fewer channels).'),
        ]),
        sp(2),
        p("Digital fixture state is fully stored and recalled in scenes."),
    ]

    story += [
        section_title("5. Grand Master"),
        p("The GM fader scales all fixture output. At 0% all channels output zero. "
          "Restoring GM returns to the same levels."),
    ]

    story += [
        section_title("6. Submasters"),
        p("Submasters control named groups of fixtures. "
          "An amber border indicates below 100%. "
          "Fixtures being scaled show an amber highlight border."),
        sp(2),
        p('Define in patch.json: {"type": "submaster", "name": "Wash Sub", '
          '"targets": ["Wash 1", "Wash 2"]}', 'kbd'),
    ]

    story += [
        section_title("7. Scene Memory"),
        sub("Recording"),
        p("Set levels then click REC. If solos are active a dialog asks whether to "
          "clear solos and record all, record partial, or cancel."),
        sp(2), sub("Recalling"),
        p("Click a scene button. Buttons are disabled during a fade. "
          "Use STOP FADE to interrupt."),
        sp(2), sub("Naming and Colour"),
        p("Right double-click to open the Edit Scene dialog. "
          "Set the name and optionally a button colour (shown as a dark tint). "
          "Saved swatches in the colour picker are stored by macOS."),
        sp(2), sub("Reordering"),
        p("Ctrl+drag a scene button to swap it with another slot. "
          "Data, name and colour all move together."),
        sp(2), sub("Auto-save"),
        p("Scenes save automatically on every change to the currently loaded show file."),
    ]

    story += [
        section_title("8. Fade Times"),
        p("The Fade (s) entry sets the fade time (decimals allowed). "
          "Each scene stores its own fade time."),
        sp(2), sub("Stopping a Fade"),
        p("STOP FADE lights amber during a fade. "
          "Pressing it halts the fade immediately at the current fader positions "
          "and re-enables the scene buttons."),
    ]

    story += [
        section_title("9. Solo & Record (Partial Scenes)"),
        key_table([
            ("S button",      "Solos that channel (amber)."),
            ("Solo fix",      "Solos all channels; illuminates all S buttons."),
            ("REC + solos",   "Dialog: clear solos and record all / record partial / cancel."),
            ("CLEAR SOLOS",   "Clears all solos across all fixtures."),
            ("Scene recall",  "Illuminates solo buttons for stored channels."),
        ]),
    ]

    story += [
        section_title("10. Copy & Paste"),
        key_table([
            ("Ctrl+click fixture",  "Copy state. Compatible fixtures highlight green."),
            ("Click green",         "Paste copied state."),
            ("Escape",              "Cancel paste mode."),
        ]),
    ]

    story += [
        section_title("11. Group Selection"),
        key_table([
            ("Shift+click 1st",  "Selects the reference fixture."),
            ("Shift+click 2nd+", "Fades fixture to match reference over 1 second, then joins group."),
            ("Move any master",  "All grouped fixtures track together."),
            ("Click / Escape",   "Clears the group."),
        ]),
    ]

    story += [
        section_title("12. Clock & Timers"),
        p('Add to patch: {"type": "clock", "name": "Show Clock", "row": 1}', 'kbd'),
        sp(2), sub("Clock"), p("Shows current time HH:MM:SS."),
        sub("Stopwatch"), p("START/STOP, LAP, RST."),
        sub("Countdown"), p("Enter mm:ss. Last 10s flash amber. At zero panel flashes red."),
        sp(2), p("Timer state is preserved across zoom changes.", 'note'),
    ]

    story += [
        section_title("13. Patch Editor"),
        sub("Selecting"),
        key_table([
            ("Single-click",   "Select row."),
            ("Shift+click",    "Multi-select."),
            ("Double-click",   "Edit dialog (fields shown/hidden by type)."),
        ]),
        sp(2), sub("Adding"),
        key_table([
            ("+ Add Fixture",    "New fixture at next free address."),
            ("+ Add Sub",        "New submaster."),
            ("+ Add Divider",    "Visual separator."),
            ("+ Add Clock",      "Clock/timer widget."),
        ]),
        sp(2), sub("Other"),
        key_table([
            ("Up / Down",          "Reorder (multi-select supported)."),
            ("Delete",             "Delete selected (with confirmation)."),
            ("Edit Fixture Def",   "Open fixture JSON in built-in editor."),
            ("Create Fixture",     "New fixture from template with inline help."),
            ("Find Fixture",       "Import from Open Fixture Library."),
            ("Save & Reload",      "Save patch.json and reload immediately."),
        ]),
    ]

    story += [
        section_title("14. Fixture Definitions"),
        sub("Channel Fields"),
        key_table([
            ("label",   "Channel name. R/G/B/W/A/UV for colour channels."),
            ("master",  "true for the main intensity channel."),
            ("default", "DMX value on startup and on app exit (0-255)."),
            ("range",   '[0,255] numeric or {"0-127":"Off","128-255":"On"} named.'),
            ("unit",    '"%" percentage, "raw" DMX value, "named" mode labels.'),
            ("show",    "false to hide the channel (sends default silently)."),
        ]),
        sp(2), sub("Top-Level Fields"),
        key_table([
            ("colour", "Hex colour for the faceplate background."),
            ("layout", '"vertical" or "horizontal" for digital fixtures.'),
        ]),
    ]

    story += [
        section_title("15. Open Fixture Library"),
        key_table([
            ("First use",    "Fetches index from GitHub. Cached in ofl_fixtures.json."),
            ("Manufacturer", "Filter by manufacturer (e.g. chauvet, robe)."),
            ("Search",       "Shows up to 100 results."),
            ("Import",       "Saves fixture JSON to fixtures/."),
            ("Refresh DB",   "Re-fetches index from GitHub."),
        ]),
    ]

    story += [
        section_title("16. Settings"),
        sub("Art-Net"),
        key_table([
            ("Target IP", "IP address of your Art-Net node."),
            ("Port",      "UDP port (default 6454)."),
            ("Universe",  "Art-Net universe 0-15."),
        ]),
        sp(2), sub("Appearance"),
        key_table([
            ("Startup zoom",    "Default zoom on launch (25%-175%)."),
            ("Scene layout",    "paired = odd/even rows; sequential = 1-15 / 16-30."),
            ("Reload last show","Auto-load last show file on startup."),
        ]),
        sp(2), sub("Behaviour"),
        key_table([
            ("DMX interval", "Update rate in ms (default 25 = 40Hz)."),
            ("Fade steps",   "Interpolation resolution (default 40)."),
        ]),
        sp(2), sub("OSC Input"),
        key_table([
            ("Enable OSC", "Enable the OSC listener."),
            ("OSC Port",   "UDP port for incoming OSC (default 8000)."),
        ]),
    ]

    story += [
        section_title("17. Save & Load"),
        sub("Show Files"),
        p("Scenes save automatically to the loaded show file on every change. "
          "The filename appears in the top bar. "
          "Use SAVE to save to a new file, LOAD to open a different show. "
          "Enable Reload last show in Settings to auto-load on startup."),
        sp(2), sub("Multiple Shows"),
        p("Keep a shows/ folder with one JSON per production. "
          "The patch stays the same for the same venue; only the scenes file changes."),
    ]

    story += [
        section_title("18. QLab Integration"),
        p("The desk receives OSC from QLab to recall scenes automatically. "
          "Art-Net HTP merge at the node allows both to send simultaneously."),
        sp(2), sub("QLab Setup"),
        p("In QLab Settings > Network add a destination: type OSC, "
          "address = desk Mac IP, port = 8000, protocol UDP. "
          "Add a Network cue with the appropriate OSC message."),
        sp(2), sub("OSC Commands"),
        key_table([
            ("/desk/scene/recall 3",          "Recall scene slot 3."),
            ('/desk/scene/recall "Name"',     "Recall by name (string argument)."),
            ("/desk/scene/recall/Name",       "Recall by name (underscores = spaces)."),
            ("/desk/scene/select 3",          "Select slot without recalling."),
            ("/desk/scene/go",                "Fire selected scene."),
            ("/desk/grandmaster 80",          "Set GM to 80%."),
            ("/desk/fader/Wash1 75",          "Set fixture master to 75%."),
        ]),
        sp(2), sub("Workflow"),
        p("Program all looks as scenes in the desk. "
          "In QLab add an OSC cue alongside each lighting cue. "
          "The operator can grab any fader to adjust live at any time."),
    ]

    story += [
        section_title("19. Keyboard & Mouse"),
        key_table([
            ("Ctrl+click fixture",       "Copy fixture state"),
            ("Click green fixture",      "Paste copied state"),
            ("Shift+click fixture",      "Add to / remove from group"),
            ("Escape",                   "Cancel paste / clear group"),
            ("Left click scene",         "Recall scene"),
            ("Right double-click scene", "Edit scene name and colour"),
            ("Ctrl+drag scene",          "Reorder scene buttons"),
            ("Double-click fader value", "Type value directly"),
            ("Cmd+S (fixture editor)",   "Save fixture definition"),
            ("Return (in dialogs)",      "Confirm / apply"),
        ]),
        PageBreak(),
    ]

    doc.build(story)
    print(f"Full manual written to {path}")


def build_quick_ref(path):
    doc = SimpleDocTemplate(path, pagesize=A4,
                             leftMargin=14*mm, rightMargin=14*mm,
                             topMargin=14*mm, bottomMargin=14*mm,
                             title="DMX Desk - Quick Reference")
    story = []

    story += [
        p("DMX Desk Emulator - Quick Reference", 'title'),
        HRFlowable(width="100%", thickness=1, color=GOLD, spaceAfter=4),
        sp(1),
    ]

    def col_section(title, rows):
        items = [p('<b>' + title + '</b>', 'subsection')]
        for k, v in rows:
            items.append(key_table([(k, v)], col_widths=[42*mm, 70*mm]))
        return items

    left = []
    left += col_section("Scenes", [
        ("Left click",          "Recall scene"),
        ("Right double-click",  "Edit name / colour"),
        ("Ctrl+drag",           "Reorder"),
        ("REC",                 "Record (warns if solos active)"),
        ("CLR",                 "Clear scene"),
        ("Fade (s)",            "Set fade time"),
        ("STOP FADE",           "Interrupt running fade"),
    ])
    left += col_section("Solos & Record", [
        ("S button",            "Solo a channel"),
        ("Solo fix",            "Solo whole fixture + light S buttons"),
        ("REC with solos",      "Partial scene record"),
        ("CLEAR SOLOS",         "Clear all solos"),
    ])
    left += col_section("Copy & Paste", [
        ("Ctrl+click",          "Copy fixture state"),
        ("Click green",         "Paste to fixture"),
        ("Escape",              "Cancel paste"),
    ])
    left += col_section("Group Control", [
        ("Shift+click 1st",     "Set reference fixture"),
        ("Shift+click 2nd+",    "Fade to match, join group"),
        ("Move any master",     "All track together"),
        ("Click / Escape",      "Clear group"),
    ])

    right = []
    right += col_section("Patch Editor", [
        ("Double-click row",    "Edit entry"),
        ("Shift+click",         "Multi-select"),
        ("+ Add Fixture",       "New fixture"),
        ("Create Fixture",      "New fixture from template"),
        ("Edit Fixture Def",    "Edit fixture JSON"),
        ("Find Fixture",        "Import from OFL"),
        ("Save & Reload",       "Apply all changes"),
    ])
    right += col_section("Settings", [
        ("Art-Net IP/Port",     "Target node address"),
        ("Universe",            "Art-Net universe 0-15"),
        ("Scene layout",        "paired / sequential"),
        ("Reload last show",    "Auto-load on startup"),
        ("OSC Port",            "Default 8000"),
    ])
    right += col_section("QLab OSC", [
        ("/desk/scene/recall N",    "Recall slot N"),
        ('/desk/scene/recall "Name"',"Recall by name"),
        ("/desk/scene/recall/Name", "Recall (underscores=spaces)"),
        ("/desk/scene/go",          "Fire selected scene"),
        ("/desk/grandmaster 80",    "Set GM to 80%"),
        ("/desk/fader/Name 75",     "Set fixture to 75%"),
    ])
    right += col_section("Clock Widget", [
        ("START/STOP",          "Stopwatch / countdown"),
        ("LAP",                 "Record lap time"),
        ("RST",                 "Reset"),
        ("Flashing red",        "Countdown at zero"),
    ])

    while len(left) < len(right): left.append(sp(1))
    while len(right) < len(left): right.append(sp(1))

    two_col = Table([[left, right]], colWidths=[91*mm, 91*mm])
    two_col.setStyle(TableStyle([
        ('VALIGN',        (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING',   (0,0), (-1,-1), 0),
        ('RIGHTPADDING',  (0,0), (-1,-1), 4),
        ('TOPPADDING',    (0,0), (-1,-1), 0),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0),
    ]))
    story.append(two_col)

    story += [
        sp(2),
        HRFlowable(width="100%", thickness=0.5, color=GOLD, spaceAfter=3),
        p("Files: patch.json (patch)  |  shows/*.json (scenes)  |  "
          "desk_prefs.json (settings)  |  fixtures/ (fixture defs)  |  "
          "ofl_fixtures.json (OFL cache)", 'note'),
    ]

    doc.build(story)
    print(f"Quick reference written to {path}")


if __name__ == "__main__":
    build_full_manual("/home/claude/DMX_Desk_Manual.pdf")
    build_quick_ref("/home/claude/DMX_Desk_Quick_Reference.pdf")
